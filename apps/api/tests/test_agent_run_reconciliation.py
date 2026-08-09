from __future__ import annotations

import io
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import mock

import pytest
from alembic import command
from alembic.config import Config
from apps.api.scripts.reconcile_agent_runs import main as reconcile_main
from fastapi.testclient import TestClient
from pydantic import ValidationError

from markinote_api.application import create_application
from markinote_api.config import Settings
from markinote_api.modules.agent.run_journal import (
    PROCESS_RESTARTED_ERROR_CODE,
    JsonAgentRunJournal,
    SqlAgentRunJournal,
)
from markinote_api.modules.conversations.repository import Database


class MutableClock:
    def __init__(self) -> None:
        self.value = datetime(2026, 7, 18, 8, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **values: float) -> None:
        self.value += timedelta(**values)


def _seed_and_exercise_reconciliation(
    journal: JsonAgentRunJournal | SqlAgentRunJournal,
    clock: MutableClock,
) -> None:
    for index in range(3):
        assert journal.start(
            run_id=f"running-{index}",
            request_id=f"request-{index}",
            provider="deepseek",
            model="deepseek-v4-flash",
        )
        clock.advance(seconds=1)

    assert journal.start(
        run_id="already-terminal",
        request_id="terminal-request",
        provider="deepseek",
        model="deepseek-v4-flash",
    )
    assert journal.finish("already-terminal", "terminal-request", "completed")
    terminal_before = journal.inspect("already-terminal", "terminal-request")

    # Dry-run is read-only and reports no more than the requested batch.
    assert journal.reconcile_running(limit=2) == 2
    for index in range(3):
        assert journal.inspect(f"running-{index}", f"request-{index}")["state"] == "running"

    clock.advance(seconds=1)
    assert journal.reconcile_running(limit=2, apply=True) == 2
    for index in range(2):
        record = journal.inspect(f"running-{index}", f"request-{index}")
        assert record is not None
        assert record["state"] == "failed"
        assert record["error_code"] == PROCESS_RESTARTED_ERROR_CODE
        assert record["finished_at"] == record["updated_at"]
    assert journal.inspect("running-2", "request-2")["state"] == "running"

    # A second bounded invocation handles only the remainder; completed rows
    # are immutable and subsequent runs are idempotent.
    assert journal.reconcile_running(limit=2, apply=True) == 1
    assert journal.reconcile_running(limit=2, apply=True) == 0
    assert journal.reconcile_running(limit=2) == 0
    assert journal.inspect("already-terminal", "terminal-request") == terminal_before


def test_json_reconciliation_is_bounded_idempotent_and_terminal_fenced(tmp_path: Path) -> None:
    clock = MutableClock()
    journal = JsonAgentRunJournal(tmp_path, now=clock)

    _seed_and_exercise_reconciliation(journal, clock)

    serialized = journal.path.read_text(encoding="utf-8")
    assert "process_restarted" in serialized
    assert "exception" not in serialized
    assert "prompt" not in serialized
    assert "api_key" not in serialized


def test_sql_reconciliation_is_bounded_idempotent_and_terminal_fenced(tmp_path: Path) -> None:
    clock = MutableClock()
    database = Database(
        f"sqlite:///{(tmp_path / 'agent-reconcile.db').as_posix()}",
        create_schema=True,
    )
    try:
        _seed_and_exercise_reconciliation(SqlAgentRunJournal(database, now=clock), clock)
    finally:
        database.close()


@pytest.mark.parametrize("limit", [0, 10_001])
def test_reconciliation_rejects_an_unbounded_limit(tmp_path: Path, limit: int) -> None:
    with pytest.raises(ValueError, match="between 1 and 10000"):
        JsonAgentRunJournal(tmp_path).reconcile_running(limit=limit)

    database = Database(
        f"sqlite:///{(tmp_path / f'bad-limit-{limit}.db').as_posix()}",
        create_schema=True,
    )
    try:
        with pytest.raises(ValueError, match="between 1 and 10000"):
            SqlAgentRunJournal(database).reconcile_running(limit=limit)
    finally:
        database.close()


def _application_settings(root: Path, backend: str, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "environment": "test",
        "library_folder": root / "library",
        "conversations_folder": root / "conversations",
        "backups_folder": root / "backups",
        "trash_folder": root / "trash",
        "conversation_backend": backend,
        "database_url": f"sqlite:///{(root / 'application.db').as_posix()}",
        "auto_create_database": True,
        "serve_web_dist": False,
        "json_logs": False,
        "agent_run_reconcile_on_startup": True,
        "agent_run_single_writer": True,
        "agent_run_reconcile_limit": 1,
    }
    values.update(overrides)
    return Settings(**values)


@pytest.mark.parametrize("backend", ["json", "database"])
def test_lifespan_reconciles_one_batch_only_for_an_attested_sole_writer(
    tmp_path: Path,
    backend: str,
) -> None:
    root = tmp_path / backend
    root.mkdir(parents=True)
    settings = _application_settings(root, backend)
    if backend == "database":
        seed_database = Database(settings.database_url, create_schema=True)
        try:
            seed_journal = SqlAgentRunJournal(seed_database)
            assert seed_journal.start(
                run_id="stranded-1",
                request_id="request-1",
                provider="deepseek",
                model="deepseek-v4-flash",
            )
            assert seed_journal.start(
                run_id="stranded-2",
                request_id="request-2",
                provider="deepseek",
                model="deepseek-v4-flash",
            )
        finally:
            seed_database.close()
    else:
        seed_journal = JsonAgentRunJournal(settings.backups_folder)
        assert seed_journal.start(
            run_id="stranded-1",
            request_id="request-1",
            provider="deepseek",
            model="deepseek-v4-flash",
        )
        assert seed_journal.start(
            run_id="stranded-2",
            request_id="request-2",
            provider="deepseek",
            model="deepseek-v4-flash",
        )

    application = create_application(settings)
    with TestClient(application):
        assert application.state.agent_run_reconciled_count == 1
        states = {
            application.state.agent_run_journal.inspect("stranded-1", "request-1")["state"],
            application.state.agent_run_journal.inspect("stranded-2", "request-2")["state"],
        }
        assert states == {"failed", "running"}
        failed = application.state.agent_run_journal.inspect("stranded-1", "request-1")
        assert failed["error_code"] == PROCESS_RESTARTED_ERROR_CODE


def test_startup_reconciliation_requires_an_explicit_single_writer_acknowledgement() -> None:
    with pytest.raises(ValidationError, match="single-writer acknowledgement"):
        Settings(agent_run_reconcile_on_startup=True, agent_run_single_writer=False)

    settings = Settings()
    assert not settings.agent_run_reconcile_on_startup
    assert not settings.agent_run_single_writer


def test_startup_reconciliation_fails_closed_without_echoing_adapter_errors(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "startup-failure"
    settings = _application_settings(root, "json")
    application = create_application(settings)
    with (
        mock.patch.object(
            application.state.agent_run_journal,
            "reconcile_running",
            side_effect=OSError("api_key=never-emit-this adapter path"),
        ),
        pytest.raises(RuntimeError) as raised,
        TestClient(application),
    ):
        pass

    assert str(raised.value) == "agent run startup reconciliation failed"
    captured = capsys.readouterr()
    assert "never-emit-this" not in captured.out
    assert "never-emit-this" not in captured.err


def test_json_cli_is_dry_run_by_default_and_requires_apply_confirmation(tmp_path: Path) -> None:
    journal = JsonAgentRunJournal(tmp_path)
    assert journal.start(
        run_id="sensitive-run-id",
        request_id="sensitive-request-id",
        provider="sensitive-provider",
        model="sensitive-model",
    )

    dry_run_output = io.StringIO()
    assert (
        reconcile_main(
            ["--journal-backend", "json", "--backups-folder", str(tmp_path)],
            environ={},
            stdout=dry_run_output,
        )
        == 0
    )
    dry_run = json.loads(dry_run_output.getvalue())
    assert dry_run["mode"] == "dry_run"
    assert dry_run["candidate_count"] == 1
    assert dry_run["reconciled_count"] == 0
    assert journal.inspect("sensitive-run-id", "sensitive-request-id")["state"] == "running"

    rejected_output = io.StringIO()
    assert (
        reconcile_main(
            [
                "--journal-backend",
                "json",
                "--backups-folder",
                str(tmp_path),
                "--apply",
            ],
            environ={},
            stdout=rejected_output,
        )
        == 2
    )
    assert json.loads(rejected_output.getvalue())["error_code"] == ("single_writer_confirmation_required")

    apply_output = io.StringIO()
    assert (
        reconcile_main(
            [
                "--journal-backend",
                "json",
                "--backups-folder",
                str(tmp_path),
                "--apply",
                "--confirm-single-writer",
            ],
            environ={},
            stdout=apply_output,
        )
        == 0
    )
    report = json.loads(apply_output.getvalue())
    assert report["reconciled_count"] == 1
    assert report["remaining_candidate_count"] == 0
    assert journal.inspect("sensitive-run-id", "sensitive-request-id")["error_code"] == (PROCESS_RESTARTED_ERROR_CODE)

    combined_output = dry_run_output.getvalue() + rejected_output.getvalue() + apply_output.getvalue()
    for forbidden in (
        str(tmp_path),
        "sensitive-run-id",
        "sensitive-request-id",
        "sensitive-provider",
        "sensitive-model",
        "run_id",
        "request_id",
        "provider",
        "model",
    ):
        assert forbidden not in combined_output


def _migrated_database(tmp_path: Path) -> str:
    url = f"sqlite:///{(tmp_path / 'reconcile-cli.db').as_posix()}"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    with mock.patch.dict(os.environ, {"MARKINOTE_DATABASE_URL": url}):
        command.upgrade(config, "head")
    return url


def test_database_cli_uses_environment_and_reconciles_one_bounded_batch(tmp_path: Path) -> None:
    url = _migrated_database(tmp_path)
    database = Database(url)
    try:
        journal = SqlAgentRunJournal(database)
        for index in range(2):
            assert journal.start(
                run_id=f"database-sensitive-{index}",
                request_id=f"database-request-{index}",
                provider="sensitive-provider",
                model="sensitive-model",
            )
    finally:
        database.close()

    output = io.StringIO()
    assert (
        reconcile_main(
            ["--batch-size", "1", "--apply", "--confirm-single-writer"],
            environ={
                "MARKINOTE_CONVERSATION_BACKEND": "database",
                "MARKINOTE_DATABASE_URL": url,
            },
            stdout=output,
        )
        == 0
    )
    report = json.loads(output.getvalue())
    assert report["journal_backend"] == "database"
    assert report["candidate_count"] == 1
    assert report["reconciled_count"] == 1
    assert report["remaining_candidate_count"] == 1
    assert report["batch_saturated"] is True
    assert url not in output.getvalue()
    assert "database-sensitive" not in output.getvalue()


@pytest.mark.parametrize(
    ("arguments", "error_code"),
    [
        (["--batch-size", "0"], "unsafe_batch_size"),
        (["--journal-backend", "filesystem"], "unsupported_journal_backend"),
        (["--unknown", "credential-value"], "invalid_arguments"),
        (
            [
                "--journal-backend",
                "database",
                "--database-url",
                "mysql://operator:super-secret@database/markinote",
            ],
            "unsupported_database_url",
        ),
    ],
)
def test_reconcile_cli_rejects_unsafe_inputs_without_echoing_them(
    arguments: list[str],
    error_code: str,
) -> None:
    output = io.StringIO()
    assert reconcile_main(arguments, environ={}, stdout=output) == 2
    assert json.loads(output.getvalue())["error_code"] == error_code
    assert "credential-value" not in output.getvalue()
    assert "super-secret" not in output.getvalue()
    assert "mysql://" not in output.getvalue()
