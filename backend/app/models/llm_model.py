"""llm_models — 설치된 로컬 LLM 인벤토리.

표준: standards/ai/LLM_INVENTORY_SCHEMA.md (Claude-Opus-bluevlad)
3계층 데이터: Layer 1 (자동 수집) + Layer 2 (수동 보강) + Layer 3 (파생 집계, 별도)
"""
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    ARRAY,
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    Index,
    Numeric,
    PrimaryKeyConstraint,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class LlmModel(Base):
    __tablename__ = "llm_models"
    __table_args__ = (
        PrimaryKeyConstraint("model_id", "provider", "host", name="pk_llm_models"),
        CheckConstraint(
            "provider IN ('ollama','mlx','gguf','claude-api','openai-api','gemini-api')",
            name="ck_llm_models_provider",
        ),
        CheckConstraint(
            "pricing_tier IN ('free-local','paid-api')",
            name="ck_llm_models_pricing_tier",
        ),
        Index("ix_llm_models_active", "provider", postgresql_where=text("deprecated_at IS NULL")),
        Index("ix_llm_models_family", "family"),
    )

    # Identity (PK)
    model_id: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    host: Mapped[str] = mapped_column(Text, nullable=False, default="macbook-mac1")

    # Layer 1: auto-collected
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    digest: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    family: Mapped[str | None] = mapped_column(Text, nullable=True)
    parameter_size: Mapped[str | None] = mapped_column(Text, nullable=True)
    quantization: Mapped[str | None] = mapped_column(Text, nullable=True)
    format: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Layer 2: manually augmented (currently via service-registry inference + future UI)
    role_tags: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    owner: Mapped[str | None] = mapped_column(Text, nullable=True)
    adopted_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    deprecated_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    replaced_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Cost / pricing (표준 v0.2.0 — paid-api 비교 분석용)
    pricing_tier: Mapped[str] = mapped_column(Text, nullable=False, default="free-local")
    cost_per_1m_tokens_in: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    cost_per_1m_tokens_out: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)

    # Bookkeeping
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    raw: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
