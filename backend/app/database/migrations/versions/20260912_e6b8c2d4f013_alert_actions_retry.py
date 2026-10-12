"""Separate action history from acknowledgment; persist notification attempts.

Revision ID: e6b8c2d4f013
Revises: d5f7a1b3c902
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "e6b8c2d4f013"
down_revision = "d5f7a1b3c902"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("llm_alerts", sa.Column("notification_attempts", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("llm_alerts", sa.Column("last_notification_attempt_at", sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        "llm_alert_actions",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("alert_id", sa.BigInteger(), sa.ForeignKey("llm_alerts.id"), nullable=False),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("target_action_id", sa.BigInteger(), sa.ForeignKey("llm_alert_actions.id"), nullable=True),
        sa.Column("action_type", sa.Text(), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("discovery_source", sa.Text(), nullable=False),
        sa.Column("evidence_url", sa.Text(), nullable=True),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("result_note", sa.Text(), nullable=True),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("alert_id", "request_id", name="uq_llm_alert_actions_request"),
        sa.UniqueConstraint("target_action_id", name="uq_llm_alert_actions_cancel"),
        sa.CheckConstraint("event_type IN ('action','cancel')", name="ck_llm_alert_actions_event"),
        sa.CheckConstraint("(event_type = 'action' AND target_action_id IS NULL) OR (event_type = 'cancel' AND target_action_id IS NOT NULL)", name="ck_llm_alert_actions_target"),
        sa.CheckConstraint("discovery_source IN ('alert','dashboard','manual')", name="ck_llm_alert_actions_source"),
        sa.CheckConstraint("outcome IN ('pending','improved','no_change')", name="ck_llm_alert_actions_outcome"),
        sa.CheckConstraint("length(trim(note)) > 0", name="ck_llm_alert_actions_note"),
    )
    op.create_index("ix_llm_alert_actions_alert_at", "llm_alert_actions", ["alert_id", "at"])
    # Existing acknowledgments remain untouched; they are not evidence of an action.


def downgrade():
    op.drop_index("ix_llm_alert_actions_alert_at", table_name="llm_alert_actions")
    op.drop_table("llm_alert_actions")
    op.drop_column("llm_alerts", "last_notification_attempt_at")
    op.drop_column("llm_alerts", "notification_attempts")
