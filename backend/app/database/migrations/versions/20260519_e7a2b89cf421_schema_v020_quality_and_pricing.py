"""schema_v020_quality_and_pricing

표준 v0.2.0 반영:
- batch_run_stages: quality_score / quality_judge / quality_raw 추가
- llm_models: pricing_tier / cost_per_1m_tokens_in / cost_per_1m_tokens_out 추가
- llm_models: provider CHECK 확장 (claude-api/openai-api/gemini-api)

표준 문서:
- standards/observability/BATCH_RUN_REPORTING.md v0.2.0
- standards/ai/LLM_INVENTORY_SCHEMA.md v0.2.0
- services/llmops/PHASE_2_DESIGN.md

Revision ID: e7a2b89cf421
Revises: d701153c3c5c
Create Date: 2026-05-19
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "e7a2b89cf421"
down_revision: Union[str, None] = "d701153c3c5c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- batch_run_stages: quality 필드 (표준 v0.2.0 §2-α) ---
    op.add_column(
        "batch_run_stages",
        sa.Column("quality_score", sa.Numeric(4, 3), nullable=True),
    )
    op.add_column(
        "batch_run_stages",
        sa.Column("quality_judge", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "batch_run_stages",
        sa.Column("quality_raw", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_check_constraint(
        "ck_batch_run_stages_quality_judge",
        "batch_run_stages",
        "quality_judge IS NULL OR quality_judge IN "
        "('human','llm-judge','ground-truth','heuristic','user-feedback')",
    )

    # --- llm_models: pricing/cost 필드 + provider enum 확장 ---
    op.add_column(
        "llm_models",
        sa.Column(
            "pricing_tier",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'free-local'"),
        ),
    )
    op.add_column(
        "llm_models",
        sa.Column("cost_per_1m_tokens_in", sa.Numeric(10, 4), nullable=True),
    )
    op.add_column(
        "llm_models",
        sa.Column("cost_per_1m_tokens_out", sa.Numeric(10, 4), nullable=True),
    )
    op.create_check_constraint(
        "ck_llm_models_pricing_tier",
        "llm_models",
        "pricing_tier IN ('free-local','paid-api')",
    )

    # provider CHECK 재정의 — drop 후 재생성 (PG 는 alter CHECK 불가)
    op.drop_constraint("ck_llm_models_provider", "llm_models", type_="check")
    op.create_check_constraint(
        "ck_llm_models_provider",
        "llm_models",
        "provider IN ('ollama','mlx','gguf','claude-api','openai-api','gemini-api')",
    )


def downgrade() -> None:
    # provider CHECK 원복
    op.drop_constraint("ck_llm_models_provider", "llm_models", type_="check")
    op.create_check_constraint(
        "ck_llm_models_provider",
        "llm_models",
        "provider IN ('ollama','mlx','gguf')",
    )

    # llm_models 컬럼 제거
    op.drop_constraint("ck_llm_models_pricing_tier", "llm_models", type_="check")
    op.drop_column("llm_models", "cost_per_1m_tokens_out")
    op.drop_column("llm_models", "cost_per_1m_tokens_in")
    op.drop_column("llm_models", "pricing_tier")

    # batch_run_stages 컬럼 제거
    op.drop_constraint(
        "ck_batch_run_stages_quality_judge", "batch_run_stages", type_="check"
    )
    op.drop_column("batch_run_stages", "quality_raw")
    op.drop_column("batch_run_stages", "quality_judge")
    op.drop_column("batch_run_stages", "quality_score")
