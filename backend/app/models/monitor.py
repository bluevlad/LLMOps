"""Layer 4 — 관제 이벤트·알림 (표준 LLM_INVENTORY_SCHEMA §3-5, v0.3.0).

llm_model_events : 인벤토리 변경 이력 (폴러 diff 가 생성)
llm_alerts       : 관제 신호 (평가 잡이 fingerprint 로 dedup, 소멸 시 자동 해결) + 확인 기록. 실제 조치 KPI는 llm_alert_actions.
"""
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, Integer, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from uuid import UUID as UUIDType
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base

EVENT_KINDS = ("discovered", "removed", "reappeared", "digest_changed", "size_changed")
ALERT_KINDS = (
    "ollama_unreachable",
    "expected_resident_missing",
    "retire_candidate",
    "failure_spike",
    "contract_anomaly",
)
SEVERITIES = ("critical", "warning", "info")


class LlmModelEvent(Base):
    __tablename__ = "llm_model_events"
    __table_args__ = (
        Index("ix_llm_model_events_at", "at"),
        Index("ix_llm_model_events_model", "provider", "model_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    model_id: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    host: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class LlmAlert(Base):
    __tablename__ = "llm_alerts"
    __table_args__ = (
        Index("ix_llm_alerts_open_fp", "fingerprint", unique=True,
              postgresql_where=text("resolved_at IS NULL")),
        Index("ix_llm_alerts_first_seen", "first_seen_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(Text, nullable=False)
    model_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notification_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_notification_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledged_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    action_note: Mapped[str | None] = mapped_column(Text, nullable=True)


class LlmAlertAction(Base):
    """실제 작업은 외부에서 수행한다. 조치·취소를 추가해 원문을 보존한다."""
    __tablename__ = "llm_alert_actions"
    __table_args__ = (
        UniqueConstraint("alert_id", "request_id", name="uq_llm_alert_actions_request"),
        UniqueConstraint("target_action_id", name="uq_llm_alert_actions_cancel"),
        CheckConstraint("event_type IN ('action','cancel')", name="ck_llm_alert_actions_event"),
        CheckConstraint("(event_type = 'action' AND target_action_id IS NULL) OR "
                        "(event_type = 'cancel' AND target_action_id IS NOT NULL)", name="ck_llm_alert_actions_target"),
        CheckConstraint("discovery_source IN ('alert','dashboard','manual')", name="ck_llm_alert_actions_source"),
        CheckConstraint("outcome IN ('pending','improved','no_change')", name="ck_llm_alert_actions_outcome"),
        CheckConstraint("length(trim(note)) > 0", name="ck_llm_alert_actions_note"),
        Index("ix_llm_alert_actions_alert_at", "alert_id", "at"),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    alert_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("llm_alerts.id"), nullable=False)
    request_id: Mapped[UUIDType] = mapped_column(UUID(as_uuid=True), nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    target_action_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("llm_alert_actions.id"), nullable=True)
    action_type: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False)
    discovery_source: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    outcome: Mapped[str] = mapped_column(Text, nullable=False)
    result_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor: Mapped[str] = mapped_column(Text, nullable=False)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
