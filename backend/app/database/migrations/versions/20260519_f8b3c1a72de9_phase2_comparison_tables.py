"""phase2_comparison_tables

Phase 2 (γ) 무료 vs 유료 비교 실험 모듈을 위한 신규 테이블.

표준: services/llmops/PHASE_2_DESIGN.md §4 (Claude-Opus-bluevlad)

Revision ID: f8b3c1a72de9
Revises: e7a2b89cf421
Create Date: 2026-05-19
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "f8b3c1a72de9"
down_revision: Union[str, None] = "e7a2b89cf421"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "comparison_runs",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("case_name", sa.Text(), nullable=False),
        sa.Column("prompt_set_id", sa.Text(), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("judge_model", sa.Text(), nullable=True),
        sa.Column("summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "comparison_results",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("comparison_run_id", sa.BigInteger(), nullable=False),
        sa.Column("prompt_id", sa.Text(), nullable=False),
        sa.Column("model_id", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("output_text", sa.Text(), nullable=True),
        sa.Column("tokens_in", sa.Integer(), nullable=True),
        sa.Column("tokens_out", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("cost_usd", sa.Numeric(10, 6), nullable=True),
        sa.Column("quality_score", sa.Numeric(4, 3), nullable=True),
        sa.Column(
            "quality_dimensions", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("quality_judge", sa.Text(), nullable=True),
        sa.Column("raw", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["comparison_run_id"], ["comparison_runs.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "comparison_run_id",
            "prompt_id",
            "model_id",
            name="uq_comparison_results_run_prompt_model",
        ),
    )
    op.create_index(
        "ix_comparison_results_run",
        "comparison_results",
        ["comparison_run_id"],
        unique=False,
    )
    op.create_index(
        "ix_comparison_results_model",
        "comparison_results",
        ["model_id", "provider"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_comparison_results_model", table_name="comparison_results")
    op.drop_index("ix_comparison_results_run", table_name="comparison_results")
    op.drop_table("comparison_results")
    op.drop_table("comparison_runs")
