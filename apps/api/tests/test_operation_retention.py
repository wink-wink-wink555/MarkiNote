from __future__ import annotations

import io
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import mock

from alembic import command
from alembic.config import Config
from apps.api.scripts.prune_operation_records import main, maintain_operation_records
from sqlalchemy import func, select

from markinote_api.modules.conversations.repository import (
    Database,
    OperationAuditRecord,
    ToolCommandRecord,
)
from markinote_api.modules.operations.journal import SqlCommandJournal

MAINTENANCE_TIME = datetime(2026, 7, 18, 12, 0, tzinfo=UTC)
OLD_TIME = MAINTENANCE_TIME - timedelta(days=120)


def _migrated_database(tmp_path: Path) -> str:
    url = f"sqlite:///{(tmp_path / 'operation-retention.db').as_posix()}"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    with mock.patch.dict(os.environ, {"MARKINOTE_DATABASE_URL": url}):
        command.upgrade(config, "head")
    return url


def _claim_and_finish(
    journal: SqlCommandJournal,
    command_id: str,
    result: dict[str, object],
) -> None:
    assert journal.claim(
        command_id,
        run_id=f"run-{command_id}",
        conversation_id=f"conversation-{command_id}",
        tool_name="write_file",
    ) == (True, None)
    assert journal.complete(command_id, result)


def _seed(url: str) -> None:
    database = Database(url)
    try:
        old = SqlCommandJournal(database, now=lambda: OLD_TIME)
        _claim_and_finish(old, "safe-command", {"result": "bounded result"})
        _claim_and_finish(
            old,
            "expired-backup-command",
            {"backup_group_id": "expired-group", "backup_info": {"operation_index": 1}},
        )
        _claim_and_finish(
            old,
            "live-backup-command",
            {"backup_group_id": "live-group", "backup_info": {"operation_index": 2}},
        )
        _claim_and_finish(
            old,
            "recovery-command",
            {
                "backup_group_id": "expired-group",
                "backup_info": {"recovery_required": True},
            },
        )
        assert old.claim(
            "running-command",
            run_id="running-run",
            conversation_id="running-conversation",
            tool_name="write_file",
        ) == (True, None)

        with database.session() as session, session.begin():
            for index, command_id in enumerate(
                (
                    None,
                    "safe-command",
                    "expired-backup-command",
                    "live-backup-command",
                    "recovery-command",
                )
            ):
                session.add(
                    OperationAuditRecord(
                        request_id=f"sensitive-request-{index}",
                        conversation_id="sensitive-conversation",
                        command_id=command_id,
                        action="write_file",
                        target="sensitive/path.md",
                        outcome="completed",
                        content_hash=None,
                        details={},
                        created_at=OLD_TIME,
                    )
                )
    finally:
        database.close()


def _counts(url: str) -> tuple[int, int]:
    database = Database(url)
    try:
        with database.session() as session:
            return (
                int(session.scalar(select(func.count()).select_from(ToolCommandRecord)) or 0),
                int(session.scalar(select(func.count()).select_from(OperationAuditRecord)) or 0),
            )
    finally:
        database.close()


def test_sql_retention_is_bounded_and_protects_running_recovery_and_live_backups(tmp_path: Path) -> None:
    url = _migrated_database(tmp_path)
    _seed(url)
    database = Database(url)
    try:
        journal = SqlCommandJournal(database)
        candidates, scanned, protected = journal.terminal_retention_candidates(
            before=MAINTENANCE_TIME - timedelta(days=30),
            limit=10,
            scan_limit=10,
            protected_backup_groups={"live-group"},
        )
        assert set(candidates) == {"safe-command", "expired-backup-command"}
        assert scanned == 4
        assert protected == 2
        assert journal.prune_terminal(
            before=MAINTENANCE_TIME - timedelta(days=30),
            limit=1,
            scan_limit=10,
            protected_backup_groups={"live-group"},
        ) == 1

        remaining = [
            value
            for value in (
                journal.inspect("safe-command"),
                journal.inspect("expired-backup-command"),
            )
            if value is not None
        ]
        assert len(remaining) == 1
        assert journal.inspect("running-command")["state"] == "running"
        assert journal.inspect("live-backup-command") is not None
        assert journal.inspect("recovery-command") is not None
    finally:
        database.close()


def test_retention_cli_defaults_to_dry_run_and_never_outputs_identifiers(tmp_path: Path) -> None:
    url = _migrated_database(tmp_path)
    _seed(url)
    backups = tmp_path / "backups"
    (backups / "live-group").mkdir(parents=True)
    (backups / "live-group" / "manifest.json").write_text("{}", encoding="utf-8")

    report = maintain_operation_records(
        url,
        backups_folder=str(backups),
        apply=False,
        command_retention_days=30,
        audit_retention_days=90,
        batch_size=10,
        scan_limit=20,
        now=lambda: MAINTENANCE_TIME,
    )
    assert report["success"] is True
    assert report["mode"] == "dry_run"
    assert report["command_candidate_count"] == 2
    assert report["command_protected_count"] == 2
    assert _counts(url) == (5, 5)
    encoded = json.dumps(report)
    for secret in ("safe-command", "live-group", "sensitive", url):
        assert secret not in encoded

    output = io.StringIO()
    exit_code = main(
        [
            "--database-url",
            url,
            "--backups-folder",
            str(backups),
            "--command-retention-days",
            "30",
            "--audit-retention-days",
            "90",
            "--batch-size",
            "10",
            "--scan-limit",
            "20",
            "--apply",
        ],
        stdout=output,
        now=lambda: MAINTENANCE_TIME,
    )
    applied = json.loads(output.getvalue())
    assert exit_code == 0
    assert applied["deleted_command_count"] == 2
    # The orphan audit plus audits whose commands expired are now removable.
    assert applied["deleted_audit_count"] == 3
    assert _counts(url) == (3, 2)
    for secret in ("safe-command", "live-group", "sensitive", url):
        assert secret not in output.getvalue()


def test_retention_cli_rejects_unsafe_bounds_without_echoing_values() -> None:
    output = io.StringIO()
    exit_code = main(
        [
            "--database-url",
            "postgresql://user:sentinel-password@db/markinote",
            "--command-retention-days",
            "90",
            "--audit-retention-days",
            "30",
        ],
        stdout=output,
        now=lambda: MAINTENANCE_TIME,
    )
    assert exit_code == 2
    assert "audit_retention_too_short" in output.getvalue()
    assert "sentinel-password" not in output.getvalue()


def test_retention_backup_index_failures_are_bounded_and_identifier_free(tmp_path: Path) -> None:
    backups = tmp_path / "backups"
    backups.mkdir()
    database_url = f"sqlite:///{(tmp_path / 'unused-secret-name.db').as_posix()}"

    with mock.patch(
        "apps.api.scripts.prune_operation_records.Path.iterdir",
        side_effect=PermissionError("SENTINEL_PRIVATE_MOUNT=C:/private/backups"),
    ):
        permission_report = maintain_operation_records(
            database_url,
            backups_folder=str(backups),
            apply=True,
            command_retention_days=30,
            audit_retention_days=90,
            batch_size=10,
            scan_limit=20,
            now=lambda: MAINTENANCE_TIME,
        )

    assert permission_report == {
        "success": False,
        "error_code": "unsafe_configuration",
        "message": "database or backup storage configuration is invalid",
    }
    assert "SENTINEL_PRIVATE_MOUNT" not in json.dumps(permission_report)
    assert database_url not in json.dumps(permission_report)

    for name in ("one", "two"):
        group = backups / name
        group.mkdir()
        (group / "manifest.json").write_text("{}", encoding="utf-8")
    with mock.patch(
        "apps.api.scripts.prune_operation_records.MAX_BACKUP_INDEX_ENTRIES",
        1,
    ):
        bounded_report = maintain_operation_records(
            database_url,
            backups_folder=str(backups),
            apply=True,
            command_retention_days=30,
            audit_retention_days=90,
            batch_size=10,
            scan_limit=20,
            now=lambda: MAINTENANCE_TIME,
        )
    assert bounded_report == permission_report


def test_audit_prune_rechecks_command_correlation_before_delete(tmp_path: Path) -> None:
    url = _migrated_database(tmp_path)
    database = Database(url)
    try:
        with database.session() as session, session.begin():
            audit = OperationAuditRecord(
                request_id="audit-race-request",
                conversation_id="audit-race-conversation",
                command_id="audit-race-command",
                action="write_file",
                target=None,
                outcome="completed",
                content_hash=None,
                details={},
                created_at=OLD_TIME,
            )
            session.add(audit)

        journal = SqlCommandJournal(database, now=lambda: MAINTENANCE_TIME)
        original_candidates = journal.audit_retention_candidates

        def insert_command_after_selection(*, before: datetime, limit: int = 1_000):
            candidates = original_candidates(before=before, limit=limit)
            assert journal.claim(
                "audit-race-command",
                run_id="audit-race-run",
                conversation_id="audit-race-conversation",
                tool_name="write_file",
            ) == (True, None)
            return candidates

        with mock.patch.object(
            journal,
            "audit_retention_candidates",
            side_effect=insert_command_after_selection,
        ):
            assert journal.prune_audit(before=MAINTENANCE_TIME - timedelta(days=90)) == 0

        with database.session() as session:
            assert session.scalar(select(func.count()).select_from(OperationAuditRecord)) == 1
            command = session.get(ToolCommandRecord, "audit-race-command")
            assert command is not None and command.state == "running"
    finally:
        database.close()
