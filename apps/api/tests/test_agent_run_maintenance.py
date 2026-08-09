from __future__ import annotations

import io
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from unittest import mock

import pytest
from alembic import command
from alembic.config import Config
from apps.api.scripts.prune_agent_runs import main, maintain_agent_runs

from markinote_api.modules.agent.run_journal import SqlAgentRunJournal
from markinote_api.modules.conversations.repository import AgentRunRecord, Database

MAINTENANCE_TIME = datetime(2026, 7, 18, 12, 0, tzinfo=UTC)
CUTOFF_TIME = datetime(2026, 7, 11, 12, 0, tzinfo=UTC)


def _migrated_database(tmp_path: Path) -> str:
    url = f"sqlite:///{(tmp_path / 'agent-run-maintenance.db').as_posix()}"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    with mock.patch.dict(os.environ, {"MARKINOTE_DATABASE_URL": url}):
        command.upgrade(config, "head")
    return url


def _seed_records(url: str) -> None:
    database = Database(url)
    old_time = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
    exact_cutoff = CUTOFF_TIME
    recent_time = datetime(2026, 7, 17, 12, 0, tzinfo=UTC)
    try:
        old_journal = SqlAgentRunJournal(database, now=lambda: old_time)
        for index, state in enumerate(("completed", "failed", "cancelled"), start=1):
            run_id = f"sensitive-old-run-{index}"
            request_id = f"sensitive-old-request-{index}"
            assert old_journal.start(
                run_id=run_id,
                request_id=request_id,
                provider="sensitive-provider",
                model="sensitive-model",
            )
            assert old_journal.finish(run_id, request_id, state)

        assert old_journal.start(
            run_id="stranded-running",
            request_id="stranded-request",
            provider="sensitive-provider",
            model="sensitive-model",
        )

        boundary_journal = SqlAgentRunJournal(database, now=lambda: exact_cutoff)
        assert boundary_journal.start(
            run_id="boundary-run",
            request_id="boundary-request",
            provider="sensitive-provider",
            model="sensitive-model",
        )
        assert boundary_journal.finish("boundary-run", "boundary-request", "completed")

        recent_journal = SqlAgentRunJournal(database, now=lambda: recent_time)
        assert recent_journal.start(
            run_id="recent-run",
            request_id="recent-request",
            provider="sensitive-provider",
            model="sensitive-model",
        )
        assert recent_journal.finish("recent-run", "recent-request", "completed")
    finally:
        database.close()


def _states(url: str) -> list[str]:
    database = Database(url)
    try:
        with database.session() as session:
            return [record.state for record in session.query(AgentRunRecord).all()]
    finally:
        database.close()


def test_dry_run_is_default_and_apply_prunes_one_terminal_batch_only(tmp_path: Path) -> None:
    url = _migrated_database(tmp_path)
    _seed_records(url)

    dry_run = maintain_agent_runs(
        url,
        apply=False,
        retention_days=7,
        batch_size=2,
        now=lambda: MAINTENANCE_TIME,
    )
    assert dry_run == {
        "success": True,
        "mode": "dry_run",
        "cutoff": CUTOFF_TIME.isoformat(),
        "retention_days": 7,
        "batch_limit": 2,
        "candidate_count": 2,
        "deleted_count": 0,
        "remaining_candidate_count": 2,
        "batch_saturated": True,
    }
    assert len(_states(url)) == 6

    applied = maintain_agent_runs(
        url,
        apply=True,
        retention_days=7,
        batch_size=2,
        now=lambda: MAINTENANCE_TIME,
    )
    assert applied["candidate_count"] == 2
    assert applied["deleted_count"] == 2
    assert applied["remaining_candidate_count"] == 1
    # One old terminal row remains because every invocation is bounded. A
    # running row, a row exactly at cutoff, and a recent row also remain.
    assert sorted(_states(url)) == ["cancelled", "completed", "completed", "running"]


def test_cli_reads_environment_and_emits_only_an_identifier_free_summary(tmp_path: Path) -> None:
    url = _migrated_database(tmp_path)
    _seed_records(url)
    output = io.StringIO()

    exit_code = main(
        ["--retention-days", "7", "--batch-size", "2"],
        environ={"MARKINOTE_DATABASE_URL": url},
        stdout=output,
        now=lambda: MAINTENANCE_TIME,
    )

    assert exit_code == 0
    report = json.loads(output.getvalue())
    assert report["mode"] == "dry_run"
    assert report["candidate_count"] == 2
    assert report["deleted_count"] == 0
    serialized = output.getvalue()
    for forbidden in (
        url,
        "sensitive-old-run",
        "sensitive-old-request",
        "stranded-running",
        "sensitive-provider",
        "sensitive-model",
        "run_id",
        "request_id",
        "conversation_id",
        "provider",
        "model",
    ):
        assert forbidden not in serialized


@pytest.mark.parametrize(
    ("arguments", "environment", "error_code"),
    [
        ([], {}, "database_url_missing"),
        (["--retention-days", "0"], {}, "unsafe_retention_days"),
        (["--retention-days", "3651"], {}, "unsafe_retention_days"),
        (["--batch-size", "0"], {}, "unsafe_batch_size"),
        (["--batch-size", "10001"], {}, "unsafe_batch_size"),
        (["--journal-backend", "json"], {}, "json_journal_not_supported"),
        (["--journal-backend", "filesystem"], {}, "unsupported_journal_backend"),
        (["--unknown", "credential-value"], {}, "invalid_arguments"),
        (
            ["--database-url", "mysql://operator:super-secret@database/markinote"],
            {},
            "unsupported_database_url",
        ),
    ],
)
def test_cli_rejects_unsafe_or_unsupported_inputs_without_echoing_them(
    arguments: list[str],
    environment: dict[str, str],
    error_code: str,
) -> None:
    output = io.StringIO()
    exit_code = main(arguments, environ=environment, stdout=output)

    assert exit_code == 2
    assert json.loads(output.getvalue())["error_code"] == error_code
    assert "credential-value" not in output.getvalue()
    assert "super-secret" not in output.getvalue()
    assert "mysql://" not in output.getvalue()


def test_explicit_empty_database_url_fails_closed_instead_of_using_environment() -> None:
    output = io.StringIO()
    exit_code = main(
        ["--database-url", ""],
        environ={"MARKINOTE_DATABASE_URL": "sqlite:///must-not-be-used.db"},
        stdout=output,
    )

    assert exit_code == 2
    assert json.loads(output.getvalue())["error_code"] == "database_url_missing"
    assert "must-not-be-used" not in output.getvalue()
