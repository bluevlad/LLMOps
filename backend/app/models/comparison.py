"""comparison_runs + comparison_results — Phase 2 (γ) 무료 vs 유료 비교 실험 결과.

표준: services/llmops/PHASE_2_DESIGN.md §4 (Claude-Opus-bluevlad)

batch_runs 와 분리한 이유: production 워크로드 로깅과 R&D 비교 실험은 의미가 달라
같은 테이블에 섞으면 분석 신호가 오염됨 (PHASE_2_DESIGN.md §2).
"""
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


class ComparisonRun(Base):
    __tablename__ = "comparison_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    case_name: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_set_id: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    judge_model: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    results: Mapped[list["ComparisonResult"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class ComparisonResult(Base):
    __tablename__ = "comparison_results"
    __table_args__ = (
        UniqueConstraint(
            "comparison_run_id", "prompt_id", "model_id",
            name="uq_comparison_results_run_prompt_model",
        ),
        Index("ix_comparison_results_run", "comparison_run_id"),
        Index("ix_comparison_results_model", "model_id", "provider"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    comparison_run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("comparison_runs.id", ondelete="CASCADE"), nullable=False
    )
    prompt_id: Mapped[str] = mapped_column(Text, nullable=False)
    model_id: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    output_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    tokens_in: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_out: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)
    quality_score: Mapped[Decimal | None] = mapped_column(Numeric(4, 3), nullable=True)
    quality_dimensions: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    quality_judge: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    run: Mapped["ComparisonRun"] = relationship(back_populates="results")
