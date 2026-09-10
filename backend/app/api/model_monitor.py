"""모델 모니터링 API — 모델 단위 사용량·상주 상태·품질·이상 징후 (인증 필요).

/api/models/stats      : 인벤토리 + 최근 N일 사용 집계 (목록 화면)
/api/models/live       : Ollama /api/ps 프록시 — 지금 메모리에 올라온 모델 (15초 캐시)
/api/models/anomalies  : 보고 계약 위반·미등록 모델명·deprecated 모델 호출
/api/models/detail     : 모델 1개 상세 (KPI · consumer×stage 분해 · 일별 시계열 · 품질 · 비교 이력)

데이터원은 모두 기존 테이블(batch_run_stages / comparison_results / golden_set_items) 의
온라인 집계 — DDL 변경 없음. 호스트 RAM/CPU·프로세스 생사는 InfraWatcher 몫이며
여기서는 "어떤 모델이 올라와 있고 얼마나 쓰였는가" 만 다룬다 (조작 버튼 없음).
"""
from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import model_roles
from app.api.comparisons import build_detail
from app.core.config import settings
from app.core.security import require_member
from app.database.session import get_db
from app.models.batch_run import BatchRun, BatchRunStage
from app.models.comparison import ComparisonResult, ComparisonRun
from app.models.golden_set import GoldenSetItem
from app.models.llm_model import LlmModel
from app.models.user import LlmopsUser

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/models", tags=["models-monitor"])

SPARKLINE_DAYS = 14


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class RoleOut(BaseModel):
    consumer_id: str | None
    role: str
    instrumented: bool
    note: str | None = None


class ModelStatsOut(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    # 인벤토리 (llm_models)
    model_id: str
    provider: str
    host: str
    family: str | None
    parameter_size: str | None
    quantization: str | None
    size_bytes: int | None
    source_modified_at: datetime | None
    first_seen_at: datetime
    last_seen_at: datetime
    adopted_at: date | None
    deprecated_at: date | None
    replaced_by: str | None
    notes: str | None
    # 역할 (Layer 2 수동값 우선, 비면 스냅샷)
    role_tags: list[str]
    roles: list[RoleOut]
    consumers: list[str]            # 스냅샷 ∪ 관측된 consumer
    # 최근 N일 사용
    calls: int
    fails: int
    consumer_count: int
    avg_ms: int | None
    p50_ms: int | None
    p95_ms: int | None
    tokens_in: int | None
    tokens_out: int | None
    truncated: int
    last_call_at: datetime | None       # 기간 내
    daily_calls: list[int]              # 최근 SPARKLINE_DAYS 일 (오래된 → 최신)
    # 수명주기
    last_call_ever: datetime | None
    last_comparison_at: datetime | None
    comparison_runs: int                # 전체 기간 참여 run 수
    lifecycle: str
    lifecycle_label: str


class ModelStatsListOut(BaseModel):
    days: int
    generated_at: datetime
    models: list[ModelStatsOut]


class LiveModelOut(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    model_id: str
    size_bytes: int | None
    size_vram: int | None
    context_length: int | None
    expires_at: datetime | None
    digest: str | None


class LiveOut(BaseModel):
    reachable: bool
    fetched_at: datetime
    cached: bool
    error: str | None = None
    models: list[LiveModelOut]


class AnomalyOut(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    kind: str
    model: str | None
    consumer_id: str
    count: int
    last_seen_at: datetime | None
    hint: str


class BreakdownRowOut(BaseModel):
    consumer_id: str
    stage_name: str | None
    calls: int
    fails: int
    avg_ms: int | None
    p95_ms: int | None
    tokens_in: int | None
    tokens_out: int | None
    truncated: int
    avg_quality: float | None
    last_call_at: datetime | None


class SeriesPointOut(BaseModel):
    bucket: str
    calls: int
    fails: int
    truncated: int
    p50_ms: int | None
    p95_ms: int | None


class QualityRowOut(BaseModel):
    judge: str
    n: int
    avg: float


class ComparisonHistoryOut(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    id: int
    case_name: str
    prompt_set_id: str
    started_at: datetime
    judge_model: str | None
    model_count: int
    rank: int
    result_count: int
    avg_quality: float | None
    win_rate: float | None
    avg_duration_ms: int | None


class GoldenSetCountOut(BaseModel):
    candidate: int
    approved: int
    rejected: int


class ModelDetailOut(BaseModel):
    days: int
    generated_at: datetime
    model: ModelStatsOut
    live: LiveModelOut | None
    live_reachable: bool
    breakdown: list[BreakdownRowOut]
    series: list[SeriesPointOut]
    quality: list[QualityRowOut]
    comparisons: list[ComparisonHistoryOut]
    golden_set: GoldenSetCountOut
    anomalies: list[AnomalyOut]


# ---------------------------------------------------------------------------
# Live (Ollama /api/ps)
# ---------------------------------------------------------------------------

_LIVE_TTL_SECONDS = 15.0
_live_cache: tuple[float, LiveOut] | None = None


def _parse_dt(v: Any) -> datetime | None:
    if not isinstance(v, str):
        return None
    try:
        return datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return None


def parse_ps_payload(payload: dict[str, Any]) -> list[LiveModelOut]:
    """Ollama /api/ps → LiveModelOut. 순수 함수 (단위 테스트 대상)."""
    out: list[LiveModelOut] = []
    for m in payload.get("models") or []:
        name = m.get("name") or m.get("model")
        if not name:
            continue
        out.append(LiveModelOut(
            model_id=name,
            size_bytes=m.get("size"),
            size_vram=m.get("size_vram"),
            context_length=m.get("context_length"),
            expires_at=_parse_dt(m.get("expires_at")),
            digest=m.get("digest"),
        ))
    return out


async def fetch_live(force: bool = False) -> LiveOut:
    global _live_cache
    now = time.monotonic()
    if not force and _live_cache is not None and now - _live_cache[0] < _LIVE_TTL_SECONDS:
        cached = _live_cache[1]
        return cached.model_copy(update={"cached": True})

    url = f"{settings.ollama_base_url.rstrip('/')}/api/ps"
    fetched_at = datetime.now(timezone.utc)
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            res = await client.get(url)
            res.raise_for_status()
            result = LiveOut(
                reachable=True, fetched_at=fetched_at, cached=False,
                models=parse_ps_payload(res.json()),
            )
    except Exception as exc:  # 네트워크·파싱 실패는 "도달 불가" 로 표시 (화면은 유지)
        logger.warning("Ollama ps fetch failed: %s", exc)
        result = LiveOut(
            reachable=False, fetched_at=fetched_at, cached=False,
            error=str(exc)[:200], models=[],
        )
    _live_cache = (now, result)
    return result


@router.get("/live", response_model=LiveOut)
async def live_models(
    force: bool = False,
    _user: LlmopsUser = Depends(require_member),
) -> LiveOut:
    return await fetch_live(force=force)


# ---------------------------------------------------------------------------
# Usage aggregates (batch_run_stages)
# ---------------------------------------------------------------------------

def _p95(col):
    return func.percentile_cont(0.95).within_group(col.asc())


def _p50(col):
    return func.percentile_cont(0.5).within_group(col.asc())


def _int_or_none(v: Any) -> int | None:
    return int(v) if v is not None else None


async def _usage_by_model(db: AsyncSession, since: datetime) -> dict[str, dict[str, Any]]:
    rows = (await db.execute(
        select(
            BatchRunStage.model,
            func.count(BatchRunStage.id),
            func.count(BatchRunStage.id).filter(BatchRunStage.ok.is_(False)),
            func.count(func.distinct(BatchRun.consumer_id)),
            func.avg(BatchRunStage.duration_ms),
            _p50(BatchRunStage.duration_ms),
            _p95(BatchRunStage.duration_ms),
            func.sum(BatchRunStage.tokens_in),
            func.sum(BatchRunStage.tokens_out),
            func.count(BatchRunStage.id).filter(BatchRunStage.content_truncated.is_(True)),
            func.max(BatchRun.started_at),
            func.array_agg(func.distinct(BatchRun.consumer_id)),
        )
        .join(BatchRun, BatchRunStage.batch_run_id == BatchRun.id)
        .where(BatchRun.started_at >= since, BatchRunStage.model.is_not(None))
        .group_by(BatchRunStage.model)
    )).all()
    out: dict[str, dict[str, Any]] = {}
    for (model, calls, fails, n_consumers, avg_ms, p50, p95, tin, tout, trunc, last_at, consumers) in rows:
        out[model] = {
            "calls": calls, "fails": fails, "consumer_count": n_consumers,
            "avg_ms": _int_or_none(round(avg_ms) if avg_ms is not None else None),
            "p50_ms": _int_or_none(round(p50) if p50 is not None else None),
            "p95_ms": _int_or_none(round(p95) if p95 is not None else None),
            "tokens_in": _int_or_none(tin), "tokens_out": _int_or_none(tout),
            "truncated": trunc, "last_call_at": last_at,
            "consumers": sorted(c for c in (consumers or []) if c),
        }
    return out


async def _daily_calls_by_model(db: AsyncSession, days: int) -> dict[str, list[int]]:
    """최근 N일 일별 호출 수 (스파크라인). 빈 날은 0."""
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=days - 1)
    since = datetime(start.year, start.month, start.day, tzinfo=timezone.utc)
    day_col = func.date_trunc("day", BatchRun.started_at)
    rows = (await db.execute(
        select(BatchRunStage.model, day_col, func.count(BatchRunStage.id))
        .join(BatchRun, BatchRunStage.batch_run_id == BatchRun.id)
        .where(BatchRun.started_at >= since, BatchRunStage.model.is_not(None))
        .group_by(BatchRunStage.model, day_col)
    )).all()
    index = {start + timedelta(days=i): i for i in range(days)}
    out: dict[str, list[int]] = {}
    for model, day, n in rows:
        arr = out.setdefault(model, [0] * days)
        d = day.date() if isinstance(day, datetime) else day
        i = index.get(d)
        if i is not None:
            arr[i] += n
    return out


async def _last_call_ever(db: AsyncSession) -> dict[str, datetime]:
    rows = (await db.execute(
        select(BatchRunStage.model, func.max(BatchRun.started_at))
        .join(BatchRun, BatchRunStage.batch_run_id == BatchRun.id)
        .where(BatchRunStage.model.is_not(None))
        .group_by(BatchRunStage.model)
    )).all()
    return {m: t for m, t in rows}


async def _comparison_presence(db: AsyncSession) -> dict[str, tuple[datetime, int]]:
    rows = (await db.execute(
        select(
            ComparisonResult.model_id,
            func.max(ComparisonRun.started_at),
            func.count(func.distinct(ComparisonRun.id)),
        )
        .join(ComparisonRun, ComparisonResult.comparison_run_id == ComparisonRun.id)
        .group_by(ComparisonResult.model_id)
    )).all()
    return {m: (t, n) for m, t, n in rows}


def _build_stats_row(
    r: LlmModel,
    usage: dict[str, Any] | None,
    daily: list[int],
    last_ever: datetime | None,
    comparison: tuple[datetime, int] | None,
    now: datetime,
) -> ModelStatsOut:
    u = usage or {}
    role_tags = list(r.role_tags or []) or model_roles.role_tags_for(r.model_id)
    consumers = sorted(set(model_roles.consumers_for(r.model_id)) | set(u.get("consumers", [])))
    last_cmp, n_cmp = comparison if comparison else (None, 0)
    lifecycle = model_roles.lifecycle_status(
        model_id=r.model_id,
        deprecated_at=r.deprecated_at,
        last_call_at=last_ever,
        last_comparison_at=last_cmp,
        now=now,
    )
    return ModelStatsOut(
        model_id=r.model_id, provider=r.provider, host=r.host,
        family=r.family, parameter_size=r.parameter_size, quantization=r.quantization,
        size_bytes=r.size_bytes, source_modified_at=r.source_modified_at,
        first_seen_at=r.first_seen_at, last_seen_at=r.last_seen_at,
        adopted_at=r.adopted_at, deprecated_at=r.deprecated_at,
        replaced_by=r.replaced_by, notes=r.notes,
        role_tags=role_tags,
        roles=[RoleOut(**x) for x in model_roles.roles_as_dicts(r.model_id)],
        consumers=consumers,
        calls=u.get("calls", 0), fails=u.get("fails", 0),
        consumer_count=u.get("consumer_count", 0),
        avg_ms=u.get("avg_ms"), p50_ms=u.get("p50_ms"), p95_ms=u.get("p95_ms"),
        tokens_in=u.get("tokens_in"), tokens_out=u.get("tokens_out"),
        truncated=u.get("truncated", 0), last_call_at=u.get("last_call_at"),
        daily_calls=daily,
        last_call_ever=last_ever, last_comparison_at=last_cmp, comparison_runs=n_cmp,
        lifecycle=lifecycle,
        lifecycle_label=model_roles.LIFECYCLE_LABELS.get(lifecycle, lifecycle),
    )


async def _stats_rows(
    db: AsyncSession, days: int, include_deprecated: bool, only_model: tuple[str, str] | None = None,
) -> list[ModelStatsOut]:
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)

    stmt = select(LlmModel)
    if only_model is not None:
        stmt = stmt.where(LlmModel.provider == only_model[0], LlmModel.model_id == only_model[1])
    elif not include_deprecated:
        stmt = stmt.where(LlmModel.deprecated_at.is_(None))
    stmt = stmt.order_by(LlmModel.provider, LlmModel.model_id)
    models = (await db.execute(stmt)).scalars().all()
    if not models:
        return []

    usage = await _usage_by_model(db, since)
    daily = await _daily_calls_by_model(db, SPARKLINE_DAYS)
    last_ever = await _last_call_ever(db)
    comparisons = await _comparison_presence(db)

    rows = [
        _build_stats_row(
            r, usage.get(r.model_id), daily.get(r.model_id, [0] * SPARKLINE_DAYS),
            last_ever.get(r.model_id), comparisons.get(r.model_id), now,
        )
        for r in models
    ]
    # 호출 많은 순 → 같은 호출수면 model_id
    rows.sort(key=lambda x: (-x.calls, x.model_id))
    return rows


@router.get("/stats", response_model=ModelStatsListOut)
async def model_stats(
    days: int = Query(30, ge=1, le=365),
    include_deprecated: bool = False,
    db: AsyncSession = Depends(get_db),
    _user: LlmopsUser = Depends(require_member),
) -> ModelStatsListOut:
    rows = await _stats_rows(db, days, include_deprecated)
    return ModelStatsListOut(days=days, generated_at=datetime.now(timezone.utc), models=rows)


# ---------------------------------------------------------------------------
# Anomalies (보고 계약 위반)
# ---------------------------------------------------------------------------

ANOMALY_HINTS = {
    "unregistered_model": "인벤토리에 없는 모델명을 보고 — consumer 의 model 필드 확인 (BATCH_RUN_REPORTING §2)",
    "missing_model": "stages[].model 누락 — 모델 축 집계에서 빠짐",
    "deprecated_model_called": "deprecated 모델을 여전히 호출 — consumer 설정에 replaced_by 반영 필요",
    "tokens_unreported": "tokens_in/out 미보고 — 토큰·비용 ROI 산출 불가",
    "ok_unreported": "ok 미보고 — 실패율 산출 불가",
    "stage_failed": "stage 실패 (ok=false)",
}


async def anomaly_rows(db: AsyncSession, days: int, model: str | None = None) -> list[AnomalyOut]:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    base = (
        select(
            BatchRunStage.model,
            BatchRun.consumer_id,
            func.count(BatchRunStage.id),
            func.max(BatchRun.started_at),
        )
        .join(BatchRun, BatchRunStage.batch_run_id == BatchRun.id)
        .where(BatchRun.started_at >= since)
        .group_by(BatchRunStage.model, BatchRun.consumer_id)
    )
    if model is not None:
        base = base.where(BatchRunStage.model == model)

    inventory = (await db.execute(select(LlmModel.model_id, LlmModel.deprecated_at))).all()
    known = {m for m, _ in inventory}
    deprecated = {m for m, d in inventory if d is not None}

    out: list[AnomalyOut] = []

    def add(kind: str, m: str | None, cid: str, n: int, last: datetime | None) -> None:
        if n:
            out.append(AnomalyOut(kind=kind, model=m, consumer_id=cid, count=n,
                                  last_seen_at=last, hint=ANOMALY_HINTS[kind]))

    for m, cid, n, last in (await db.execute(base)).all():
        if m is None:
            add("missing_model", None, cid, n, last)
        elif m not in known:
            add("unregistered_model", m, cid, n, last)
        elif m in deprecated:
            add("deprecated_model_called", m, cid, n, last)

    tokens_missing = BatchRunStage.tokens_in.is_(None) & BatchRunStage.tokens_out.is_(None)
    for m, cid, n, last in (await db.execute(base.where(tokens_missing))).all():
        add("tokens_unreported", m, cid, n, last)
    for m, cid, n, last in (await db.execute(base.where(BatchRunStage.ok.is_(None)))).all():
        add("ok_unreported", m, cid, n, last)
    for m, cid, n, last in (await db.execute(base.where(BatchRunStage.ok.is_(False)))).all():
        add("stage_failed", m, cid, n, last)

    out.sort(key=lambda a: (a.kind, -a.count))
    return out


@router.get("/anomalies", response_model=list[AnomalyOut])
async def model_anomalies(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    _user: LlmopsUser = Depends(require_member),
) -> list[AnomalyOut]:
    return await anomaly_rows(db, days)


# ---------------------------------------------------------------------------
# Detail
# ---------------------------------------------------------------------------

async def _breakdown(db: AsyncSession, model: str, since: datetime) -> list[BreakdownRowOut]:
    rows = (await db.execute(
        select(
            BatchRun.consumer_id,
            BatchRunStage.name,
            func.count(BatchRunStage.id),
            func.count(BatchRunStage.id).filter(BatchRunStage.ok.is_(False)),
            func.avg(BatchRunStage.duration_ms),
            _p95(BatchRunStage.duration_ms),
            func.sum(BatchRunStage.tokens_in),
            func.sum(BatchRunStage.tokens_out),
            func.count(BatchRunStage.id).filter(BatchRunStage.content_truncated.is_(True)),
            func.avg(BatchRunStage.quality_score),
            func.max(BatchRun.started_at),
        )
        .join(BatchRun, BatchRunStage.batch_run_id == BatchRun.id)
        .where(BatchRun.started_at >= since, BatchRunStage.model == model)
        .group_by(BatchRun.consumer_id, BatchRunStage.name)
        .order_by(func.count(BatchRunStage.id).desc())
    )).all()
    return [
        BreakdownRowOut(
            consumer_id=cid, stage_name=name, calls=calls, fails=fails,
            avg_ms=_int_or_none(round(avg) if avg is not None else None),
            p95_ms=_int_or_none(round(p95) if p95 is not None else None),
            tokens_in=_int_or_none(tin), tokens_out=_int_or_none(tout),
            truncated=trunc,
            avg_quality=round(float(q), 3) if q is not None else None,
            last_call_at=last,
        )
        for cid, name, calls, fails, avg, p95, tin, tout, trunc, q, last in rows
    ]


async def _series(db: AsyncSession, model: str, since: datetime) -> list[SeriesPointOut]:
    bucket = func.to_char(func.date_trunc("day", BatchRun.started_at), "YYYY-MM-DD").label("bucket")
    rows = (await db.execute(
        select(
            bucket,
            func.count(BatchRunStage.id),
            func.count(BatchRunStage.id).filter(BatchRunStage.ok.is_(False)),
            func.count(BatchRunStage.id).filter(BatchRunStage.content_truncated.is_(True)),
            _p50(BatchRunStage.duration_ms),
            _p95(BatchRunStage.duration_ms),
        )
        .join(BatchRun, BatchRunStage.batch_run_id == BatchRun.id)
        .where(BatchRun.started_at >= since, BatchRunStage.model == model)
        .group_by("bucket")
        .order_by("bucket")
    )).all()
    return [
        SeriesPointOut(
            bucket=b, calls=calls, fails=fails, truncated=trunc,
            p50_ms=_int_or_none(round(p50) if p50 is not None else None),
            p95_ms=_int_or_none(round(p95) if p95 is not None else None),
        )
        for b, calls, fails, trunc, p50, p95 in rows
    ]


async def _quality(db: AsyncSession, model: str, since: datetime) -> list[QualityRowOut]:
    rows = (await db.execute(
        select(
            BatchRunStage.quality_judge,
            func.count(BatchRunStage.id),
            func.avg(BatchRunStage.quality_score),
        )
        .join(BatchRun, BatchRunStage.batch_run_id == BatchRun.id)
        .where(
            BatchRun.started_at >= since,
            BatchRunStage.model == model,
            BatchRunStage.quality_score.is_not(None),
        )
        .group_by(BatchRunStage.quality_judge)
    )).all()
    return [
        QualityRowOut(judge=j or "unknown", n=n, avg=round(float(a), 3))
        for j, n, a in rows
    ]


async def _comparison_history(db: AsyncSession, model: str) -> list[ComparisonHistoryOut]:
    run_ids = select(ComparisonResult.comparison_run_id).where(
        ComparisonResult.model_id == model
    ).distinct()
    runs = (await db.execute(
        select(ComparisonRun).where(ComparisonRun.id.in_(run_ids))
        .order_by(ComparisonRun.started_at.desc())
    )).scalars().all()

    out: list[ComparisonHistoryOut] = []
    for run in runs:
        detail = build_detail(run)
        for rank, agg in enumerate(detail.aggregates, start=1):
            if agg.model_id == model:
                out.append(ComparisonHistoryOut(
                    id=run.id, case_name=run.case_name, prompt_set_id=run.prompt_set_id,
                    started_at=run.started_at, judge_model=run.judge_model,
                    model_count=len(detail.aggregates), rank=rank,
                    result_count=agg.result_count, avg_quality=agg.avg_quality,
                    win_rate=agg.win_rate, avg_duration_ms=agg.avg_duration_ms,
                ))
                break
    return out


async def _golden_counts(db: AsyncSession, model: str) -> GoldenSetCountOut:
    rows = (await db.execute(
        select(GoldenSetItem.status, func.count(GoldenSetItem.id))
        .where(GoldenSetItem.model == model)
        .group_by(GoldenSetItem.status)
    )).all()
    counts = {s: n for s, n in rows}
    return GoldenSetCountOut(
        candidate=counts.get("candidate", 0),
        approved=counts.get("approved", 0),
        rejected=counts.get("rejected", 0),
    )


@router.get("/detail", response_model=ModelDetailOut)
async def model_detail(
    provider: str = Query(..., min_length=1),
    model_id: str = Query(..., min_length=1),
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    _user: LlmopsUser = Depends(require_member),
) -> ModelDetailOut:
    rows = await _stats_rows(db, days, include_deprecated=True, only_model=(provider, model_id))
    if not rows:
        raise HTTPException(404, "model not found")
    stats = rows[0]

    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    live = await fetch_live()
    live_row = next((m for m in live.models if m.model_id == model_id), None)

    return ModelDetailOut(
        days=days,
        generated_at=now,
        model=stats,
        live=live_row,
        live_reachable=live.reachable,
        breakdown=await _breakdown(db, model_id, since),
        series=await _series(db, model_id, since),
        quality=await _quality(db, model_id, since),
        comparisons=await _comparison_history(db, model_id),
        golden_set=await _golden_counts(db, model_id),
        anomalies=await anomaly_rows(db, days, model=model_id),
    )
