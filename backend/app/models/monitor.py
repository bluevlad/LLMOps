"""Layer 4 — 관제 이벤트·알림 (표준 LLM_INVENTORY_SCHEMA §3-5, v0.3.0).

llm_model_events : 인벤토리 변경 이력 (폴러 diff 가 생성)
llm_alerts       : 관제 신호 (평가 잡이 fingerprint 로 dedup, 소멸 시 자동 해결) + 조치 기록 (Sunset KPI 원천)
"""
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Index, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
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
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledged_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    action_note: Mapped[str | None] = mapped_column(Text, nullable=True)
