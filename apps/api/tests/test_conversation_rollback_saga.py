from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from markinote_api.modules.conversations.repository import JsonConversationRepository
from markinote_api.modules.conversations.service import ConversationService
from markinote_api.modules.operations.backup import BackupManager
from markinote_api.platform.errors import Problem


def _tool_message(group_id: str, operation_index: int) -> dict[str, object]:
    return {
        "role": "tool",
        "content": "completed",
        "_tool_meta": {
            "backup_group_id": group_id,
            "backup_info": {"operation_index": operation_index},
        },
    }


def _modify(manager: BackupManager, group_id: str, relative: str, content: str) -> int:
    operation = manager.backup_before_modify(group_id, "write_file", relative)
    (manager.library_dir / relative).write_text(content, encoding="utf-8")
    manager.backup_after_modify(group_id, operation, relative)
    return operation


def _fixture():
    temporary = tempfile.TemporaryDirectory()
    root = Path(temporary.name)
    library = root / "library"
    library.mkdir()
    manager = BackupManager(root / "backups", library)
    repository = JsonConversationRepository(root / "conversations")
    service = ConversationService(repository, manager)
    return temporary, library, manager, repository, service


def _save_conversation(repository: JsonConversationRepository, messages: list[dict[str, object]]) -> None:
    repository.save(
        {
            "id": "conversation",
            "title": "Saga",
            "created_at": "2026-07-18T00:00:00+00:00",
            "updated_at": "2026-07-18T00:00:00+00:00",
            "messages": messages,
        }
    )


def _latest_saga(manager: BackupManager) -> dict[str, object]:
    records = sorted((manager.backup_dir / "conversation-sagas").glob("*/record.json"))
    return json.loads(records[-1].read_text(encoding="utf-8"))


def test_truncate_rolls_back_only_removed_operation_from_shared_group() -> None:
    temporary, library, manager, repository, service = _fixture()
    try:
        (library / "kept.md").write_text("kept-before", encoding="utf-8")
        (library / "removed.md").write_text("removed-before", encoding="utf-8")
        group = manager.create_operation_group("conversation")
        kept_operation = _modify(manager, group, "kept.md", "kept-after")
        removed_operation = _modify(manager, group, "removed.md", "removed-after")
        manager.complete_operation_group(group)
        _save_conversation(
            repository,
            [
                {"role": "system", "content": "system"},
                {"role": "user", "content": "keep"},
                _tool_message(group, kept_operation),
                {"role": "user", "content": "remove"},
                _tool_message(group, removed_operation),
            ],
        )

        result = service.truncate("conversation", 1, True)

        assert result["message"] == "Conversation truncated"
        assert (library / "kept.md").read_text(encoding="utf-8") == "kept-after"
        assert (library / "removed.md").read_text(encoding="utf-8") == "removed-before"
        assert len(repository.get("conversation")["messages"]) == 3
        manifest = manager.get_group_manifest(group)
        assert manifest["operations"][kept_operation]["rolled_back_at"] is None
        assert manifest["operations"][removed_operation]["rolled_back_at"] is not None
        record = _latest_saga(manager)
        assert record["stage"] == "committed"
        assert record["target_message_count"] == 3
        assert "target_messages" not in record
    finally:
        temporary.cleanup()


def test_truncate_treats_an_already_rolled_back_operation_as_idempotent() -> None:
    temporary, library, manager, repository, service = _fixture()
    try:
        document = library / "already-rolled-back.md"
        document.write_text("before", encoding="utf-8")
        group = manager.create_operation_group("conversation")
        operation = _modify(manager, group, document.name, "after")
        manager.complete_operation_group(group)
        original_messages = [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "remove"},
            _tool_message(group, operation),
        ]
        _save_conversation(repository, original_messages)
        assert manager.rollback_operation(group, operation)[0] is True
        assert document.read_text(encoding="utf-8") == "before"

        result = service.truncate("conversation", 0, True)

        assert result["committed"] is True
        assert result["message"] == "Conversation truncated"
        assert document.read_text(encoding="utf-8") == "before"
        assert repository.get("conversation")["messages"] == [{"role": "system", "content": "system"}]
    finally:
        temporary.cleanup()


def test_truncate_fails_closed_when_an_old_backup_is_no_longer_available() -> None:
    temporary, library, manager, repository, service = _fixture()
    try:
        document = library / "expired-backup.md"
        document.write_text("before", encoding="utf-8")
        group = manager.create_operation_group("conversation")
        operation = _modify(manager, group, document.name, "after")
        manager.complete_operation_group(group)
        original_messages = [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "remove"},
            _tool_message(group, operation),
        ]
        _save_conversation(repository, original_messages)
        shutil.rmtree(manager.backup_dir / group)

        result = service.truncate("conversation", 0, True)

        assert result["committed"] is False
        assert result["rollback_results"] == [
            {"group_id": group, "success": False, "message": "备份不存在"}
        ]
        assert document.read_text(encoding="utf-8") == "after"
        assert repository.get("conversation")["messages"] == original_messages
    finally:
        temporary.cleanup()


def test_any_rollback_failure_keeps_conversation_and_compensates_prior_steps() -> None:
    temporary, library, manager, repository, service = _fixture()
    try:
        groups: list[tuple[str, int, str]] = []
        for name in ("first.md", "second.md"):
            (library / name).write_text(f"{name}-before", encoding="utf-8")
            group = manager.create_operation_group("conversation")
            operation = _modify(manager, group, name, f"{name}-after")
            manager.complete_operation_group(group)
            groups.append((group, operation, name))
        original_messages = [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "remove"},
            _tool_message(groups[0][0], groups[0][1]),
            _tool_message(groups[1][0], groups[1][1]),
        ]
        _save_conversation(repository, original_messages)
        real_rollback = manager.rollback_operation

        def fail_after_one_success(group_id: str, operation_index: int | None = None):
            if group_id == groups[0][0]:
                return False, "injected rollback failure"
            return real_rollback(group_id, operation_index)

        with mock.patch.object(manager, "rollback_operation", side_effect=fail_after_one_success):
            result = service.truncate("conversation", 0, True)

        assert result["message"].startswith("Conversation was not truncated")
        assert repository.get("conversation")["messages"] == original_messages
        for _, _, name in groups:
            assert (library / name).read_text(encoding="utf-8") == f"{name}-after"
        record = _latest_saga(manager)
        assert record["stage"] == "rollback_failed_compensated"
        assert record["target_message_count"] == 1
        assert "target_messages" not in record

        retry = service.truncate("conversation", 0, True)
        assert retry["message"] == "Conversation truncated"
        for _, _, name in groups:
            assert (library / name).read_text(encoding="utf-8") == f"{name}-before"
    finally:
        temporary.cleanup()


def test_repository_failure_after_file_rollback_is_compensated_and_retryable() -> None:
    temporary, library, manager, repository, service = _fixture()
    try:
        document = library / "note.md"
        document.write_text("before", encoding="utf-8")
        group = manager.create_operation_group("conversation")
        operation = _modify(manager, group, "note.md", "after")
        manager.complete_operation_group(group)
        original_messages = [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "remove"},
            _tool_message(group, operation),
        ]
        _save_conversation(repository, original_messages)

        with (
            mock.patch.object(repository, "save", side_effect=OSError("injected save failure")),
            pytest.raises(OSError, match="injected save failure"),
        ):
            service.truncate("conversation", 0, True)

        assert document.read_text(encoding="utf-8") == "after"
        assert repository.get("conversation")["messages"] == original_messages
        assert manager.get_group_manifest(group)["operations"][operation]["rolled_back_at"] is None
        record = _latest_saga(manager)
        assert record["stage"] == "persistence_failed_compensated"
        assert record["recovery_action"] == "restore_pre_truncate_files"
        assert record["persistence_error"] == "repository_save_failed"
        assert record["target_message_count"] == 1
        assert "target_messages" not in record
        assert "injected save failure" not in json.dumps(record)

        assert service.truncate("conversation", 0, True)["message"] == "Conversation truncated"
        assert document.read_text(encoding="utf-8") == "before"
    finally:
        temporary.cleanup()


def test_save_acknowledgement_failure_after_commit_does_not_reverse_files() -> None:
    temporary, library, manager, repository, service = _fixture()
    try:
        document = library / "note.md"
        document.write_text("before", encoding="utf-8")
        group = manager.create_operation_group("conversation")
        operation = _modify(manager, group, "note.md", "after")
        manager.complete_operation_group(group)
        _save_conversation(
            repository,
            [
                {"role": "system", "content": "system"},
                {"role": "user", "content": "remove"},
                _tool_message(group, operation),
            ],
        )
        actual_save = repository.save

        def committed_but_unacknowledged(value):
            actual_save(value)
            raise OSError("commit acknowledgement lost")

        with mock.patch.object(repository, "save", side_effect=committed_but_unacknowledged):
            result = service.truncate("conversation", 0, True)

        assert result["message"] == "Conversation truncated"
        assert document.read_text(encoding="utf-8") == "before"
        assert len(repository.get("conversation")["messages"]) == 1
        record = _latest_saga(manager)
        assert record["stage"] == "committed"
        assert record["persistence_warning"] == "repository_commit_acknowledgement_uncertain"
        assert record["target_message_count"] == 1
        assert "target_messages" not in record
        assert "acknowledgement lost" not in json.dumps(record)
    finally:
        temporary.cleanup()


def test_incomplete_compensation_is_deterministically_recovered_on_retry() -> None:
    temporary, library, manager, repository, service = _fixture()
    try:
        document = library / "note.md"
        document.write_text("before", encoding="utf-8")
        group = manager.create_operation_group("conversation")
        operation = _modify(manager, group, "note.md", "after")
        manager.complete_operation_group(group)
        original_messages = [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "remove"},
            _tool_message(group, operation),
        ]
        _save_conversation(repository, original_messages)

        with (
            mock.patch.object(repository, "save", side_effect=OSError("crash after rollback")),
            mock.patch.object(
                service.rollback_sagas,
                "_restore",
                return_value=["injected compensation interruption"],
            ),
            pytest.raises(OSError, match="crash after rollback"),
        ):
            service.truncate("conversation", 0, True)

        assert document.read_text(encoding="utf-8") == "before"
        assert repository.get("conversation")["messages"] == original_messages
        recovery_record = _latest_saga(manager)
        assert recovery_record["stage"] == "compensation_failed"
        assert recovery_record["target_messages"] == [
            {"role": "system", "content": "system"}
        ]
        assert recovery_record["path_snapshots"]
        assert recovery_record["manifest_snapshots"]

        # Recovery first restores the post-tool file + manifest state from the
        # durable Saga snapshot, then the fresh attempt rolls it back again.
        assert service.truncate("conversation", 0, True)["message"] == "Conversation truncated"
        assert document.read_text(encoding="utf-8") == "before"
        records = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in sorted((manager.backup_dir / "conversation-sagas").glob("*/record.json"))
        ]
        stages = [record["stage"] for record in records]
        assert "recovered_compensated" in stages
        assert "committed" in stages
        assert all("target_messages" not in record for record in records)
    finally:
        temporary.cleanup()


def test_recover_compacts_legacy_terminal_record_and_retries_snapshot_cleanup() -> None:
    temporary, _, manager, repository, service = _fixture()
    try:
        saga_dir = manager.backup_dir / "conversation-sagas" / "legacy-terminal"
        snapshots = saga_dir / "snapshots"
        snapshots.mkdir(parents=True)
        (snapshots / "orphaned-payload").write_text("file snapshot", encoding="utf-8")
        record_path = saga_dir / "record.json"
        record_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "id": "legacy-terminal",
                    "conversation_id": "conversation",
                    "stage": "committed",
                    "target_messages": [
                        {"role": "user", "content": "private legacy conversation text"}
                    ],
                    "path_snapshots": [],
                    "manifest_snapshots": {},
                }
            ),
            encoding="utf-8",
        )

        service.rollback_sagas.recover(repository, "conversation")

        compacted_text = record_path.read_text(encoding="utf-8")
        compacted = json.loads(compacted_text)
        assert compacted["stage"] == "committed"
        assert compacted["target_message_count"] == 1
        assert "target_messages" not in compacted
        assert "private legacy conversation text" not in compacted_text
        assert not snapshots.exists()
    finally:
        temporary.cleanup()


def test_delete_removes_only_matching_terminal_sagas() -> None:
    temporary, _, manager, repository, service = _fixture()
    try:
        _save_conversation(repository, [{"role": "system", "content": "system"}])
        saga_root = manager.backup_dir / "conversation-sagas"

        terminal = saga_root / "matching-terminal"
        terminal.mkdir()
        (terminal / "record.json").write_text(
            json.dumps(
                {
                    "conversation_id": "conversation",
                    "stage": "committed",
                    "target_messages": [{"role": "user", "content": "terminal text"}],
                }
            ),
            encoding="utf-8",
        )

        unrelated = saga_root / "unrelated-terminal"
        unrelated.mkdir()
        (unrelated / "record.json").write_text(
            json.dumps(
                {
                    "conversation_id": "another-conversation",
                    "stage": "committed",
                    "target_messages": [{"role": "user", "content": "other text"}],
                }
            ),
            encoding="utf-8",
        )

        assert service.delete("conversation") == 0

        assert repository.get("conversation") is None
        assert not terminal.exists()
        assert unrelated.is_dir()
    finally:
        temporary.cleanup()


def test_delete_blocks_and_preserves_saga_that_still_requires_recovery() -> None:
    temporary, _, manager, repository, service = _fixture()
    try:
        messages = [{"role": "system", "content": "system"}]
        _save_conversation(repository, messages)
        recovery_required = (
            manager.backup_dir / "conversation-sagas" / "matching-recovery-required"
        )
        recovery_required.mkdir()
        record_path = recovery_required / "record.json"
        record_path.write_text(
            json.dumps(
                {
                    "conversation_id": "conversation",
                    "stage": "compensation_failed",
                    "target_messages": [
                        {"role": "user", "content": "recovery evidence"}
                    ],
                    "path_snapshots": [
                        {
                            "path": "note.md",
                            "existed": True,
                            "snapshot": "snapshots/missing",
                        }
                    ],
                    "manifest_snapshots": {},
                }
            ),
            encoding="utf-8",
        )

        with pytest.raises(Problem) as captured:
            service.delete("conversation")

        assert captured.value.code == "conversation_saga_recovery_failed"
        assert repository.get("conversation")["messages"] == messages
        retained = json.loads(record_path.read_text(encoding="utf-8"))
        assert retained["stage"] == "compensation_failed"
        assert retained["target_messages"] == [
            {"role": "user", "content": "recovery evidence"}
        ]
        assert retained["path_snapshots"]
    finally:
        temporary.cleanup()


def test_terminal_saga_cleanup_failure_leaves_conversation_unchanged() -> None:
    temporary, _, manager, repository, service = _fixture()
    try:
        messages = [{"role": "system", "content": "system"}]
        _save_conversation(repository, messages)
        terminal = manager.backup_dir / "conversation-sagas" / "terminal"
        terminal.mkdir()
        (terminal / "record.json").write_text(
            json.dumps(
                {
                    "conversation_id": "conversation",
                    "stage": "committed",
                    "target_messages": [{"role": "user", "content": "private"}],
                }
            ),
            encoding="utf-8",
        )

        with (
            mock.patch.object(
                service.rollback_sagas,
                "delete_terminal_records",
                side_effect=Problem(
                    503,
                    "conversation_saga_cleanup_failed",
                    "Conversation recovery history cleanup failed",
                    "injected cleanup failure",
                ),
            ),
            pytest.raises(Problem) as captured,
        ):
            service.delete("conversation")

        assert captured.value.code == "conversation_saga_cleanup_failed"
        assert repository.get("conversation")["messages"] == messages
        assert terminal.is_dir()
    finally:
        temporary.cleanup()
