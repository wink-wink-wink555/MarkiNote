from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import mock

from alembic.config import Config
from alembic.script import ScriptDirectory
from apps.api.scripts import migrate_conversations as migration_module
from apps.api.scripts.migrate_conversations import migrate

from markinote_api.modules.conversations.repository import (
    EXPECTED_SCHEMA_REVISION,
    Database,
    JsonConversationRepository,
    SqlConversationRepository,
)


def test_runtime_readiness_revision_matches_alembic_head():
    script = ScriptDirectory.from_config(Config("alembic.ini"))
    assert script.get_current_head() == EXPECTED_SCHEMA_REVISION


def test_repository_import_does_not_construct_application():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; "
                "import markinote_api.modules.conversations.repository; "
                "assert 'markinote_api.application' not in sys.modules"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_json_to_sql_migration_is_verified_and_idempotent():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source = JsonConversationRepository(root / "source")
        value = {
            "id": "conversation_1",
            "title": "Example",
            "created_at": "2026-07-18T00:00:00+00:00",
            "updated_at": "2026-07-18T00:00:00+00:00",
            "messages": [
                {"role": "system", "content": "system"},
                {"role": "user", "content": "hello", "_display_content": "hello"},
            ],
        }
        source.save(value)
        database = Database(f"sqlite:///{(root / 'target.db').as_posix()}", create_schema=True)
        try:
            target = SqlConversationRepository(database)
            first = migrate(source, target, apply=True)
            second = migrate(source, target, apply=True)
            assert first["success"] and second["success"]
            assert first["verified_count"] == second["verified_count"] == 1
            assert target.get("conversation_1")["messages"][1]["_display_content"] == "hello"
        finally:
            database.close()


def test_migration_reports_corrupt_source_instead_of_silently_skipping_it():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source = JsonConversationRepository(root / "source")
        (source.root / "broken.json").write_text("{not-json", encoding="utf-8")
        database = Database(f"sqlite:///{(root / 'target.db').as_posix()}", create_schema=True)
        try:
            report = migrate(source, SqlConversationRepository(database), apply=False)
            assert report["success"] is False
            assert report["source_file_count"] == 1
            assert report["errors"][0]["code"] == "invalid_conversation_json"
        finally:
            database.close()


def test_migration_does_not_overwrite_a_differing_destination_by_default():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source = JsonConversationRepository(root / "source")
        source.save(
            {
                "id": "conversation_1",
                "title": "source",
                "created_at": "2026-07-18T00:00:00+00:00",
                "updated_at": "2026-07-18T00:00:00+00:00",
                "messages": [],
            }
        )
        database = Database(f"sqlite:///{(root / 'target.db').as_posix()}", create_schema=True)
        target = SqlConversationRepository(database)
        target.save(
            {
                "id": "conversation_1",
                "title": "destination write",
                "created_at": "2026-07-18T00:00:00+00:00",
                "updated_at": "2026-07-18T01:00:00+00:00",
                "messages": [],
            }
        )
        try:
            report = migrate(source, target, apply=True)
            assert report["success"] is False
            assert report["errors"][0]["code"] == "destination_conflict"
            assert "destination differs" in report["errors"][0]["error"]
            assert target.get("conversation_1")["title"] == "destination write"
        finally:
            database.close()


def test_migration_report_never_reflects_unexpected_driver_errors() -> None:
    sentinel = "postgresql://user:SECRET@private-db/internal-path"
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source = JsonConversationRepository(root / "source")
        source.save(
            {
                "id": "conversation_1",
                "title": "source",
                "created_at": "2026-07-18T00:00:00+00:00",
                "updated_at": "2026-07-18T00:00:00+00:00",
                "messages": [],
            }
        )
        database = Database(f"sqlite:///{(root / 'target.db').as_posix()}", create_schema=True)
        target = SqlConversationRepository(database)
        try:
            with mock.patch.object(target, "get", side_effect=RuntimeError(sentinel)):
                report = migrate(source, target, apply=True)
            serialized = json.dumps(report)
            assert report["errors"][0]["code"] == "migration_record_failed"
            assert sentinel not in serialized
            assert "SECRET" not in serialized
        finally:
            database.close()


def test_migration_cli_startup_failure_is_identifier_free(monkeypatch, capsys, tmp_path: Path) -> None:
    sentinel = "postgresql://user:SECRET@private-db/internal-path"

    def fail_database(*_args, **_kwargs):
        raise RuntimeError(sentinel)

    monkeypatch.setattr(migration_module, "Database", fail_database)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "migrate_conversations.py",
            "--source",
            str(tmp_path / "source-private"),
            "--database-url",
            sentinel,
            "--report",
            str(tmp_path / "report-private.json"),
        ],
    )

    assert migration_module.main() == 2
    output = capsys.readouterr().out
    assert json.loads(output)["error_code"] == "migration_failed"
    assert sentinel not in output
    assert "SECRET" not in output
