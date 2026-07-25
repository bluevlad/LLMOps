"""golden_set_items — batch_run_stages content 샘플에서 승격된 골든셋 항목 (Phase C).

LLMOps 는 골든셋을 "생성"하지 않는다 — consumer 가 보고한 content 샘플 중
큐레이터가 승격(promote)·검수(approve/reject)한 항목을 축적·추이 관측한다.
파인튜닝 실행은 별도 consumer(model-tuner)가 export 를 가져가서 수행한다.
"""
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class GoldenSetItem(Base):
    __tablename__ = "golden_set_items"
    __table_args__ = (
        CheckConstraint(
            "status IN ('candidate','approved','rejected')",
            name="ck_golden_set_items_status",
        ),
        Index("ix_golden_set_items_consumer_status", "consumer_id", "status"),
        Index("ix_golden_set_items_source_stage", "source_stage_id", unique=True),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # 승격 출처 stage. stage 가 retention 으로 지워져도 골든셋은 보존 (SET NULL)
    source_stage_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("batch_run_stages.id", ondelete="SET NULL"),
        nullable=True,
    )
    consumer_id: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    response: Mapped[str] = mapped_column(Text, nullable=False)
    # 큐레이터가 다듬은 정답. NULL 이면 response 를 골든으로 채택.
    # response(초안)는 항상 보존 → (초안 ≻/= 골든) 선호쌍 확보
    gold_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="candidate")
    # 자유 라벨 (rejection_category, 도메인 태그 등)
    labels: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    curated_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
