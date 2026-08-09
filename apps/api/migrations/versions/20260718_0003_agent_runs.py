"""Add metadata-only AI agent run lifecycle audit.

Revision ID: 20260718_0003
Revises: 20260718_0002
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260718_0003"
down_revision = "20260718_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_runs",
        sa.Column("run_id", sa.String(length=96), nullable=False),
        sa.Column("request_id", sa.String(length=128), nullable=False),
        sa.Column("conversation_id", sa.String(length=64), nullable=True),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("conversation_attached_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_content_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.CheckConstraint(
            "state IN ('running', 'completed', 'failed', 'cancelled')",
            name="ck_agent_runs_state",
        ),
        sa.PrimaryKeyConstraint("run_id", "request_id", name="pk_agent_runs"),
    )
    op.create_index(
        "ix_agent_runs_conversation_id",
        "agent_runs",
        ["conversation_id"],
        unique=False,
    )
    op.create_index("ix_agent_runs_provider", "agent_runs", ["provider"], unique=False)
    op.create_index(
        "ix_agent_runs_state_finished_at",
        "agent_runs",
        ["state", "finished_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_agent_runs_state_finished_at", table_name="agent_runs")
    op.drop_index("ix_agent_runs_provider", table_name="agent_runs")
    op.drop_index("ix_agent_runs_conversation_id", table_name="agent_runs")
    op.drop_table("agent_runs")
