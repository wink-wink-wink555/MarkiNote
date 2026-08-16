"""Database-native AI mutation snapshots and rollback metadata."""
from __future__ import annotations

import base64
import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKeyConstraint, Integer, String, delete, func, select
from sqlalchemy.orm import Mapped, mapped_column

from markinote_api.modules.conversations.repository import Base, Database
from markinote_api.modules.documents.database_storage import DatabaseDocumentStorage
from markinote_api.platform.paths import PathValidationError, validate_storage_id


class DatabaseBackupGroupRecord(Base):
    __tablename__ = "backup_groups"

    user_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    conversation_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    state: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DatabaseBackupOperationRecord(Base):
    __tablename__ = "backup_operations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["user_id", "group_id"],
            ["backup_groups.user_id", "backup_groups.id"],
            ondelete="CASCADE",
        ),
    )

    user_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    group_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    operation_index: Mapped[int] = mapped_column(Integer, primary_key=True)
    operation_type: Mapped[str] = mapped_column(String(64), nullable=False)
    path: Mapped[str] = mapped_column(String(1024), nullable=False)
    target_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    description: Mapped[str] = mapped_column(String(1000), nullable=False)
    before_snapshot: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    after_snapshot: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    command_id: Mapped[str | None] = mapped_column(String(96), nullable=True, index=True)
    command_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    command_result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    rolled_back_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


def _encode_snapshot(snapshot: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "path": str(item["path"]),
            "is_folder": bool(item["is_folder"]),
            "content": base64.b64encode(item.get("content") or b"").decode("ascii")
            if not item["is_folder"]
            else None,
        }
        for item in snapshot
    ]


def _decode_snapshot(snapshot: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    return [
        {
            "path": str(item["path"]),
            "is_folder": bool(item["is_folder"]),
            "content": base64.b64decode(item.get("content") or "")
            if not item["is_folder"]
            else None,
        }
        for item in snapshot or []
    ]


def _fingerprint(snapshot: list[dict[str, Any]] | None) -> str:
    payload = json.dumps(snapshot or [], sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class DatabaseBackupManager:
    """Tenant-scoped backup manager whose snapshots and manifests stay in SQL."""

    def __init__(
        self,
        database: Database,
        user_id: str,
        documents: DatabaseDocumentStorage,
        max_count: int,
        max_bytes: int,
    ) -> None:
        self.database = database
        self.user_id = user_id
        self.documents = documents
        self.max_count = max(1, int(max_count))
        self.max_bytes = max(1, int(max_bytes))
        self.active_lease = timedelta(minutes=10)

    def _group(self, group_id: str) -> DatabaseBackupGroupRecord | None:
        try:
            validate_storage_id(group_id, "backup group id")
        except PathValidationError:
            raise
        with self.database.session() as session:
            return session.get(DatabaseBackupGroupRecord, (self.user_id, group_id))

    def create_operation_group(self, conversation_id: str | None = None) -> str:
        group_id = f"bg_{uuid.uuid4().hex}"
        now = datetime.now(UTC)
        with self.database.session() as session, session.begin():
            session.add(
                DatabaseBackupGroupRecord(
                    user_id=self.user_id,
                    id=group_id,
                    conversation_id=conversation_id,
                    state="active",
                    created_at=now,
                    completed_at=None,
                    lease_until=now + self.active_lease,
                )
            )
        return group_id

    def complete_operation_group(self, group_id: str) -> None:
        with self.database.session() as session, session.begin():
            record = session.get(DatabaseBackupGroupRecord, (self.user_id, group_id))
            if record is not None and record.state == "active":
                record.state = "completed"
                record.completed_at = datetime.now(UTC)
                record.lease_until = None

    def heartbeat_operation_group(self, group_id: str) -> None:
        with self.database.session() as session, session.begin():
            record = session.get(DatabaseBackupGroupRecord, (self.user_id, group_id))
            if record is not None and record.state == "active":
                record.lease_until = datetime.now(UTC) + self.active_lease

    def backup_before_modify(
        self,
        group_id: str,
        operation_type: str,
        rel_path: str,
        description: str,
        *,
        target_path: str | None = None,
    ) -> int:
        before = _encode_snapshot(self.documents.snapshot(rel_path))
        projected = len(json.dumps(before, separators=(",", ":")).encode("utf-8"))
        if projected > self.max_bytes:
            raise ValueError("recovery snapshot exceeds the configured backup quota")
        with self.database.session() as session, session.begin():
            group = session.get(DatabaseBackupGroupRecord, (self.user_id, group_id))
            if group is None or group.state != "active":
                raise ValueError("backup group is not active")
            current = session.scalar(
                select(func.max(DatabaseBackupOperationRecord.operation_index)).where(
                    DatabaseBackupOperationRecord.user_id == self.user_id,
                    DatabaseBackupOperationRecord.group_id == group_id,
                )
            )
            operation_index = int(current if current is not None else -1) + 1
            session.add(
                DatabaseBackupOperationRecord(
                    user_id=self.user_id,
                    group_id=group_id,
                    operation_index=operation_index,
                    operation_type=operation_type,
                    path=rel_path,
                    target_path=target_path,
                    description=description[:1000],
                    before_snapshot=before,
                    after_snapshot=None,
                    command_id=None,
                    command_state=None,
                    command_result=None,
                    rolled_back_at=None,
                )
            )
        return operation_index

    def backup_after_modify(self, group_id: str, operation_index: int, rel_path: str) -> None:
        after = _encode_snapshot(self.documents.snapshot(rel_path))
        with self.database.session() as session, session.begin():
            operation = session.get(
                DatabaseBackupOperationRecord,
                (self.user_id, group_id, operation_index),
            )
            if operation is None:
                raise ValueError("backup operation does not exist")
            operation.after_snapshot = after

    def prepare_command(self, group_id: str, operation_index: int, command_id: str) -> None:
        self._command_state(group_id, operation_index, command_id, "prepared")

    def mark_command_applied(self, group_id: str, operation_index: int, command_id: str) -> None:
        self._command_state(group_id, operation_index, command_id, "applied")

    def mark_command_committed(self, group_id: str, operation_index: int, command_id: str) -> None:
        self._command_state(group_id, operation_index, command_id, "committed")

    def _command_state(self, group_id: str, operation_index: int, command_id: str, state: str) -> None:
        with self.database.session() as session, session.begin():
            operation = session.get(
                DatabaseBackupOperationRecord,
                (self.user_id, group_id, operation_index),
            )
            if operation is None:
                raise ValueError("backup operation does not exist")
            if operation.command_id not in {None, command_id}:
                raise ValueError("backup operation belongs to another command")
            operation.command_id = command_id
            operation.command_state = state

    def record_command_result(
        self,
        group_id: str,
        operation_index: int,
        command_id: str,
        result: str,
        backup_info: dict[str, Any],
    ) -> None:
        with self.database.session() as session, session.begin():
            operation = session.get(
                DatabaseBackupOperationRecord,
                (self.user_id, group_id, operation_index),
            )
            if operation is None or operation.command_id != command_id:
                raise ValueError("backup operation command mismatch")
            operation.command_result = {"result": result, "backup_info": backup_info}

    def find_command(self, command_id: str) -> dict[str, Any] | None:
        with self.database.session() as session:
            operation = session.scalar(
                select(DatabaseBackupOperationRecord).where(
                    DatabaseBackupOperationRecord.user_id == self.user_id,
                    DatabaseBackupOperationRecord.command_id == command_id,
                )
            )
        if operation is None:
            return None
        return {
            "backup_group_id": operation.group_id,
            "operation_index": operation.operation_index,
            "state": operation.command_state,
            **(operation.command_result or {}),
        }

    def _restore(self, operation: DatabaseBackupOperationRecord) -> None:
        if operation.operation_type == "move_item" and operation.target_path:
            self.documents.replace_snapshot(operation.target_path, [])
        self.documents.replace_snapshot(operation.path, _decode_snapshot(operation.before_snapshot))

    def compensate_active_operation(
        self,
        group_id: str,
        operation_index: int,
        *,
        observed_path: str = "",
        require_after_match: bool = False,
    ) -> tuple[bool, str]:
        with self.database.session() as session:
            operation = session.get(
                DatabaseBackupOperationRecord,
                (self.user_id, group_id, operation_index),
            )
            if operation is None:
                return False, "Backup operation not found"
            if require_after_match and operation.after_snapshot is not None:
                live = _encode_snapshot(self.documents.snapshot(observed_path or operation.path))
                if _fingerprint(live) != _fingerprint(operation.after_snapshot):
                    return False, "Rollback refused because the live document changed"
            self._restore(operation)
        with self.database.session() as session, session.begin():
            record = session.get(
                DatabaseBackupOperationRecord,
                (self.user_id, group_id, operation_index),
            )
            if record is not None:
                record.rolled_back_at = datetime.now(UTC)
                record.command_state = "compensated"
        return True, "Operation rolled back"

    def rollback_operation(self, group_id: str, operation_index: int | None = None) -> tuple[bool, str]:
        if operation_index is None:
            with self.database.session() as session:
                indexes = list(
                    session.scalars(
                        select(DatabaseBackupOperationRecord.operation_index)
                        .where(
                            DatabaseBackupOperationRecord.user_id == self.user_id,
                            DatabaseBackupOperationRecord.group_id == group_id,
                        )
                        .order_by(DatabaseBackupOperationRecord.operation_index.desc())
                    )
                )
            for index in indexes:
                ok, message = self.compensate_active_operation(group_id, index, require_after_match=True)
                if not ok:
                    return ok, message
            return True, "Backup group rolled back"
        return self.compensate_active_operation(group_id, operation_index, require_after_match=True)

    def get_group_manifest(self, group_id: str) -> dict[str, Any] | None:
        with self.database.session() as session:
            group = session.get(DatabaseBackupGroupRecord, (self.user_id, group_id))
            if group is None:
                return None
            operations = session.scalars(
                select(DatabaseBackupOperationRecord)
                .where(
                    DatabaseBackupOperationRecord.user_id == self.user_id,
                    DatabaseBackupOperationRecord.group_id == group_id,
                )
                .order_by(DatabaseBackupOperationRecord.operation_index)
            ).all()
        return {
            "id": group.id,
            "timestamp": group.created_at.isoformat(),
            "conversation_id": group.conversation_id,
            "state": group.state,
            "completed_at": group.completed_at.isoformat() if group.completed_at else None,
            "operations": [
                {
                    "index": item.operation_index,
                    "type": item.operation_type,
                    "path": item.path,
                    "target": item.target_path,
                    "description": item.description,
                    "command_id": item.command_id,
                    "command_state": item.command_state,
                    "rolled_back_at": item.rolled_back_at.isoformat() if item.rolled_back_at else None,
                }
                for item in operations
            ],
        }

    def list_backups(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.database.session() as session:
            ids = list(
                session.scalars(
                    select(DatabaseBackupGroupRecord.id)
                    .where(DatabaseBackupGroupRecord.user_id == self.user_id)
                    .order_by(DatabaseBackupGroupRecord.created_at.desc())
                    .limit(limit)
                )
            )
        return [manifest for group_id in ids if (manifest := self.get_group_manifest(group_id))]

    def delete_conversation_backups(self, conversation_id: str) -> int:
        with self.database.session() as session, session.begin():
            result = session.execute(
                delete(DatabaseBackupGroupRecord).where(
                    DatabaseBackupGroupRecord.user_id == self.user_id,
                    DatabaseBackupGroupRecord.conversation_id == conversation_id,
                    DatabaseBackupGroupRecord.state != "active",
                )
            )
        return max(0, int(getattr(result, "rowcount", 0) or 0))

    def cleanup(self, max_count: int | None = None, max_bytes: int | None = None) -> None:
        keep = max(1, int(max_count or self.max_count))
        with self.database.session() as session:
            expired = list(
                session.scalars(
                    select(DatabaseBackupGroupRecord.id)
                    .where(
                        DatabaseBackupGroupRecord.user_id == self.user_id,
                        DatabaseBackupGroupRecord.state != "active",
                    )
                    .order_by(DatabaseBackupGroupRecord.created_at.desc())
                    .offset(keep)
                )
            )
        if expired:
            with self.database.session() as session, session.begin():
                session.execute(
                    delete(DatabaseBackupGroupRecord).where(
                        DatabaseBackupGroupRecord.user_id == self.user_id,
                        DatabaseBackupGroupRecord.id.in_(expired),
                    )
                )
