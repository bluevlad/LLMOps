"""실제 모델 조치·취소의 추가 전용 기록. 호스트 작업을 실행하지 않는다."""
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, HttpUrl, StringConstraints, model_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.security import require_admin, require_member_or_s2s
from app.database.session import get_db
from app.models.monitor import LlmAlert, LlmAlertAction
from app.models.user import LlmopsUser

router = APIRouter(prefix="/monitor", tags=["monitor"])
Note = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
ActionType = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]


class ActionIn(BaseModel):
    request_id: UUID
    action_type: ActionType
    note: Note
    discovery_source: Literal["alert", "dashboard", "manual"]
    evidence_url: HttpUrl | None = None
    outcome: Literal["pending", "improved", "no_change"]
    result_note: Note | None = None

    @model_validator(mode="after")
    def require_result(self):
        if self.outcome != "pending" and self.result_note is None:
            raise ValueError("검증된 결과에는 result_note가 필요합니다")
        return self


class CancelIn(BaseModel):
    request_id: UUID
    note: Note


class ActionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    alert_id: int
    request_id: UUID
    event_type: str
    target_action_id: int | None
    action_type: str
    note: str
    discovery_source: str
    evidence_url: str | None
    outcome: str
    result_note: str | None
    actor: str
    at: datetime


async def lock_alert(db: AsyncSession, alert_id: int):
    alert = (await db.execute(select(LlmAlert).where(LlmAlert.id == alert_id).with_for_update())).scalar_one_or_none()
    if alert is None:
        raise HTTPException(404, "alert not found")


async def existing_request(db: AsyncSession, alert_id: int, request_id: UUID):
    return (await db.execute(select(LlmAlertAction).where(
        LlmAlertAction.alert_id == alert_id, LlmAlertAction.request_id == request_id,
    ))).scalar_one_or_none()


@router.get("/alerts/{alert_id}/actions", response_model=list[ActionOut])
async def list_actions(
    alert_id: int, before_id: int | None = Query(None, ge=1),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db), _user: LlmopsUser = Depends(require_member_or_s2s),
):
    if await db.get(LlmAlert, alert_id) is None:
        raise HTTPException(404, "alert not found")
    stmt = select(LlmAlertAction).where(LlmAlertAction.alert_id == alert_id)
    if before_id is not None:
        stmt = stmt.where(LlmAlertAction.id < before_id)
    return (await db.execute(stmt.order_by(LlmAlertAction.id.desc()).limit(limit))).scalars().all()


@router.post("/alerts/{alert_id}/actions", response_model=ActionOut)
async def record_action(
    alert_id: int, body: ActionIn, db: AsyncSession = Depends(get_db),
    user: LlmopsUser = Depends(require_admin),
):
    await lock_alert(db, alert_id)
    values = body.model_dump()
    values["evidence_url"] = str(body.evidence_url) if body.evidence_url else None
    existing = await existing_request(db, alert_id, body.request_id)
    if existing is not None:
        if existing.event_type != "action" or existing.actor != user.email or any(
            getattr(existing, key) != value for key, value in values.items()
        ):
            raise HTTPException(409, "request_id already used with different content")
        return existing
    row = LlmAlertAction(alert_id=alert_id, event_type="action", actor=user.email, **values)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


@router.post("/alerts/{alert_id}/actions/{action_id}/cancel", response_model=ActionOut)
async def cancel_action(
    alert_id: int, action_id: int, body: CancelIn, db: AsyncSession = Depends(get_db),
    user: LlmopsUser = Depends(require_admin),
):
    await lock_alert(db, alert_id)
    existing = await existing_request(db, alert_id, body.request_id)
    if existing is not None:
        if (existing.event_type, existing.target_action_id, existing.note, existing.actor) != (
            "cancel", action_id, body.note, user.email,
        ):
            raise HTTPException(409, "request_id already used with different content")
        return existing
    target = await db.get(LlmAlertAction, action_id)
    if target is None or target.alert_id != alert_id or target.event_type != "action":
        raise HTTPException(404, "action not found")
    cancelled = (await db.execute(select(LlmAlertAction.id).where(
        LlmAlertAction.target_action_id == action_id,
    ))).scalar_one_or_none()
    if cancelled is not None:
        raise HTTPException(409, "action already cancelled")
    row = LlmAlertAction(
        alert_id=alert_id, request_id=body.request_id, event_type="cancel", target_action_id=action_id,
        action_type=target.action_type, note=body.note, discovery_source=target.discovery_source,
        evidence_url=target.evidence_url, outcome=target.outcome, result_note=target.result_note,
        actor=user.email,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


@router.get("/actions/summary")
async def action_summary(
    db: AsyncSession = Depends(get_db), _user: LlmopsUser = Depends(require_member_or_s2s),
) -> dict[str, int]:
    cancellation = aliased(LlmAlertAction)
    active = ~select(cancellation.id).where(cancellation.target_action_id == LlmAlertAction.id).exists()
    verified = LlmAlertAction.outcome == "improved"
    row = (await db.execute(select(
        func.count(LlmAlertAction.id),
        func.count(LlmAlertAction.id).filter(verified),
        func.count(LlmAlertAction.id).filter(verified, LlmAlertAction.discovery_source.in_(["alert", "dashboard"])),
    ).where(LlmAlertAction.event_type == "action", active))).one()
    return dict(zip(("action_count", "verified_action_count", "llmops_first_verified_count"), row))
