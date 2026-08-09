"""Durable compensation for conversation-triggered file rollbacks."""
from __future__ import annotations

import copy
import json
import logging
import shutil
import uuid
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from markinote_api.modules.conversations.repository import ConversationData, ConversationRepository
from markinote_api.modules.operations.backup import BackupManager
from markinote_api.platform.errors import Problem
from markinote_api.platform.io import atomic_write_json, resource_lock
from markinote_api.platform.metrics import OPERATION_ROLLBACK_ATTEMPTS
from markinote_api.platform.paths import resolve_under_root

LOGGER = logging.getLogger(__name__)

TERMINAL_STAGES = {
    "committed",
    "abandoned_before_rollback",
    "rollback_failed_compensated",
    "persistence_failed_compensated",
    "recovered_compensated",
}


class ConversationRollbackSaga:
    """Write-ahead Saga log for rollback-then-truncate workflows.

    The repository and the Markdown library cannot share a transaction. Before
    touching either, this coordinator snapshots every affected library path and
    the corresponding backup manifests. An interrupted or failed Saga therefore
    has one deterministic recovery action: restore the pre-truncate file and
    manifest state, then leave the conversation unchanged.
    """

    def __init__(self, backup_manager: BackupManager):
        self.backup_manager = backup_manager
        self.root = Path(backup_manager.backup_dir).resolve() / "conversation-sagas"
        self.root.mkdir(parents=True, exist_ok=True)

    def recover(self, repository: ConversationRepository, conversation_id: str) -> None:
        """Resolve non-terminal records before accepting another truncation."""
        for record_path in sorted(self.root.glob("*/record.json")):
            try:
                record = self._read_record(record_path)
            except (OSError, ValueError, json.JSONDecodeError) as error:
                raise Problem(
                    503,
                    "conversation_saga_journal_corrupt",
                    "Conversation recovery journal is corrupt",
                    "File rollback safety cannot be established until the Saga journal is repaired.",
                ) from error
            if record.get("conversation_id") != conversation_id:
                continue
            stage = str(record.get("stage", ""))
            if stage in TERMINAL_STAGES:
                # Compact records written by older versions too. A crash after
                # the terminal decision but before payload cleanup must not
                # retain conversation text indefinitely.
                self._release_terminal_payload(record_path, record)
                continue
            if stage == "snapshotting":
                # No rollback can start until the record reaches `prepared`.
                self._transition(record_path, record, "abandoned_before_rollback")
                continue

            current = repository.get(conversation_id)
            if (
                stage in {"files_rolled_back", "persisting"}
                and current is not None
                and current.get("messages", []) == record.get("target_messages", [])
            ):
                self._transition(record_path, record, "committed")
                continue

            errors = self._restore(record_path.parent, record)
            if errors:
                self._transition(
                    record_path,
                    record,
                    "compensation_failed",
                    compensation_errors=errors,
                )
                raise Problem(
                    503,
                    "conversation_saga_recovery_failed",
                    "Conversation recovery failed",
                    "A previous file rollback could not be compensated; retry after repairing storage.",
                )
            self._transition(
                record_path,
                record,
                "recovered_compensated",
                compensation_errors=[],
            )

    def delete_terminal_records(self, conversation_id: str) -> int:
        """Delete terminal Saga history for a conversation being deleted.

        Non-terminal and corrupt records are recovery evidence and are never
        removed here. Corruption or an I/O failure therefore blocks the caller
        before the conversation repository is changed.
        """
        removed = 0
        for record_path in sorted(self.root.glob("*/record.json")):
            if record_path.parent.is_symlink():
                raise Problem(
                    503,
                    "conversation_saga_journal_corrupt",
                    "Conversation recovery journal is corrupt",
                    "Conversation deletion cannot establish its data lifecycle until the Saga journal is repaired.",
                )
            try:
                record = self._read_record(record_path)
            except (OSError, ValueError, json.JSONDecodeError) as error:
                raise Problem(
                    503,
                    "conversation_saga_journal_corrupt",
                    "Conversation recovery journal is corrupt",
                    "Conversation deletion cannot establish its data lifecycle until the Saga journal is repaired.",
                ) from error
            if (
                record.get("conversation_id") != conversation_id
                or str(record.get("stage", "")) not in TERMINAL_STAGES
            ):
                continue
            try:
                shutil.rmtree(record_path.parent)
            except OSError as error:
                LOGGER.exception(
                    "conversation terminal Saga cleanup failed",
                    extra={"conversation_id": conversation_id},
                )
                raise Problem(
                    503,
                    "conversation_saga_cleanup_failed",
                    "Conversation recovery history cleanup failed",
                    "The terminal recovery history could not be removed; retry after repairing storage.",
                ) from error
            removed += 1
        return removed

    def execute(
        self,
        repository: ConversationRepository,
        conversation: ConversationData,
        target_messages: list[Any],
        steps: list[dict[str, Any]],
    ) -> tuple[bool, list[dict[str, Any]]]:
        """Rollback selected operations and persist truncation, or compensate."""
        saga_id = f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%f')}_{uuid.uuid4().hex[:8]}"
        saga_dir = self.root / saga_id
        saga_dir.mkdir(parents=False, exist_ok=False)
        record_path = saga_dir / "record.json"
        record: dict[str, Any] = {
            "version": 1,
            "id": saga_id,
            "conversation_id": conversation["id"],
            "stage": "snapshotting",
            "recovery_action": "restore_pre_truncate_files",
            "created_at": datetime.now(UTC).isoformat(),
            "updated_at": datetime.now(UTC).isoformat(),
            "steps": copy.deepcopy(steps),
            "target_messages": copy.deepcopy(target_messages),
            "target_message_count": len(target_messages),
            "path_snapshots": [],
            "manifest_snapshots": {},
            "rollback_results": [],
            "compensation_errors": [],
        }
        atomic_write_json(record_path, record)
        self._capture_pre_state(saga_dir, record)
        self._transition(record_path, record, "prepared")

        rollback_results: list[dict[str, Any]] = []
        for position, step in enumerate(steps):
            self._transition(record_path, record, "rolling_back", current_step=position)
            group_id = str(step["group_id"])
            operation_index = step.get("operation_index")
            try:
                if isinstance(operation_index, int) and not isinstance(operation_index, bool):
                    ok, message = self.backup_manager.rollback_operation(group_id, operation_index)
                else:
                    ok, message = self.backup_manager.rollback_operation(group_id)
            except Exception:
                LOGGER.exception(
                    "conversation Saga rollback step failed",
                    extra={"conversation_id": str(conversation["id"])},
                )
                ok, message = False, "Rollback failed; see correlated server telemetry."
            OPERATION_ROLLBACK_ATTEMPTS.labels(
                "conversation_saga", "success" if ok else "failure"
            ).inc()
            outcome = {"group_id": group_id, "success": bool(ok), "message": str(message)}
            rollback_results.append(outcome)
            record["rollback_results"] = copy.deepcopy(rollback_results)
            atomic_write_json(record_path, record)
            if not ok:
                errors = self._restore(saga_dir, record)
                stage = "rollback_failed_compensated" if not errors else "compensation_failed"
                self._transition(
                    record_path,
                    record,
                    stage,
                    compensation_errors=errors,
                )
                if errors:
                    outcome["message"] = f"{message}; compensation incomplete: {'; '.join(errors)}"
                return False, rollback_results

        self._transition(record_path, record, "files_rolled_back", current_step=None)
        target = copy.deepcopy(conversation)
        target["messages"] = copy.deepcopy(target_messages)
        self._transition(record_path, record, "persisting")
        try:
            repository.save(target)
        except Exception:
            LOGGER.exception(
                "conversation Saga repository save failed",
                extra={"conversation_id": str(conversation["id"])},
            )
            # A database driver may report a commit acknowledgement failure
            # after the transaction actually became durable. Read-after-error
            # prevents us from compensating files for an already-truncated
            # conversation.
            persisted: ConversationData | None = None
            with suppress(Exception):
                persisted = repository.get(str(conversation["id"]))
            if persisted is not None and persisted.get("messages", []) == target_messages:
                self._transition(
                    record_path,
                    record,
                    "committed",
                    persistence_warning="repository_commit_acknowledgement_uncertain",
                )
                return True, rollback_results
            errors = self._restore(saga_dir, record)
            stage = "persistence_failed_compensated" if not errors else "compensation_failed"
            self._transition(
                record_path,
                record,
                stage,
                persistence_error="repository_save_failed",
                compensation_errors=errors,
            )
            raise
        self._transition(record_path, record, "committed")
        return True, rollback_results

    def _capture_pre_state(self, saga_dir: Path, record: dict[str, Any]) -> None:
        manifests: dict[str, Any] = {}
        selected_paths: set[str] = set()
        for step in record["steps"]:
            group_id = str(step["group_id"])
            manifest = self.backup_manager.get_group_manifest(group_id)
            if not isinstance(manifest, dict):
                continue
            manifests[group_id] = copy.deepcopy(manifest)
            operation_index = step.get("operation_index")
            operations = manifest.get("operations", [])
            for operation in operations if isinstance(operations, list) else []:
                if not isinstance(operation, dict):
                    continue
                if isinstance(operation_index, int) and operation.get("index") != operation_index:
                    continue
                for key in ("path", "target_path", "after_path"):
                    value = operation.get(key)
                    if isinstance(value, str) and value:
                        target, relative = resolve_under_root(
                            self.backup_manager.library_dir,
                            value,
                            allow_root=False,
                        )
                        selected_paths.add(relative)

        record["manifest_snapshots"] = manifests
        snapshots: list[dict[str, Any]] = []
        with resource_lock(self.backup_manager.library_dir):
            for index, relative in enumerate(sorted(selected_paths)):
                target, normalized = resolve_under_root(
                    self.backup_manager.library_dir,
                    relative,
                    allow_root=False,
                )
                entry: dict[str, Any] = {"path": normalized, "existed": target.exists()}
                if target.exists():
                    if target.is_symlink():
                        raise ValueError("symbolic links cannot be captured for Saga compensation")
                    snapshot = saga_dir / "snapshots" / f"{index:04d}"
                    self._copy_path(target, snapshot)
                    entry["snapshot"] = snapshot.relative_to(saga_dir).as_posix()
                snapshots.append(entry)
        record["path_snapshots"] = snapshots
        atomic_write_json(saga_dir / "record.json", record)

    def _restore(self, saga_dir: Path, record: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        snapshots = record.get("path_snapshots", [])
        with resource_lock(self.backup_manager.library_dir):
            for entry in sorted(
                (item for item in snapshots if isinstance(item, dict)),
                key=lambda item: str(item.get("path", "")).count("/"),
            ):
                try:
                    target, _ = resolve_under_root(
                        self.backup_manager.library_dir,
                        str(entry["path"]),
                        allow_root=False,
                    )
                    self._remove_path(target)
                    if entry.get("existed"):
                        snapshot = saga_dir / str(entry["snapshot"])
                        if not snapshot.exists():
                            raise FileNotFoundError("Saga compensation snapshot is missing")
                        self._copy_path(snapshot, target)
                except Exception:
                    LOGGER.exception(
                        "conversation Saga path compensation failed",
                        extra={"conversation_id": str(record.get("conversation_id", ""))},
                    )
                    errors.append("path_snapshot_restore_failed")

        manifests = record.get("manifest_snapshots", {})
        if isinstance(manifests, dict):
            for group_id, manifest in manifests.items():
                try:
                    group_dir = Path(self.backup_manager.backup_dir) / str(group_id)
                    with resource_lock(group_dir):
                        atomic_write_json(group_dir / "manifest.json", manifest)
                except Exception:
                    LOGGER.exception(
                        "conversation Saga manifest compensation failed",
                        extra={
                            "conversation_id": str(record.get("conversation_id", "")),
                            "backup_group_id": str(group_id),
                        },
                    )
                    errors.append("backup_manifest_restore_failed")
        return errors

    @staticmethod
    def _copy_path(source: Path, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.is_file():
            shutil.copy2(source, destination)
        elif source.is_dir():
            shutil.copytree(source, destination)
        else:
            raise ValueError("unsupported Saga snapshot resource")

    @staticmethod
    def _remove_path(path: Path) -> None:
        if path.is_symlink() or path.is_file():
            path.unlink(missing_ok=True)
        elif path.is_dir():
            shutil.rmtree(path)

    @staticmethod
    def _read_record(path: Path) -> dict[str, Any]:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("invalid conversation Saga record")
        return value

    @classmethod
    def _transition(cls, path: Path, record: dict[str, Any], stage: str, **values: Any) -> None:
        record.update(values)
        record["stage"] = stage
        record["updated_at"] = datetime.now(UTC).isoformat()
        if stage in TERMINAL_STAGES:
            cls._compact_terminal_record(record)
        atomic_write_json(path, record)
        if stage in TERMINAL_STAGES:
            # Recovery payloads can be as large as the modified resources. Once
            # the Saga is terminal, retain only its compact decision/outcome
            # record and release data that can no longer be replayed.
            shutil.rmtree(path.parent / "snapshots", ignore_errors=True)

    @classmethod
    def _release_terminal_payload(cls, path: Path, record: dict[str, Any]) -> None:
        if cls._compact_terminal_record(record):
            atomic_write_json(path, record)
        # A previous process may have committed the compact record and crashed
        # before deleting the physical snapshots. Retrying is always safe.
        shutil.rmtree(path.parent / "snapshots", ignore_errors=True)

    @staticmethod
    def _compact_terminal_record(record: dict[str, Any]) -> bool:
        changed = False
        missing = object()
        target_messages = record.pop("target_messages", missing)
        if target_messages is not missing:
            changed = True
        if isinstance(target_messages, list) and "target_message_count" not in record:
            record["target_message_count"] = len(target_messages)
        if record.get("path_snapshots") != []:
            record["path_snapshots"] = []
            changed = True
        if record.get("manifest_snapshots") != {}:
            record["manifest_snapshots"] = {}
            changed = True
        if "recovery_payload_released_at" not in record:
            record["recovery_payload_released_at"] = datetime.now(UTC).isoformat()
            changed = True
        return changed
