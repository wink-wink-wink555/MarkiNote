"""Tool command idempotency and operation audit."""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from collections.abc import Callable
from contextvars import ContextVar
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import delete, exists, or_, select, update
from sqlalchemy.exc import IntegrityError

from markinote_api.modules.conversations.repository import (
    Database,
    OperationAuditRecord,
    ToolCommandRecord,
)
from markinote_api.platform.io import atomic_write_json, resource_lock


class CommandJournal(ABC):
    @abstractmethod
    def claim(
        self,
        command_id: str,
        *,
        run_id: str,
        conversation_id: str | None,
        tool_name: str,
    ) -> tuple[bool, dict[str, Any] | None]:
        """Return (claimed, previous_result)."""

    @abstractmethod
    def complete(self, command_id: str, result: dict[str, Any]) -> bool:
        raise NotImplementedError

    @abstractmethod
    def fail(self, command_id: str, result: dict[str, Any]) -> bool:
        raise NotImplementedError

    @abstractmethod
    def inspect(self, command_id: str) -> dict[str, Any] | None:
        """Return current durable state without claiming or renewing it."""

    @abstractmethod
    def audit(
        self,
        *,
        request_id: str,
        action: str,
        outcome: str,
        conversation_id: str | None = None,
        command_id: str | None = None,
        target: str | None = None,
        content_hash: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        raise NotImplementedError


class CommandJournalCorruptionError(RuntimeError):
    """Raised when idempotency state cannot be read safely."""


class CommandOwnershipConflictError(RuntimeError):
    """Raised when a command identifier is reused outside its original scope."""


def _assert_command_owner(
    existing: dict[str, Any] | ToolCommandRecord,
    *,
    run_id: str,
    conversation_id: str | None,
    tool_name: str,
) -> None:
    def value(name: str) -> Any:
        return existing.get(name) if isinstance(existing, dict) else getattr(existing, name)

    if (
        value("run_id") != run_id
        or value("conversation_id") != conversation_id
        or value("tool_name") != tool_name
    ):
        raise CommandOwnershipConflictError(
            "command identifier ownership does not match the original scope"
        )


class JsonCommandJournal(CommandJournal):
    """Atomic local journal used by the single-node profile."""

    def __init__(
        self,
        root: str | Path,
        *,
        lease_duration: timedelta = timedelta(minutes=5),
        retention_ttl: timedelta = timedelta(days=30),
        max_commands: int = 10_000,
        now: Callable[[], datetime] | None = None,
    ):
        if lease_duration <= timedelta(0):
            raise ValueError("lease_duration must be positive")
        if retention_ttl <= timedelta(0):
            raise ValueError("retention_ttl must be positive")
        self.root = Path(root).resolve() / "journal"
        self.root.mkdir(parents=True, exist_ok=True)
        self.commands_file = self.root / "commands.json"
        self.audit_file = self.root / "audit.json"
        self.lease_duration = lease_duration
        self.retention_ttl = retention_ttl
        self.max_commands = max(1, max_commands)
        self._now = now or (lambda: datetime.now(UTC))
        self._owned_attempts: ContextVar[dict[str, int] | None] = ContextVar(
            f"json_command_attempts_{id(self)}",
            default=None,
        )

    def claim(
        self,
        command_id: str,
        *,
        run_id: str,
        conversation_id: str | None,
        tool_name: str,
    ) -> tuple[bool, dict[str, Any] | None]:
        with resource_lock(self.commands_file):
            commands = self._read_mapping(self.commands_file)
            current_time = self._utc_now()
            self._apply_retention(commands, current_time)
            existing = commands.get(command_id)
            if existing:
                _assert_command_owner(
                    existing,
                    run_id=run_id,
                    conversation_id=conversation_id,
                    tool_name=tool_name,
                )
                if existing.get("state") == "running" and self._lease_expired(
                    existing.get("lease_until"), current_time
                ):
                    existing.update(
                        {
                            "state": "running",
                            "result": None,
                            "lease_until": (current_time + self.lease_duration).isoformat(),
                            "attempt": max(1, self._integer(existing.get("attempt"))) + 1,
                            "claimed_at": current_time.isoformat(),
                            "completed_at": None,
                        }
                    )
                    atomic_write_json(self.commands_file, commands)
                    self._remember_claim(command_id, int(existing["attempt"]))
                    return True, None
                # Persist pruning even when this command itself is a duplicate.
                atomic_write_json(self.commands_file, commands)
                return False, existing.get("result")
            commands[command_id] = {
                "run_id": run_id,
                "conversation_id": conversation_id,
                "tool_name": tool_name,
                "state": "running",
                "result": None,
                "created_at": current_time.isoformat(),
                "claimed_at": current_time.isoformat(),
                "lease_until": (current_time + self.lease_duration).isoformat(),
                "attempt": 1,
            }
            atomic_write_json(self.commands_file, commands)
            self._remember_claim(command_id, 1)
        return True, None

    def complete(self, command_id: str, result: dict[str, Any]) -> bool:
        return self._finish(command_id, "completed", result)

    def fail(self, command_id: str, result: dict[str, Any]) -> bool:
        return self._finish(command_id, "failed", result)

    def inspect(self, command_id: str) -> dict[str, Any] | None:
        with resource_lock(self.commands_file):
            current = self._read_mapping(self.commands_file).get(command_id)
            return dict(current) if isinstance(current, dict) else None

    def audit(self, **entry: Any) -> None:
        with resource_lock(self.audit_file):
            values = self._read_list(self.audit_file)
            sanitized = {**entry, "created_at": datetime.now(UTC).isoformat()}
            values.append(sanitized)
            # Bound local operational data. Production retention is a DB concern.
            atomic_write_json(self.audit_file, values[-5000:])

    def _finish(self, command_id: str, state: str, result: dict[str, Any]) -> bool:
        with resource_lock(self.commands_file):
            commands = self._read_mapping(self.commands_file)
            current = commands.get(command_id)
            if not isinstance(current, dict):
                return False
            owned_attempt = self._owned_attempt(command_id)
            if (
                owned_attempt is None
                or current.get("state") != "running"
                or self._integer(current.get("attempt")) != owned_attempt
            ):
                # A newer lease owner or an already-durable terminal state
                # fences this context, including copied ContextVar snapshots.
                return False
            current_time = self._utc_now()
            current.update(
                {
                    "state": state,
                    "result": result,
                    "lease_until": None,
                    "completed_at": current_time.isoformat(),
                }
            )
            self._apply_retention(commands, current_time)
            atomic_write_json(self.commands_file, commands)
            self._forget_claim(command_id)
            return True

    def _utc_now(self) -> datetime:
        value = self._now()
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)

    @staticmethod
    def _integer(value: object) -> int:
        return value if isinstance(value, int) and not isinstance(value, bool) else 0

    @staticmethod
    def _timestamp(value: object) -> datetime | None:
        if not isinstance(value, str):
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)

    def _lease_expired(self, value: object, current_time: datetime) -> bool:
        lease_until = self._timestamp(value)
        # Pre-lease running records are recoverable immediately after upgrade.
        return lease_until is None or lease_until <= current_time

    def _apply_retention(self, commands: dict[str, Any], current_time: datetime) -> None:
        cutoff = current_time - self.retention_ttl
        terminal: list[tuple[str, datetime]] = []
        for command_id, value in list(commands.items()):
            if not isinstance(value, dict) or value.get("state") == "running":
                continue
            timestamp = self._timestamp(value.get("completed_at")) or self._timestamp(
                value.get("created_at")
            )
            if timestamp is not None and timestamp < cutoff:
                commands.pop(command_id, None)
                continue
            terminal.append((command_id, timestamp or datetime.min.replace(tzinfo=UTC)))

        # Never evict an in-flight command. If active commands alone exceed the
        # bound, the journal temporarily grows instead of breaking idempotency.
        overflow = max(0, len(commands) - self.max_commands)
        for command_id, _ in sorted(terminal, key=lambda item: item[1])[:overflow]:
            commands.pop(command_id, None)

    def _remember_claim(self, command_id: str, attempt: int) -> None:
        values = dict(self._owned_attempts.get() or {})
        values[command_id] = attempt
        self._owned_attempts.set(values)

    def _owned_attempt(self, command_id: str) -> int | None:
        return (self._owned_attempts.get() or {}).get(command_id)

    def _forget_claim(self, command_id: str) -> None:
        values = dict(self._owned_attempts.get() or {})
        values.pop(command_id, None)
        self._owned_attempts.set(values)

    @staticmethod
    def _read_mapping(path: Path) -> dict[str, Any]:
        if not path.is_file():
            return {}
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise CommandJournalCorruptionError(
                "command journal is unreadable; refusing a potentially duplicate execution"
            ) from error
        if not isinstance(value, dict):
            raise CommandJournalCorruptionError(
                "command journal has an invalid shape; refusing a potentially duplicate execution"
            )
        return value

    @staticmethod
    def _read_list(path: Path) -> list[dict[str, Any]]:
        if not path.is_file():
            return []
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        return value if isinstance(value, list) else []


class SqlCommandJournal(CommandJournal):
    """Database-backed idempotency for multi-worker deployments."""

    def __init__(
        self,
        database: Database,
        *,
        user_id: str | None = None,
        lease_duration: timedelta = timedelta(minutes=5),
        now: Callable[[], datetime] | None = None,
    ):
        if lease_duration <= timedelta(0):
            raise ValueError("lease_duration must be positive")
        self.database = database
        self.user_id = user_id
        self.lease_duration = lease_duration
        self._now = now or (lambda: datetime.now(UTC))
        self._owned_attempts: ContextVar[dict[str, int] | None] = ContextVar(
            f"sql_command_attempts_{id(self)}",
            default=None,
        )

    def claim(
        self,
        command_id: str,
        *,
        run_id: str,
        conversation_id: str | None,
        tool_name: str,
    ) -> tuple[bool, dict[str, Any] | None]:
        current_time = self._utc_now()
        try:
            with self.database.session() as session, session.begin():
                session.add(
                    ToolCommandRecord(
                        command_id=command_id,
                        user_id=self.user_id,
                        run_id=run_id,
                        conversation_id=conversation_id,
                        tool_name=tool_name,
                        state="running",
                        result=None,
                        created_at=current_time,
                        completed_at=None,
                        lease_until=current_time + self.lease_duration,
                        attempt=1,
                    )
                )
            self._remember_claim(command_id, 1)
            return True, None
        except IntegrityError:
            with self.database.session() as session, session.begin():
                existing = session.scalar(
                    select(ToolCommandRecord).where(
                        ToolCommandRecord.command_id == command_id,
                        ToolCommandRecord.user_id == self.user_id,
                    )
                )
                if existing is None:
                    raise CommandJournalCorruptionError(
                        "command uniqueness conflict has no durable record"
                    ) from None
                _assert_command_owner(
                    existing,
                    run_id=run_id,
                    conversation_id=conversation_id,
                    tool_name=tool_name,
                )
                takeover = session.execute(
                    update(ToolCommandRecord)
                    .where(
                        ToolCommandRecord.command_id == command_id,
                        ToolCommandRecord.user_id == self.user_id,
                        ToolCommandRecord.run_id == run_id,
                        ToolCommandRecord.conversation_id == conversation_id,
                        ToolCommandRecord.tool_name == tool_name,
                        ToolCommandRecord.state == "running",
                        or_(
                            ToolCommandRecord.lease_until.is_(None),
                            ToolCommandRecord.lease_until <= current_time,
                        ),
                    )
                    .values(
                        result=None,
                        completed_at=None,
                        lease_until=current_time + self.lease_duration,
                        attempt=ToolCommandRecord.attempt + 1,
                    )
                    .returning(ToolCommandRecord.attempt)
                    .execution_options(synchronize_session=False)
                )
                claimed_attempt = takeover.scalar_one_or_none()
                if claimed_attempt is not None:
                    self._remember_claim(command_id, claimed_attempt)
                    return True, None
                # The original owner can commit between the SELECT above and
                # this conditional takeover. Refresh the identity-map entry so
                # a duplicate observes that durable terminal result instead of
                # incorrectly reporting that the command is still running.
                session.expire_all()
                durable = session.scalar(
                    select(ToolCommandRecord)
                    .where(
                        ToolCommandRecord.command_id == command_id,
                        ToolCommandRecord.user_id == self.user_id,
                    )
                    .execution_options(populate_existing=True)
                )
                if durable is None:
                    raise CommandJournalCorruptionError(
                        "command record disappeared during lease reconciliation"
                    ) from None
                _assert_command_owner(
                    durable,
                    run_id=run_id,
                    conversation_id=conversation_id,
                    tool_name=tool_name,
                )
                return False, durable.result

    def complete(self, command_id: str, result: dict[str, Any]) -> bool:
        return self._finish(command_id, "completed", result)

    def fail(self, command_id: str, result: dict[str, Any]) -> bool:
        return self._finish(command_id, "failed", result)

    def inspect(self, command_id: str) -> dict[str, Any] | None:
        with self.database.session() as session:
            record = session.scalar(
                select(ToolCommandRecord).where(
                    ToolCommandRecord.command_id == command_id,
                    ToolCommandRecord.user_id == self.user_id,
                )
            )
            if record is None:
                return None
            return {
                "run_id": record.run_id,
                "conversation_id": record.conversation_id,
                "tool_name": record.tool_name,
                "state": record.state,
                "result": record.result,
                "attempt": record.attempt,
                "lease_until": record.lease_until.isoformat() if record.lease_until else None,
            }

    def terminal_retention_candidates(
        self,
        *,
        before: datetime,
        limit: int = 1_000,
        scan_limit: int = 10_000,
        protected_backup_groups: set[str] | None = None,
    ) -> tuple[list[str], int, int]:
        """Return a bounded safe-delete batch and scanned/protected counts.

        ``None`` means the caller cannot verify backup storage, so every row
        with a backup-group reference is protected. Passing a set allows rows
        whose referenced backup group has already expired to be retained only
        by the normal TTL. Recovery-required rows are always protected.
        """
        if limit < 1 or scan_limit < limit:
            raise ValueError("retention bounds are invalid")
        cutoff = self._as_utc(before)
        with self.database.session() as session:
            records = list(
                session.execute(
                    select(ToolCommandRecord.command_id, ToolCommandRecord.result)
                    .where(
                        ToolCommandRecord.state.in_(("completed", "failed")),
                        ToolCommandRecord.user_id == self.user_id,
                        ToolCommandRecord.completed_at.is_not(None),
                        ToolCommandRecord.completed_at < cutoff,
                    )
                    .order_by(ToolCommandRecord.completed_at, ToolCommandRecord.command_id)
                    .limit(scan_limit)
                )
            )
        selected: list[str] = []
        protected_count = 0
        for command_id, result in records:
            if self._result_requires_retention(result, protected_backup_groups):
                protected_count += 1
                continue
            selected.append(command_id)
            if len(selected) == limit:
                break
        return selected, len(records), protected_count

    def prune_terminal(
        self,
        *,
        before: datetime,
        limit: int = 1_000,
        scan_limit: int = 10_000,
        protected_backup_groups: set[str] | None = None,
    ) -> int:
        command_ids, _, _ = self.terminal_retention_candidates(
            before=before,
            limit=limit,
            scan_limit=scan_limit,
            protected_backup_groups=protected_backup_groups,
        )
        if not command_ids:
            return 0
        cutoff = self._as_utc(before)
        with self.database.session() as session, session.begin():
            result = session.execute(
                delete(ToolCommandRecord).where(
                    ToolCommandRecord.command_id.in_(command_ids),
                    ToolCommandRecord.user_id == self.user_id,
                    ToolCommandRecord.state.in_(("completed", "failed")),
                    ToolCommandRecord.completed_at.is_not(None),
                    ToolCommandRecord.completed_at < cutoff,
                )
            )
        return max(0, int(getattr(result, "rowcount", 0) or 0))

    def audit_retention_candidates(
        self,
        *,
        before: datetime,
        limit: int = 1_000,
    ) -> list[int]:
        """Select old audit rows that are not tied to a retained command."""
        if limit < 1:
            raise ValueError("retention limit must be positive")
        cutoff = self._as_utc(before)
        retained_command = exists(
            select(ToolCommandRecord.command_id).where(
                ToolCommandRecord.command_id == OperationAuditRecord.command_id
                , ToolCommandRecord.user_id == self.user_id
            )
        )
        with self.database.session() as session:
            return list(
                session.scalars(
                    select(OperationAuditRecord.id)
                    .where(
                        OperationAuditRecord.created_at < cutoff,
                        OperationAuditRecord.user_id == self.user_id,
                        ~retained_command,
                    )
                    .order_by(OperationAuditRecord.created_at, OperationAuditRecord.id)
                    .limit(limit)
                )
            )

    def prune_audit(self, *, before: datetime, limit: int = 1_000) -> int:
        audit_ids = self.audit_retention_candidates(before=before, limit=limit)
        if not audit_ids:
            return 0
        cutoff = self._as_utc(before)
        retained_command = exists(
            select(ToolCommandRecord.command_id).where(
                ToolCommandRecord.command_id == OperationAuditRecord.command_id
                , ToolCommandRecord.user_id == self.user_id
            )
        )
        with self.database.session() as session, session.begin():
            result = session.execute(
                delete(OperationAuditRecord).where(
                    OperationAuditRecord.id.in_(audit_ids),
                    OperationAuditRecord.user_id == self.user_id,
                    OperationAuditRecord.created_at < cutoff,
                    ~retained_command,
                )
            )
        return max(0, int(getattr(result, "rowcount", 0) or 0))

    def _finish(self, command_id: str, state: str, result: dict[str, Any]) -> bool:
        owned_attempt = self._owned_attempt(command_id)
        if owned_attempt is None:
            return False
        with self.database.session() as session, session.begin():
            terminal = session.execute(
                update(ToolCommandRecord)
                .where(
                    ToolCommandRecord.command_id == command_id,
                    ToolCommandRecord.user_id == self.user_id,
                    ToolCommandRecord.state == "running",
                    ToolCommandRecord.attempt == owned_attempt,
                )
                .values(
                    state=state,
                    result=result,
                    completed_at=self._utc_now(),
                    lease_until=None,
                )
                .returning(ToolCommandRecord.command_id)
            )
            finished = terminal.scalar_one_or_none() is not None
        if finished:
            self._forget_claim(command_id)
        return finished

    def _utc_now(self) -> datetime:
        value = self._now()
        return self._as_utc(value)

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)

    @staticmethod
    def _result_requires_retention(
        result: object,
        protected_backup_groups: set[str] | None,
    ) -> bool:
        if result is None:
            return False
        if not isinstance(result, dict):
            return True
        backup_info = result.get("backup_info")
        if bool(result.get("recovery_required")) or (
            isinstance(backup_info, dict) and bool(backup_info.get("recovery_required"))
        ):
            return True
        backup_group_id = result.get("backup_group_id")
        if not isinstance(backup_group_id, str) or not backup_group_id:
            return False
        return protected_backup_groups is None or backup_group_id in protected_backup_groups

    def _remember_claim(self, command_id: str, attempt: int) -> None:
        values = dict(self._owned_attempts.get() or {})
        values[command_id] = attempt
        self._owned_attempts.set(values)

    def _owned_attempt(self, command_id: str) -> int | None:
        return (self._owned_attempts.get() or {}).get(command_id)

    def _forget_claim(self, command_id: str) -> None:
        values = dict(self._owned_attempts.get() or {})
        values.pop(command_id, None)
        self._owned_attempts.set(values)

    def audit(self, **entry: Any) -> None:
        with self.database.session() as session, session.begin():
            session.add(
                OperationAuditRecord(
                    user_id=self.user_id,
                    request_id=str(entry.get("request_id", ""))[:128],
                    conversation_id=entry.get("conversation_id"),
                    command_id=entry.get("command_id"),
                    action=str(entry.get("action", ""))[:100],
                    target=entry.get("target"),
                    outcome=str(entry.get("outcome", ""))[:32],
                    content_hash=entry.get("content_hash"),
                    details=entry.get("details") or {},
                    created_at=datetime.now(UTC),
                )
            )
