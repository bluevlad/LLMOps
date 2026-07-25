"""golden_set_items

Phase C — batch_run_stages content 샘플 → 골든셋 승격/큐레이션 테이블.
LLMOps 는 승격·검수·추이 관측만 담당 (생성은 consumer, 파인튜닝은 model-tuner).

Revision ID: c4e8a2d6f931
Revises: b2d5f1a9c84e
Create Date: 2026-07-25
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "c4e8a2d6f931"
down_revision: Union[str, None] = "b2d5f1a9c84e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "golden_set_items",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "source_stage_id",
            sa.BigInteger(),
            sa.ForeignKey("batch_run_stages.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("consumer_id", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("response", sa.Text(), nullable=False),
        sa.Column("gold_response", sa.Text(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="candidate"),
        sa.Column("labels", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("curated_by", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "status IN ('candidate','approved','rejected')",
            name="ck_golden_set_items_status",
        ),
    )
    op.create_index(
        "ix_golden_set_items_consumer_status",
        "golden_set_items",
        ["consumer_id", "status"],
    )
    op.create_index(
        "ix_golden_set_items_source_stage",
        "golden_set_items",
        ["source_stage_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_golden_set_items_source_stage", table_name="golden_set_items")
    op.drop_index("ix_golden_set_items_consumer_status", table_name="golden_set_items")
    op.drop_table("golden_set_items")
