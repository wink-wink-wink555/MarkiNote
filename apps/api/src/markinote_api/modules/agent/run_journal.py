"""Durable, metadata-only audit journal for AI agent runs."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, select, tuple_, update
from sqlalchemy.exc import IntegrityError

from markinote_api.modules.agent.ports import AgentRunData, TerminalAgentRunState
from markinote_api.modules.conversations.repository import AgentRunRecord, Database
from markinote_api.platform.io import atomic_write_json, resource_lock

PROCESS_RESTARTED_ERROR_CODE = "process_restarted"


class AgentRunJournalCorruptionError(RuntimeError):
    """The JSON audit cannot be trusted and must not be overwritten."""


def _utc(value: datetime) -> datetime:
    return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)


def _iso(value: datetime | None) -> str | None:
    return _utc(value).isoformat() if value is not None else None


def _validate_metadata(
    *,
    run_id: str,
    request_id: str,
    provider: str | None = None,
    model: str | None = None,
    conversation_id: str | None = None,
    error_code: str | None = None,
) -> None:
    values = {
        "run_id": (run_id, 96),
        "request_id": (request_id, 128),
        "provider": (provider, 64),
        "model": (model, 128),
        "conversation_id": (conversation_id, 64),
        "error_code": (error_code, 64),
    }
    for name, (value, limit) in values.items():
        if value is not None and (not value or len(value) > limit):
            raise ValueError(f"{name} must contain 1 to {limit} characters")


class JsonAgentRunJournal:
    """Atomic single-node adapter colocated with the other local journals."""

    def __init__(
        self,
        root: str | Path,
        *,
        retention_ttl: timedelta = timedelta(days=30),
        max_records: int = 10_000,
        now: Callable[[], datetime] | None = None,
    ):
        if retention_ttl <= timedelta(0):
            raise ValueError("retention_ttl must be positive")
        if max_records <= 0:
            raise ValueError("max_records must be positive")
        self.root = Path(root).resolve() / "journal"
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "agent_runs.json"
        self.retention_ttl = retention_ttl
        self.max_records = max_records
        self._now = now or (lambda: datetime.now(UTC))

    def start(
        self,
        *,
        run_id: str,
        request_id: str,
        provider: str,
        model: str,
    ) -> bool:
        _validate_metadata(
            run_id=run_id,
            request_id=request_id,
            provider=provider,
            model=model,
        )
        with resource_lock(self.path):
            records = self._read()
            current_time = _utc(self._now())
            self._apply_retention(records, current_time)
            key = self._record_key(run_id, request_id)
            if key in records:
                atomic_write_json(self.path, records)
                return False
            now = current_time.isoformat()
            records[key] = {
                "run_id": run_id,
                "request_id": request_id,
                "conversation_id": None,
                "provider": provider,
                "model": model,
                "state": "running",
                "started_at": now,
                "conversation_attached_at": None,
                "first_content_at": None,
                "finished_at": None,
                "updated_at": now,
                "error_code": None,
            }
            self._apply_retention(records, current_time)
            atomic_write_json(self.path, records)
            return True

    def attach_conversation(self, run_id: str, request_id: str, conversation_id: str) -> bool:
        _validate_metadata(
            run_id=run_id,
            request_id=request_id,
            conversation_id=conversation_id,
        )
        return self._update_running(
            run_id,
            request_id,
            lambda record, now: record.update(
                {
                    "conversation_id": conversation_id,
                    "conversation_attached_at": record.get("conversation_attached_at") or now,
                    "updated_at": now,
                }
            ),
        )

    def mark_first_content(self, run_id: str, request_id: str) -> bool:
        return self._update_running(
            run_id,
            request_id,
            lambda record, now: record.update(
                {
                    "first_content_at": record.get("first_content_at") or now,
                    "updated_at": now,
                }
            ),
        )

    def finish(
        self,
        run_id: str,
        request_id: str,
        state: TerminalAgentRunState,
        *,
        error_code: str | None = None,
    ) -> bool:
        if state not in {"completed", "failed", "cancelled"}:
            raise ValueError("agent run terminal state is invalid")
        _validate_metadata(run_id=run_id, request_id=request_id, error_code=error_code)
        return self._update_running(
            run_id,
            request_id,
            lambda record, now: record.update(
                {
                    "state": state,
                    "finished_at": now,
                    "updated_at": now,
                    "error_code": error_code,
                }
            ),
        )

    def inspect(self, run_id: str, request_id: str) -> AgentRunData | None:
        with resource_lock(self.path):
            value = self._read().get(self._record_key(run_id, request_id))
            return dict(value) if isinstance(value, dict) else None

    def reconcile_running(self, *, limit: int = 1000, apply: bool = False) -> int:
        """Count or fail one bounded batch after the sole writer has stopped.

        Calling this while another process can still own a run is unsafe. The
        composition root therefore guards startup reconciliation with an
        explicit single-writer operator acknowledgement.
        """
        if not 1 <= limit <= 10_000:
            raise ValueError("limit must be between 1 and 10000")
        with resource_lock(self.path):
            records = self._read()
            candidates = sorted(
                (
                    (self._timestamp(record.get("started_at")), key)
                    for key, record in records.items()
                    if isinstance(record, dict) and record.get("state") == "running"
                ),
                key=lambda item: (item[0] or datetime.min.replace(tzinfo=UTC), item[1]),
            )[:limit]
            if not apply:
                return len(candidates)

            now = _utc(self._now()).isoformat()
            reconciled = 0
            for _, key in candidates:
                record = records.get(key)
                # Preserve the same state fence as ``finish`` even though the
                # file lock already serializes this adapter in one node.
                if not isinstance(record, dict) or record.get("state") != "running":
                    continue
                record.update(
                    {
                        "state": "failed",
                        "finished_at": now,
                        "updated_at": now,
                        "error_code": PROCESS_RESTARTED_ERROR_CODE,
                    }
                )
                reconciled += 1
            if reconciled:
                atomic_write_json(self.path, records)
            return reconciled

    def prune_terminal(self, *, before: datetime, limit: int = 1000) -> int:
        if limit <= 0:
            raise ValueError("limit must be positive")
        cutoff = _utc(before)
        with resource_lock(self.path):
            records = self._read()
            candidates = self._terminal_records(records)
            expired = [
                key
                for key, timestamp in sorted(candidates, key=lambda item: item[1])
                if timestamp < cutoff
            ][:limit]
            for key in expired:
                records.pop(key, None)
            if expired:
                atomic_write_json(self.path, records)
            return len(expired)

    def _update_running(
        self,
        run_id: str,
        request_id: str,
        mutation: Callable[[dict[str, Any], str], None],
    ) -> bool:
        with resource_lock(self.path):
            records = self._read()
            record = records.get(self._record_key(run_id, request_id))
            if not isinstance(record, dict) or record.get("state") != "running":
                return False
            current_time = _utc(self._now())
            mutation(record, current_time.isoformat())
            self._apply_retention(records, current_time)
            atomic_write_json(self.path, records)
            return True

    def _apply_retention(self, records: dict[str, Any], current_time: datetime) -> None:
        cutoff = current_time - self.retention_ttl
        terminal = self._terminal_records(records)
        for key, timestamp in terminal:
            if timestamp < cutoff:
                records.pop(key, None)

        terminal = self._terminal_records(records)
        overflow = max(0, len(records) - self.max_records)
        for key, _ in sorted(terminal, key=lambda item: item[1])[:overflow]:
            records.pop(key, None)

    @classmethod
    def _terminal_records(cls, records: dict[str, Any]) -> list[tuple[str, datetime]]:
        values: list[tuple[str, datetime]] = []
        for key, record in records.items():
            if not isinstance(record, dict) or record.get("state") not in {
                "completed",
                "failed",
                "cancelled",
            }:
                continue
            timestamp = cls._timestamp(record.get("finished_at")) or cls._timestamp(
                record.get("started_at")
            )
            if timestamp is not None:
                values.append((key, timestamp))
        return values

    @staticmethod
    def _timestamp(value: object) -> datetime | None:
        if not isinstance(value, str):
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return _utc(parsed)

    def _read(self) -> dict[str, Any]:
        if not self.path.is_file():
            return {}
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise AgentRunJournalCorruptionError("agent run journal is unreadable") from error
        if not isinstance(value, dict):
            raise AgentRunJournalCorruptionError("agent run journal has an invalid shape")
        return value

    @staticmethod
    def _record_key(run_id: str, request_id: str) -> str:
        material = f"{len(run_id)}:{run_id}{request_id}".encode()
        return hashlib.sha256(material).hexdigest()


class SqlAgentRunJournal:
    """Transactional adapter; operators schedule bounded ``prune_terminal`` batches."""

    def __init__(
        self,
        database: Database,
        *,
        user_id: str | None = None,
        now: Callable[[], datetime] | None = None,
    ):
        self.database = database
        self.user_id = user_id
        self._now = now or (lambda: datetime.now(UTC))

    def start(
        self,
        *,
        run_id: str,
        request_id: str,
        provider: str,
        model: str,
    ) -> bool:
        _validate_metadata(
            run_id=run_id,
            request_id=request_id,
            provider=provider,
            model=model,
        )
        now = _utc(self._now())
        try:
            with self.database.session() as session, session.begin():
                session.add(
                    AgentRunRecord(
                        run_id=run_id,
                        request_id=request_id,
                        user_id=self.user_id,
                        conversation_id=None,
                        provider=provider,
                        model=model,
                        state="running",
                        started_at=now,
                        conversation_attached_at=None,
                        first_content_at=None,
                        finished_at=None,
                        updated_at=now,
                        error_code=None,
                    )
                )
            return True
        except IntegrityError:
            return False

    def attach_conversation(self, run_id: str, request_id: str, conversation_id: str) -> bool:
        _validate_metadata(
            run_id=run_id,
            request_id=request_id,
            conversation_id=conversation_id,
        )
        now = _utc(self._now())
        with self.database.session() as session, session.begin():
            result = session.execute(
                update(AgentRunRecord)
                .where(
                    AgentRunRecord.run_id == run_id,
                    AgentRunRecord.request_id == request_id,
                    AgentRunRecord.user_id == self.user_id,
                    AgentRunRecord.state == "running",
                )
                .values(
                    conversation_id=conversation_id,
                    conversation_attached_at=func.coalesce(
                        AgentRunRecord.conversation_attached_at,
                        now,
                    ),
                    updated_at=now,
                )
                .returning(AgentRunRecord.run_id)
            )
            return result.scalar_one_or_none() is not None

    def mark_first_content(self, run_id: str, request_id: str) -> bool:
        now = _utc(self._now())
        with self.database.session() as session, session.begin():
            result = session.execute(
                update(AgentRunRecord)
                .where(
                    AgentRunRecord.run_id == run_id,
                    AgentRunRecord.request_id == request_id,
                    AgentRunRecord.user_id == self.user_id,
                    AgentRunRecord.state == "running",
                    AgentRunRecord.first_content_at.is_(None),
                )
                .values(first_content_at=now, updated_at=now)
                .returning(AgentRunRecord.run_id)
            )
            if result.scalar_one_or_none() is not None:
                return True
        # Repeated content events are idempotent while the run stays active.
        current = self.inspect(run_id, request_id)
        return bool(current and current["state"] == "running" and current["first_content_at"])

    def finish(
        self,
        run_id: str,
        request_id: str,
        state: TerminalAgentRunState,
        *,
        error_code: str | None = None,
    ) -> bool:
        if state not in {"completed", "failed", "cancelled"}:
            raise ValueError("agent run terminal state is invalid")
        _validate_metadata(run_id=run_id, request_id=request_id, error_code=error_code)
        now = _utc(self._now())
        with self.database.session() as session, session.begin():
            result = session.execute(
                update(AgentRunRecord)
                .where(
                    AgentRunRecord.run_id == run_id,
                    AgentRunRecord.request_id == request_id,
                    AgentRunRecord.user_id == self.user_id,
                    AgentRunRecord.state == "running",
                )
                .values(
                    state=state,
                    finished_at=now,
                    updated_at=now,
                    error_code=error_code,
                )
                .returning(AgentRunRecord.run_id)
            )
            return result.scalar_one_or_none() is not None

    def inspect(self, run_id: str, request_id: str) -> AgentRunData | None:
        with self.database.session() as session:
            record = session.scalar(
                select(AgentRunRecord).where(
                    AgentRunRecord.run_id == run_id,
                    AgentRunRecord.request_id == request_id,
                    AgentRunRecord.user_id == self.user_id,
                )
            )
            if record is None:
                return None
            return {
                "run_id": record.run_id,
                "request_id": record.request_id,
                "conversation_id": record.conversation_id,
                "provider": record.provider,
                "model": record.model,
                "state": record.state,
                "started_at": _iso(record.started_at),
                "conversation_attached_at": _iso(record.conversation_attached_at),
                "first_content_at": _iso(record.first_content_at),
                "finished_at": _iso(record.finished_at),
                "updated_at": _iso(record.updated_at),
                "error_code": record.error_code,
            }

    def reconcile_running(self, *, limit: int = 1000, apply: bool = False) -> int:
        """Count or fail one transactionally fenced, bounded running batch."""
        if not 1 <= limit <= 10_000:
            raise ValueError("limit must be between 1 and 10000")
        now = _utc(self._now())
        with self.database.session() as session, session.begin():
            keys = session.execute(
                select(AgentRunRecord.run_id, AgentRunRecord.request_id)
                .where(
                    AgentRunRecord.state == "running",
                    AgentRunRecord.user_id == self.user_id,
                )
                .order_by(
                    AgentRunRecord.started_at,
                    AgentRunRecord.run_id,
                    AgentRunRecord.request_id,
                )
                .limit(limit)
            ).all()
            if not keys or not apply:
                return len(keys)
            reconciled = session.execute(
                update(AgentRunRecord)
                .where(
                    tuple_(AgentRunRecord.run_id, AgentRunRecord.request_id).in_(keys),
                    AgentRunRecord.state == "running",
                    AgentRunRecord.user_id == self.user_id,
                )
                .values(
                    state="failed",
                    finished_at=now,
                    updated_at=now,
                    error_code=PROCESS_RESTARTED_ERROR_CODE,
                )
                .returning(AgentRunRecord.run_id)
            ).scalars()
            return len(reconciled.all())

    def prune_terminal(self, *, before: datetime, limit: int = 1000) -> int:
        if limit <= 0:
            raise ValueError("limit must be positive")
        cutoff = _utc(before)
        with self.database.session() as session, session.begin():
            keys = session.execute(
                select(AgentRunRecord.run_id, AgentRunRecord.request_id)
                .where(
                    AgentRunRecord.state.in_(("completed", "failed", "cancelled")),
                    AgentRunRecord.user_id == self.user_id,
                    AgentRunRecord.finished_at.is_not(None),
                    AgentRunRecord.finished_at < cutoff,
                )
                .order_by(AgentRunRecord.finished_at, AgentRunRecord.run_id)
                .limit(limit)
            ).all()
            if not keys:
                return 0
            session.execute(
                delete(AgentRunRecord).where(
                    tuple_(AgentRunRecord.run_id, AgentRunRecord.request_id).in_(keys)
                    , AgentRunRecord.user_id == self.user_id
                )
            )
            return len(keys)
