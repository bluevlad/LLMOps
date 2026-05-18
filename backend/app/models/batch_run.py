"""batch_runs + batch_run_stages — LLM 호출 실행 로그.

표준: standards/observability/BATCH_RUN_REPORTING.md (Claude-Opus-bluevlad)
계약: POST /api/batch-runs payload 와 1:1 매핑.
"""
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


class BatchRun(Base):
    __tablename__ = "batch_runs"
    __table_args__ = (
        UniqueConstraint("consumer_id", "run_id", name="uq_batch_runs_consumer_run"),
        CheckConstraint("status IN ('success','failure','partial')", name="ck_batch_runs_status"),
        Index("ix_batch_runs_consumer_started", "consumer_id", "started_at"),
        Index("ix_batch_runs_received", "received_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    consumer_id: Mapped[str] = mapped_column(Text, nullable=False)
    # service-registry.yaml 의 llm_consumers[].id 와 일치
    run_id: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    metrics: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    extra: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    stages: Mapped[list["BatchRunStage"]] = relationship(
        back_populates="batch_run",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class BatchRunStage(Base):
    __tablename__ = "batch_run_stages"
    __table_args__ = (
        Index("ix_batch_run_stages_model", "model"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    batch_run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("batch_runs.id", ondelete="CASCADE"), nullable=False
    )
    stage_order: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    model: Mapped[str | None] = mapped_column(Text, nullable=True)
    tokens_in: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_out: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    batch_run: Mapped["BatchRun"] = relationship(back_populates="stages")
