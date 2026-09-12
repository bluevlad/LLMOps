"""monitor events + alerts (Layer 4)

v0.3.0 M3 — 인벤토리 변경 이력(llm_model_events) + 관제 알림·조치 기록(llm_alerts).
표준: LLM_INVENTORY_SCHEMA.md §3-5 (0.3.0)

Revision ID: d5f7a1b3c902
Revises: c4e8a2d6f931
Create Date: 2026-09-12
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "d5f7a1b3c902"
down_revision: Union[str, None] = "c4e8a2d6f931"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "llm_model_events",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("model_id", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("host", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("detail", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_llm_model_events_at", "llm_model_events", ["at"])
    op.create_index("ix_llm_model_events_model", "llm_model_events", ["provider", "model_id"])

    op.create_table(
        "llm_alerts",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column("model_id", sa.Text(), nullable=True),
        sa.Column("fingerprint", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("detail", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_by", sa.Text(), nullable=True),
        sa.Column("action_note", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_llm_alerts_open_fp", "llm_alerts", ["fingerprint"], unique=True,
        postgresql_where=sa.text("resolved_at IS NULL"),
    )
    op.create_index("ix_llm_alerts_first_seen", "llm_alerts", ["first_seen_at"])


def downgrade() -> None:
    op.drop_index("ix_llm_alerts_first_seen", table_name="llm_alerts")
    op.drop_index("ix_llm_alerts_open_fp", table_name="llm_alerts")
    op.drop_table("llm_alerts")
    op.drop_index("ix_llm_model_events_model", table_name="llm_model_events")
    op.drop_index("ix_llm_model_events_at", table_name="llm_model_events")
    op.drop_table("llm_model_events")
