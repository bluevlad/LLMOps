"""관제 알림 평가 — 신호 수집 → fingerprint reconcile → llm_alerts 저장 → Slack.

신호 (표준 §3-5 kind):
- ollama_unreachable        critical  Ollama /api/ps 도달 불가
- expected_resident_missing warning   EXPECTED_RESIDENT_MODELS 가 메모리에 없음
- failure_spike             warning   24h 실패 ≥ ALERT_FAIL_MIN_COUNT 이고 실패율 ≥ ALERT_FAIL_RATE_THRESHOLD
- contract_anomaly          warning   24h 보고 계약 위반 (미등록 모델명 · deprecated 모델 호출 · model 누락)
- retire_candidate          info      수명주기 판정 retire-candidate (60일 미호출 + 90일 비교 0)

열린 알림은 fingerprint 로 유일. 신호가 사라지면 resolved_at 을 찍고(critical/warning 은 Slack 해결 알림),
같은 신호가 계속되면 갱신하며, 미발송 critical/warning은 횟수·간격 제한 안에서 재시도한다.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import model_monitor
from app.core.config import settings
from app.database.session import AsyncSessionLocal
from app.models.batch_run import BatchRun, BatchRunStage
from app.models.monitor import LlmAlert
from app.monitor import notify

logger = logging.getLogger(__name__)

CONTRACT_KINDS = ("unregistered_model", "deprecated_model_called", "missing_model")

_last_evaluated_at: datetime | None = None
_last_result: dict[str, Any] | None = None


@dataclass
class Signal:
    kind: str
    severity: str
    fingerprint: str
    title: str
    message: str
    model_id: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 신호 수집
# ---------------------------------------------------------------------------

async def _failure_spikes(db: AsyncSession, now: datetime) -> list[Signal]:
    since = now - timedelta(hours=24)
    rows = (await db.execute(
        select(
            BatchRunStage.model,
            func.count(BatchRunStage.id),
            func.count(BatchRunStage.id).filter(BatchRunStage.ok.is_(False)),
        )
        .join(BatchRun, BatchRunStage.batch_run_id == BatchRun.id)
        .where(BatchRun.started_at >= since, BatchRunStage.model.isnot(None))
        .group_by(BatchRunStage.model)
    )).all()
    return failure_signals(rows, settings.alert_fail_rate_threshold, settings.alert_fail_min_count)


def failure_signals(rows: list[tuple[str, int, int]], threshold: float, min_count: int) -> list[Signal]:
    """순수 함수 — rows: (model, calls_24h, fails_24h)."""
    out: list[Signal] = []
    for model, calls, fails in rows:
        if calls <= 0 or fails < min_count:
            continue
        rate = fails / calls
        if rate < threshold:
            continue
        out.append(Signal(
            kind="failure_spike", severity="warning", model_id=model,
            fingerprint=f"failure_spike:{model}",
            title=f"실패율 급증 — {model}",
            message=f"최근 24h 호출 {calls}건 중 실패 {fails}건 ({rate * 100:.0f}%)",
            detail={"calls_24h": calls, "fails_24h": fails, "rate": round(rate, 3)},
        ))
    return out


def resident_signals(live: Any, expected: list[str]) -> list[Signal]:
    """순수 함수 — live: LiveOut(reachable, models[].model_id)."""
    if not live.reachable:
        return [Signal(
            kind="ollama_unreachable", severity="critical", fingerprint="ollama_unreachable",
            title="Ollama 도달 불가", message=f"/api/ps 실패: {live.error or 'unknown'}",
            detail={"error": live.error},
        )]
    loaded = {m.model_id for m in live.models}
    return [
        Signal(
            kind="expected_resident_missing", severity="warning", model_id=m,
            fingerprint=f"expected_resident_missing:{m}",
            title=f"상주 이탈 — {m}",
            message="EXPECTED_RESIDENT_MODELS 에 있으나 Ollama 메모리에 올라와 있지 않음",
            detail={"loaded": sorted(loaded)},
        )
        for m in expected if m not in loaded
    ]


def lifecycle_signals(stats_rows: list[Any]) -> list[Signal]:
    """순수 함수 — stats_rows: ModelStatsOut 유사 (model_id, lifecycle, last_call_ever, last_comparison_at)."""
    out: list[Signal] = []
    for r in stats_rows:
        if r.lifecycle != "retire-candidate":
            continue
        out.append(Signal(
            kind="retire_candidate", severity="info", model_id=r.model_id,
            fingerprint=f"retire_candidate:{r.model_id}",
            title=f"퇴출 후보 — {r.model_id}",
            message=f"60일 호출 0 · 90일 비교 0 (마지막 호출 {r.last_call_ever or '없음'}, 마지막 비교 {r.last_comparison_at or '없음'})",
            detail={"last_call_ever": str(r.last_call_ever), "last_comparison_at": str(r.last_comparison_at),
                    "size_bytes": getattr(r, "size_bytes", None)},
        ))
    return out


def contract_signals(anomalies: list[Any]) -> list[Signal]:
    """순수 함수 — anomalies: AnomalyOut 유사 (kind, model, consumer_id, count)."""
    out: list[Signal] = []
    for a in anomalies:
        if a.kind not in CONTRACT_KINDS:
            continue
        model = a.model or "-"
        out.append(Signal(
            kind="contract_anomaly", severity="warning", model_id=a.model,
            fingerprint=f"contract_anomaly:{a.kind}:{model}:{a.consumer_id}",
            title=f"보고 계약 위반 ({a.kind}) — {a.consumer_id}",
            message=f"{model}: 최근 24h {a.count}건. {a.hint}",
            detail={"anomaly_kind": a.kind, "consumer_id": a.consumer_id, "count": a.count},
        ))
    return out


async def collect_signals(db: AsyncSession, now: datetime | None = None) -> list[Signal]:
    now = now or datetime.now(timezone.utc)
    live = await model_monitor.fetch_live(force=True)
    signals = resident_signals(live, settings.expected_resident_models_list)
    signals += await _failure_spikes(db, now)
    signals += contract_signals(await model_monitor.anomaly_rows(db, 1))
    signals += lifecycle_signals(await model_monitor._stats_rows(db, 30, include_deprecated=False))
    return signals


# ---------------------------------------------------------------------------
# reconcile (순수) + 저장
# ---------------------------------------------------------------------------

@dataclass
class Reconciled:
    to_open: list[Signal]
    to_update: list[tuple[Any, Signal]]
    to_resolve: list[Any]


def reconcile(open_alerts: list[Any], signals: list[Signal]) -> Reconciled:
    by_fp = {a.fingerprint: a for a in open_alerts}
    seen: set[str] = set()
    to_open: list[Signal] = []
    to_update: list[tuple[Any, Signal]] = []
    for s in signals:
        if s.fingerprint in seen:
            continue
        seen.add(s.fingerprint)
        if s.fingerprint in by_fp:
            to_update.append((by_fp[s.fingerprint], s))
        else:
            to_open.append(s)
    to_resolve = [a for fp, a in by_fp.items() if fp not in seen]
    return Reconciled(to_open, to_update, to_resolve)


def notification_due(alert: Any, now: datetime, *, new: bool = False) -> bool:
    if alert.resolved_at is not None or alert.notified_at is not None:
        return False
    if not new and alert.severity not in ("critical", "warning"):
        return False
    if alert.notification_attempts >= settings.alert_notify_max_attempts:
        return False
    last = alert.last_notification_attempt_at
    return last is None or now - last >= timedelta(seconds=settings.alert_notify_retry_seconds)


async def send_open_notification(db: AsyncSession, alert_id: int, *, new: bool = False) -> None:
    # 한 알림에 대해 여러 evaluator가 동시에 발송하지 않도록 행 잠금.
    # 완전한 outbox는 E-2에서 구현한다. 네트워크 timeout은 notify.send의 5초다.
    alert = (await db.execute(select(LlmAlert).where(LlmAlert.id == alert_id)
                             .with_for_update(skip_locked=True)
                             .execution_options(populate_existing=True))).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if alert is None or not notification_due(alert, now, new=new):
        await db.commit()
        return
    alert.notification_attempts += 1
    alert.last_notification_attempt_at = now
    sent = await notify.send(notify.format_alert(alert, "opened"))
    if sent:
        alert.notified_at = now
    await db.commit()
    if not sent:
        logger.warning("alert notification failed: alert_id=%d attempt=%d/%d exhausted=%s",
                       alert.id, alert.notification_attempts, settings.alert_notify_max_attempts,
                       alert.notification_attempts >= settings.alert_notify_max_attempts)


async def evaluate_and_store(db: AsyncSession, *, send_notifications: bool = True) -> dict[str, Any]:
    global _last_evaluated_at, _last_result
    # API 수동 평가와 scheduler 평가를 프로세스 간에도 직렬화한다.
    # 일회성 세션 잠금 대신 transaction 잠금을 사용해 rollback 시에도 해제한다.
    await db.execute(text("SELECT pg_advisory_xact_lock(9110, 1)"))
    now = datetime.now(timezone.utc)
    signals = await collect_signals(db, now)
    open_alerts = (await db.execute(select(LlmAlert).where(LlmAlert.resolved_at.is_(None)))).scalars().all()
    r = reconcile(list(open_alerts), signals)

    opened: list[LlmAlert] = []
    for s in r.to_open:
        a = LlmAlert(kind=s.kind, severity=s.severity, model_id=s.model_id, fingerprint=s.fingerprint,
                     title=s.title, message=s.message, detail=s.detail,
                     first_seen_at=now, last_seen_at=now)
        db.add(a)
        opened.append(a)
    for a, s in r.to_update:
        a.last_seen_at = now
        a.message = s.message
        a.detail = s.detail
    for a in r.to_resolve:
        a.resolved_at = now
    await db.flush()

    # 저장되지 않은 알림을 외부로 보내지 않는다.
    await db.commit()
    if send_notifications and notify.configured():
        new_ids = {a.id for a in opened}
        pending_ids = [a.id for a in opened] + [a.id for a in open_alerts if a.resolved_at is None]
        for alert_id in pending_ids:
            await send_open_notification(db, alert_id, new=alert_id in new_ids)
        for a in r.to_resolve:
            if a.severity in ("critical", "warning") and a.notified_at is not None:
                await notify.send(notify.format_alert(a, "resolved"))

    _last_evaluated_at = now
    _last_result = {
        "evaluated_at": now, "signals": len(signals),
        "opened": len(opened), "updated": len(r.to_update), "resolved": len(r.to_resolve),
    }
    if opened or r.to_resolve:
        logger.info("alerts: opened=%d updated=%d resolved=%d", len(opened), len(r.to_update), len(r.to_resolve))
    return _last_result


async def run_once() -> dict[str, Any] | None:
    """스케줄러 진입점 — 예외는 로그만 (다음 주기에 재시도)."""
    try:
        async with AsyncSessionLocal() as db:
            return await evaluate_and_store(db)
    except Exception as exc:  # noqa: BLE001
        logger.warning("alert evaluation failed: %s", exc)
        return None


def last_evaluation() -> tuple[datetime | None, dict[str, Any] | None]:
    return _last_evaluated_at, _last_result
