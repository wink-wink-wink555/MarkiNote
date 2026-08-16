"""Conversation repository ports and JSON/PostgreSQL-compatible adapters."""
from __future__ import annotations

import copy
import json
import os
from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    delete,
    event,
    func,
    inspect,
    select,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker

from markinote_api.platform.io import atomic_write_json, resource_lock
from markinote_api.platform.paths import PathValidationError, resolve_under_root, validate_storage_id

EXPECTED_SCHEMA_REVISION = "20260817_0004"

ConversationData = dict[str, Any]


class ConversationRepository(ABC):
    @abstractmethod
    def list(self) -> list[ConversationData]:
        raise NotImplementedError

    @abstractmethod
    def get(self, conversation_id: str) -> ConversationData | None:
        raise NotImplementedError

    @abstractmethod
    def save(self, conversation: ConversationData) -> None:
        raise NotImplementedError

    @abstractmethod
    def delete(self, conversation_id: str) -> bool:
        raise NotImplementedError

    def ready(self) -> bool:
        return True


class JsonConversationRepository(ConversationRepository):
    """Backward-compatible adapter for existing .ai_conversations JSON files."""

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, conversation_id: str) -> Path:
        # basename is redundant with the strict storage-ID validator, but also
        # makes the path sanitization boundary explicit to static analyzers.
        safe_id = os.path.basename(
            validate_storage_id(conversation_id, "conversation id")
        )
        filename = f"{safe_id}.json"
        path, normalized = resolve_under_root(self.root, filename, allow_root=False)
        canonical_path = Path(os.path.realpath(path))
        canonical_root = Path(os.path.realpath(self.root))

        try:
            contained = os.path.commonpath((canonical_root, canonical_path)) == str(
                canonical_root
            )
        except ValueError:
            contained = False

        # Conversation records are always direct children of ``self.root``.
        # Keeping this boundary check next to the filesystem operations makes
        # the containment guarantee explicit even if path helpers evolve.
        if (
            normalized != filename
            or not contained
            or canonical_path.parent != canonical_root
        ):
            raise PathValidationError("conversation path leaves its storage root")
        return canonical_path

    def list(self) -> list[ConversationData]:
        values, _ = self.scan()
        return list(values)

    def scan(self) -> tuple[Sequence[ConversationData], Sequence[dict[str, str]]]:
        """Return valid records and explicit corruption findings for migration audits."""
        values: list[ConversationData] = []
        errors: list[dict[str, str]] = []
        for path in sorted(self.root.glob("*.json")):
            try:
                value = self._read(path)
            except (OSError, ValueError, json.JSONDecodeError) as error:
                errors.append(
                    {
                        "file": path.name,
                        "code": "invalid_conversation_json",
                        "error_type": type(error).__name__,
                    }
                )
                continue
            if isinstance(value, dict):
                conversation_id = str(value.get("id", ""))
                if not conversation_id or conversation_id != path.stem:
                    errors.append(
                        {
                            "file": path.name,
                            "code": "conversation_id_mismatch",
                            "error_type": "ValueError",
                        }
                    )
                    continue
                values.append(value)
        return values, errors

    def get(self, conversation_id: str) -> ConversationData | None:
        path = self._path(conversation_id)
        if not path.is_file():
            return None
        try:
            return self._read(path)
        except (OSError, ValueError, json.JSONDecodeError):
            return None

    def save(self, conversation: ConversationData) -> None:
        conversation_id = str(conversation.get("id", ""))
        path = self._path(conversation_id)
        snapshot = copy.deepcopy(conversation)
        snapshot["updated_at"] = datetime.now(UTC).isoformat()
        with resource_lock(path):
            atomic_write_json(path, snapshot)
        conversation["updated_at"] = snapshot["updated_at"]

    def delete(self, conversation_id: str) -> bool:
        path = self._path(conversation_id)
        with resource_lock(path):
            if not path.exists():
                return False
            path.unlink()
        return True

    @staticmethod
    def _read(path: Path) -> ConversationData:
        with resource_lock(path), path.open("r", encoding="utf-8") as stream:
            value = json.load(stream)
        if not isinstance(value, dict) or not isinstance(value.get("messages", []), list):
            raise ValueError("invalid conversation document")
        return value


class Base(DeclarativeBase):
    pass


class ConversationRecord(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    messages: Mapped[list[MessageRecord]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="MessageRecord.position",
    )


class MessageRecord(Base):
    __tablename__ = "messages"
    __table_args__ = (UniqueConstraint("conversation_id", "position", name="uq_message_position"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    conversation: Mapped[ConversationRecord] = relationship(back_populates="messages")


class ToolCommandRecord(Base):
    __tablename__ = "tool_commands"

    command_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    user_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    run_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    conversation_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    tool_name: Mapped[str] = mapped_column(String(100), nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class OperationAuditRecord(Base):
    __tablename__ = "operation_audit"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    request_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    conversation_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    command_id: Mapped[str | None] = mapped_column(String(96), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    target: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AgentRunRecord(Base):
    """Metadata-only execution audit; prompts and credentials never belong here."""

    __tablename__ = "agent_runs"
    __table_args__ = (
        CheckConstraint(
            "state IN ('running', 'completed', 'failed', 'cancelled')",
            name="ck_agent_runs_state",
        ),
        Index("ix_agent_runs_state_finished_at", "state", "finished_at"),
    )

    run_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    request_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    user_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    conversation_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    conversation_attached_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    first_content_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)


class Database:
    def __init__(self, url: str, *, create_schema: bool = False):
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        self.engine = create_engine(url, pool_pre_ping=True, connect_args=connect_args)
        if url.startswith("sqlite"):
            @event.listens_for(self.engine, "connect")
            def _sqlite_pragmas(dbapi_connection, _connection_record) -> None:
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA foreign_keys = ON")
                cursor.execute("PRAGMA journal_mode = WAL")
                cursor.execute("PRAGMA busy_timeout = 10000")
                cursor.close()
        self.session_factory = sessionmaker(self.engine, expire_on_commit=False)
        self.requires_migration_revision = not create_schema
        if create_schema:
            Base.metadata.create_all(self.engine)

    def session(self) -> Session:
        return self.session_factory()

    def ready(self) -> bool:
        try:
            with self.engine.connect() as connection:
                connection.exec_driver_sql("SELECT 1")
                table_names = set(inspect(connection).get_table_names())
                if not set(Base.metadata.tables).issubset(table_names):
                    return False
                if self.requires_migration_revision:
                    if "alembic_version" not in table_names:
                        return False
                    revision = connection.exec_driver_sql(
                        "SELECT version_num FROM alembic_version"
                    ).scalar_one_or_none()
                    if revision != EXPECTED_SCHEMA_REVISION:
                        return False
            return True
        except Exception:
            return False

    def close(self) -> None:
        self.engine.dispose()


def _parse_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except ValueError:
            pass
    return datetime.now(UTC)


def _iso_datetime(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.isoformat()


class SqlConversationRepository(ConversationRepository):
    """Normalized SQL adapter suitable for SQLite and PostgreSQL."""

    def __init__(self, database: Database, *, user_id: str | None = None):
        self.database = database
        self.user_id = user_id

    def list(self) -> list[ConversationData]:
        with self.database.session() as session:
            rows = session.execute(
                select(ConversationRecord, func.count(MessageRecord.id))
                .outerjoin(
                    MessageRecord,
                    (MessageRecord.conversation_id == ConversationRecord.id)
                    & (MessageRecord.role != "system"),
                )
                .where(ConversationRecord.user_id == self.user_id)
                .group_by(ConversationRecord.id)
                .order_by(ConversationRecord.updated_at.desc())
            ).all()
            values: list[ConversationData] = []
            for record, message_count in rows:
                value = self._to_data(record, include_messages=False)
                value["message_count"] = message_count
                values.append(value)
            return values

    def get(self, conversation_id: str) -> ConversationData | None:
        validate_storage_id(conversation_id, "conversation id")
        with self.database.session() as session:
            record = session.scalar(
                select(ConversationRecord).where(
                    ConversationRecord.id == conversation_id,
                    ConversationRecord.user_id == self.user_id,
                )
            )
            if record is None:
                return None
            # Relationship data is materialized before the session closes.
            _ = list(record.messages)
            return self._to_data(record, include_messages=True)

    def save(self, conversation: ConversationData) -> None:
        conversation_id = validate_storage_id(str(conversation.get("id", "")), "conversation id")
        now = datetime.now(UTC)
        created_at = _parse_datetime(conversation.get("created_at"))
        messages = conversation.get("messages", [])
        metadata = {
            key: value
            for key, value in conversation.items()
            if key not in {"id", "title", "created_at", "updated_at", "messages"}
        }
        with self.database.session() as session, session.begin():
            record = session.scalar(
                select(ConversationRecord).where(
                    ConversationRecord.id == conversation_id,
                    ConversationRecord.user_id == self.user_id,
                )
            )
            if record is None:
                record = ConversationRecord(
                    id=conversation_id,
                    user_id=self.user_id,
                    title=str(conversation.get("title", "New conversation"))[:200],
                    created_at=created_at,
                    updated_at=now,
                    metadata_json=metadata,
                )
                session.add(record)
            else:
                record.title = str(conversation.get("title", record.title))[:200]
                record.updated_at = now
                record.metadata_json = metadata
                session.execute(delete(MessageRecord).where(MessageRecord.conversation_id == conversation_id))
            session.flush()
            for index, message in enumerate(messages if isinstance(messages, list) else []):
                if not isinstance(message, dict):
                    continue
                payload = {
                    key: value
                    for key, value in message.items()
                    if key not in {"role", "content"}
                }
                session.add(
                    MessageRecord(
                        conversation_id=conversation_id,
                        position=index,
                        role=str(message.get("role", ""))[:32],
                        content=message.get("content") if isinstance(message.get("content"), str) else None,
                        payload=payload,
                    )
                )
        conversation["updated_at"] = now.isoformat()

    def delete(self, conversation_id: str) -> bool:
        validate_storage_id(conversation_id, "conversation id")
        with self.database.session() as session, session.begin():
            record = session.scalar(
                select(ConversationRecord).where(
                    ConversationRecord.id == conversation_id,
                    ConversationRecord.user_id == self.user_id,
                )
            )
            if record is None:
                return False
            session.delete(record)
        return True

    def ready(self) -> bool:
        return self.database.ready()

    @staticmethod
    def _to_data(record: ConversationRecord, *, include_messages: bool) -> ConversationData:
        value: ConversationData = {
            "id": record.id,
            "title": record.title,
            "created_at": _iso_datetime(record.created_at),
            "updated_at": _iso_datetime(record.updated_at),
            **(record.metadata_json or {}),
        }
        if include_messages:
            value["messages"] = [
                {"role": message.role, "content": message.content or "", **(message.payload or {})}
                for message in record.messages
            ]
        return value
