"""관제 API (v0.3.0 M3) — 알림 목록·확인(조치 기록), 인벤토리 변경 이력, 디스크 사용량.

/api/monitor/alerts        : 열린/해결된 알림 (kind·severity 필터)
/api/monitor/alerts/{id}/ack : 조치 기록 — Sunset KPI(관제 조치 수) 의 원천
/api/monitor/alerts/evaluate : 즉시 재평가 (admin)
/api/monitor/events        : 인벤토리 변경 이력 (discovered/removed/reappeared/digest_changed/size_changed)
/api/monitor/disk          : 모델 파일 디스크 사용량 + 회수 가능(deprecated 인데 설치됨)

조작(모델 삭제·pull)은 제공하지 않는다 — 관측 plane 원칙.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import require_admin, require_member_or_s2s
from app.database.session import get_db
from app.models.monitor import LlmAlert, LlmModelEvent
from app.models.user import LlmopsUser
from app.monitor import alerts as alert_job
from app.monitor.disk import DiskOut, disk_usage

router = APIRouter(prefix="/monitor", tags=["monitor"])

SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2}


class AlertOut(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    id: int
    kind: str
    severity: str
    model_id: str | None
    fingerprint: str
    title: str
    message: str
    detail: dict[str, Any] | None
    first_seen_at: datetime
    last_seen_at: datetime
    resolved_at: datetime | None
    notified_at: datetime | None
    acknowledged_at: datetime | None
    acknowledged_by: str | None
    action_note: str | None


class AlertListOut(BaseModel):
    open_count: int
    unacknowledged_count: int
    by_severity: dict[str, int]
    last_evaluated_at: datetime | None
    last_result: dict[str, Any] | None
    alerts: list[AlertOut]


class AckIn(BaseModel):
    action_note: str | None = None
    undo: bool = False


class EventOut(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    id: int
    model_id: str
    provider: str
    host: str
    kind: str
    detail: dict[str, Any] | None
    at: datetime


@router.get("/alerts", response_model=AlertListOut)
async def list_alerts(
    status: str = Query("open", pattern="^(open|resolved|all)$"),
    kind: str | None = None,
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    _user: LlmopsUser = Depends(require_member_or_s2s),
) -> AlertListOut:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    stmt = select(LlmAlert).where(LlmAlert.last_seen_at >= since)
    if status == "open":
        stmt = stmt.where(LlmAlert.resolved_at.is_(None))
    elif status == "resolved":
        stmt = stmt.where(LlmAlert.resolved_at.isnot(None))
    if kind:
        stmt = stmt.where(LlmAlert.kind == kind)
    rows = (await db.execute(stmt.order_by(LlmAlert.last_seen_at.desc()).limit(limit))).scalars().all()

    open_rows = (await db.execute(
        select(LlmAlert).where(LlmAlert.resolved_at.is_(None))
    )).scalars().all()
    by_sev: dict[str, int] = {}
    for a in open_rows:
        by_sev[a.severity] = by_sev.get(a.severity, 0) + 1

    ordered = sorted(rows, key=lambda a: (SEVERITY_ORDER.get(a.severity, 9), -a.last_seen_at.timestamp()))
    evaluated_at, last_result = alert_job.last_evaluation()
    return AlertListOut(
        open_count=len(open_rows),
        unacknowledged_count=sum(1 for a in open_rows if a.acknowledged_at is None),
        by_severity=by_sev,
        last_evaluated_at=evaluated_at,
        last_result=last_result,
        alerts=[AlertOut.model_validate(a, from_attributes=True) for a in ordered],
    )


@router.post("/alerts/{alert_id}/ack", response_model=AlertOut)
async def acknowledge_alert(
    alert_id: int,
    body: AckIn,
    db: AsyncSession = Depends(get_db),
    user: LlmopsUser = Depends(require_admin),
) -> AlertOut:
    """조치 기록. Sunset KPI 가 세는 '관제 신호로 내려진 모델 조치' 가 여기 쌓인다."""
    alert = (await db.execute(select(LlmAlert).where(LlmAlert.id == alert_id))).scalar_one_or_none()
    if alert is None:
        raise HTTPException(404, "alert not found")
    if body.undo:
        alert.acknowledged_at = None
        alert.acknowledged_by = None
        alert.action_note = None
    else:
        alert.acknowledged_at = datetime.now(timezone.utc)
        alert.acknowledged_by = user.email
        alert.action_note = body.action_note
    await db.commit()
    await db.refresh(alert)
    return AlertOut.model_validate(alert, from_attributes=True)


@router.post("/alerts/evaluate")
async def evaluate_alerts(
    db: AsyncSession = Depends(get_db),
    _user: LlmopsUser = Depends(require_admin),
) -> dict[str, Any]:
    return await alert_job.evaluate_and_store(db)


@router.get("/events", response_model=list[EventOut])
async def list_events(
    days: int = Query(90, ge=1, le=730),
    kind: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    _user: LlmopsUser = Depends(require_member_or_s2s),
) -> list[EventOut]:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    stmt = select(LlmModelEvent).where(LlmModelEvent.at >= since)
    if kind:
        stmt = stmt.where(LlmModelEvent.kind == kind)
    rows = (await db.execute(stmt.order_by(LlmModelEvent.at.desc()).limit(limit))).scalars().all()
    return [EventOut.model_validate(r, from_attributes=True) for r in rows]


@router.get("/disk", response_model=DiskOut)
async def model_disk_usage(
    top: int = Query(10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _user: LlmopsUser = Depends(require_member_or_s2s),
) -> DiskOut:
    return await disk_usage(db, top=top)
