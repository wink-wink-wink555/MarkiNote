"""Create conversation, command idempotency, and operation audit tables."""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260718_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_conversations_updated_at", "conversations", ["updated_at"], unique=False)
    op.create_table(
        "messages",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("conversation_id", sa.String(length=64), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("conversation_id", "position", name="uq_message_position"),
    )
    op.create_index("ix_messages_conversation_id", "messages", ["conversation_id"], unique=False)
    op.create_table(
        "tool_commands",
        sa.Column("command_id", sa.String(length=96), nullable=False),
        sa.Column("run_id", sa.String(length=96), nullable=False),
        sa.Column("conversation_id", sa.String(length=64), nullable=True),
        sa.Column("tool_name", sa.String(length=100), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("command_id"),
    )
    op.create_index("ix_tool_commands_run_id", "tool_commands", ["run_id"], unique=False)
    op.create_index("ix_tool_commands_conversation_id", "tool_commands", ["conversation_id"], unique=False)
    op.create_table(
        "operation_audit",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("request_id", sa.String(length=128), nullable=False),
        sa.Column("conversation_id", sa.String(length=64), nullable=True),
        sa.Column("command_id", sa.String(length=96), nullable=True),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("target", sa.String(length=1024), nullable=True),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_operation_audit_request_id", "operation_audit", ["request_id"], unique=False)
    op.create_index("ix_operation_audit_conversation_id", "operation_audit", ["conversation_id"], unique=False)
    op.create_index("ix_operation_audit_command_id", "operation_audit", ["command_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_operation_audit_command_id", table_name="operation_audit")
    op.drop_index("ix_operation_audit_conversation_id", table_name="operation_audit")
    op.drop_index("ix_operation_audit_request_id", table_name="operation_audit")
    op.drop_table("operation_audit")
    op.drop_index("ix_tool_commands_conversation_id", table_name="tool_commands")
    op.drop_index("ix_tool_commands_run_id", table_name="tool_commands")
    op.drop_table("tool_commands")
    op.drop_index("ix_messages_conversation_id", table_name="messages")
    op.drop_table("messages")
    op.drop_index("ix_conversations_updated_at", table_name="conversations")
    op.drop_table("conversations")
