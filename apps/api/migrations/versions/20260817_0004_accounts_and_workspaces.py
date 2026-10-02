"""Add database-native accounts, tenant workspaces, credentials, and backups."""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260817_0004"
down_revision = "20260718_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "accounts",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("username", sa.String(length=32), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("session_version", sa.Integer(), nullable=False),
        sa.Column("email_verified", sa.Boolean(), nullable=False),
        sa.Column("disabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
        sa.UniqueConstraint("username"),
    )
    op.create_index("ix_accounts_email", "accounts", ["email"], unique=True)
    op.create_index("ix_accounts_username", "accounts", ["username"], unique=True)

    op.create_table(
        "email_verifications",
        sa.Column("account_id", sa.String(length=32), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("account_id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(
        "ix_email_verifications_token_hash",
        "email_verifications",
        ["token_hash"],
        unique=True,
    )

    op.create_table(
        "user_credentials",
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("encrypted_value", sa.LargeBinary(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "name"),
        sa.UniqueConstraint("user_id", "name", name="uq_user_credentials_name"),
    )

    op.create_table(
        "documents",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("path", sa.String(length=1024), nullable=False),
        sa.Column("path_key", sa.String(length=1024), nullable=False),
        sa.Column("is_folder", sa.Boolean(), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=True),
        sa.Column("modified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("trash_id", sa.String(length=64), nullable=True),
        sa.Column("original_path", sa.String(length=1024), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "path_key", name="uq_documents_user_path"),
    )
    op.create_index("ix_documents_user_id", "documents", ["user_id"], unique=False)
    op.create_index("ix_documents_trash_id", "documents", ["trash_id"], unique=False)

    op.create_table(
        "backup_groups",
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("conversation_id", sa.String(length=64), nullable=True),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("user_id", "id"),
    )
    op.create_index(
        "ix_backup_groups_conversation_id",
        "backup_groups",
        ["conversation_id"],
        unique=False,
    )
    op.create_table(
        "backup_operations",
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("group_id", sa.String(length=64), nullable=False),
        sa.Column("operation_index", sa.Integer(), nullable=False),
        sa.Column("operation_type", sa.String(length=64), nullable=False),
        sa.Column("path", sa.String(length=1024), nullable=False),
        sa.Column("target_path", sa.String(length=1024), nullable=True),
        sa.Column("description", sa.String(length=1000), nullable=False),
        sa.Column("before_snapshot", sa.JSON(), nullable=False),
        sa.Column("after_snapshot", sa.JSON(), nullable=True),
        sa.Column("command_id", sa.String(length=96), nullable=True),
        sa.Column("command_state", sa.String(length=32), nullable=True),
        sa.Column("command_result", sa.JSON(), nullable=True),
        sa.Column("rolled_back_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id", "group_id"],
            ["backup_groups.user_id", "backup_groups.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", "group_id", "operation_index"),
    )
    op.create_index(
        "ix_backup_operations_command_id",
        "backup_operations",
        ["command_id"],
        unique=False,
    )

    for table_name in ("conversations", "tool_commands", "operation_audit", "agent_runs"):
        op.add_column(table_name, sa.Column("user_id", sa.String(length=32), nullable=True))
        op.create_index(f"ix_{table_name}_user_id", table_name, ["user_id"], unique=False)


def downgrade() -> None:
    for table_name in ("agent_runs", "operation_audit", "tool_commands", "conversations"):
        op.drop_index(f"ix_{table_name}_user_id", table_name=table_name)
        op.drop_column(table_name, "user_id")
    op.drop_index("ix_backup_operations_command_id", table_name="backup_operations")
    op.drop_table("backup_operations")
    op.drop_index("ix_backup_groups_conversation_id", table_name="backup_groups")
    op.drop_table("backup_groups")
    op.drop_index("ix_documents_trash_id", table_name="documents")
    op.drop_index("ix_documents_user_id", table_name="documents")
    op.drop_table("documents")
    op.drop_table("user_credentials")
    op.drop_index("ix_email_verifications_token_hash", table_name="email_verifications")
    op.drop_table("email_verifications")
    op.drop_index("ix_accounts_username", table_name="accounts")
    op.drop_index("ix_accounts_email", table_name="accounts")
    op.drop_table("accounts")
