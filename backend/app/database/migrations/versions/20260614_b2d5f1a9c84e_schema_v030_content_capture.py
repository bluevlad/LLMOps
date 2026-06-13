"""schema_v030_content_capture

표준 v0.3.0 반영 (BATCH_RUN_REPORTING §2-β — 샘플링/제한 content 저장):
- batch_run_stages: LLM 호출 "내용·결과" 레이어 추가
  prompt / response / params / ok / retries / stage_error
  prompt_chars / response_chars / content_truncated / content_sampled

목적: 분석 agent 가 LLM 을 "어떤 내용으로 호출했고 무슨 결과가 나왔는지" 를
확인해 효율(토큰 낭비·재시도·파싱 실패·품질 대비 비용)을 관리.
본문은 consumer 가 샘플링(실패/저품질/1-in-N)해서 truncate 후 보고한다.

표준 문서:
- standards/observability/BATCH_RUN_REPORTING.md v0.3.0

Revision ID: b2d5f1a9c84e
Revises: f8b3c1a72de9
Create Date: 2026-06-14
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "b2d5f1a9c84e"
down_revision: Union[str, None] = "f8b3c1a72de9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_CONTENT_COLUMNS = (
    ("prompt", sa.Text()),
    ("response", sa.Text()),
    ("params", postgresql.JSONB(astext_type=sa.Text())),
    ("ok", sa.Boolean()),
    ("retries", sa.Integer()),
    ("stage_error", sa.Text()),
    ("prompt_chars", sa.Integer()),
    ("response_chars", sa.Integer()),
    ("content_truncated", sa.Boolean()),
    ("content_sampled", sa.Boolean()),
)


def upgrade() -> None:
    for name, col_type in _CONTENT_COLUMNS:
        op.add_column("batch_run_stages", sa.Column(name, col_type, nullable=True))


def downgrade() -> None:
    for name, _ in reversed(_CONTENT_COLUMNS):
        op.drop_column("batch_run_stages", name)
