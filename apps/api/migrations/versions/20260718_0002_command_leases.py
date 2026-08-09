"""Add recoverable leases to tool command claims.

Revision ID: 20260718_0002
Revises: 20260718_0001
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260718_0002"
down_revision = "20260718_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tool_commands",
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "tool_commands",
        sa.Column("attempt", sa.Integer(), server_default=sa.text("1"), nullable=False),
    )
    # A command left running by the pre-lease release is immediately eligible
    # for takeover. Terminal rows deliberately keep a null lease.
    op.execute(
        sa.text(
            "UPDATE tool_commands SET lease_until = created_at "
            "WHERE state = 'running' AND lease_until IS NULL"
        )
    )
    op.create_index(
        "ix_tool_commands_lease_until",
        "tool_commands",
        ["lease_until"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_tool_commands_lease_until", table_name="tool_commands")
    op.drop_column("tool_commands", "attempt")
    op.drop_column("tool_commands", "lease_until")
