"""Safely audit or prune terminal SQL agent-run journal rows.

Dry-run is the default. The command deliberately supports only the SQL
journal and emits one identifier-free JSON summary on stdout.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import NoReturn, TextIO

from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
API_SOURCE = REPOSITORY_ROOT / "apps" / "api" / "src"
sys.path.insert(0, str(REPOSITORY_ROOT))
sys.path.insert(0, str(API_SOURCE))

from markinote_api.modules.agent.run_journal import SqlAgentRunJournal  # noqa: E402
from markinote_api.modules.conversations.repository import (  # noqa: E402
    AgentRunRecord,
    Database,
)

DEFAULT_RETENTION_DAYS = 30
DEFAULT_BATCH_SIZE = 1_000
MAX_RETENTION_DAYS = 3_650
MAX_BATCH_SIZE = 10_000
TERMINAL_STATES = ("completed", "failed", "cancelled")


class CliArgumentError(ValueError):
    """An argument error that must be rendered as a safe JSON code."""


class JsonArgumentParser(argparse.ArgumentParser):
    """Keep invalid operational invocations machine-readable and secret-free."""

    def error(self, message: str) -> NoReturn:
        del message
        raise CliArgumentError


def _parser() -> argparse.ArgumentParser:
    parser = JsonArgumentParser(
        description=(
            "Audit or prune a single bounded batch of terminal SQL agent-run records. "
            "The default is dry-run."
        )
    )
    parser.add_argument(
        "--database-url",
        help="SQLAlchemy SQLite/PostgreSQL URL; MARKINOTE_DATABASE_URL is the fallback",
    )
    parser.add_argument(
        "--journal-backend",
        default="sql",
        help="only 'sql' is supported; 'json' is rejected explicitly",
    )
    parser.add_argument("--retention-days", type=int, default=DEFAULT_RETENTION_DAYS)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--apply", action="store_true", help="delete one bounded batch")
    return parser


def _error(code: str, message: str) -> dict[str, object]:
    return {"success": False, "error_code": code, "message": message}


def _validate_database_url(database_url: str) -> None:
    try:
        backend = make_url(database_url).get_backend_name()
    except (ArgumentError, ValueError) as error:
        raise CliArgumentError from error
    if backend not in {"sqlite", "postgresql"}:
        raise CliArgumentError


def _count_terminal_candidates(
    database: Database,
    *,
    before: datetime,
    limit: int,
) -> int:
    bounded_candidates = (
        select(AgentRunRecord.run_id)
        .where(
            AgentRunRecord.state.in_(TERMINAL_STATES),
            AgentRunRecord.finished_at.is_not(None),
            AgentRunRecord.finished_at < before,
        )
        .order_by(AgentRunRecord.finished_at, AgentRunRecord.run_id)
        .limit(limit)
        .subquery()
    )
    with database.session() as session:
        return int(
            session.execute(select(func.count()).select_from(bounded_candidates)).scalar_one()
        )


def maintain_agent_runs(
    database_url: str,
    *,
    apply: bool,
    retention_days: int,
    batch_size: int,
    now: Callable[[], datetime] | None = None,
) -> dict[str, object]:
    """Audit or delete one bounded batch without exposing row metadata."""
    if not 1 <= retention_days <= MAX_RETENTION_DAYS:
        return _error(
            "unsafe_retention_days",
            f"retention days must be between 1 and {MAX_RETENTION_DAYS}",
        )
    if not 1 <= batch_size <= MAX_BATCH_SIZE:
        return _error(
            "unsafe_batch_size",
            f"batch size must be between 1 and {MAX_BATCH_SIZE}",
        )
    if not database_url.strip():
        return _error("database_url_missing", "a database URL is required")
    try:
        _validate_database_url(database_url)
    except CliArgumentError:
        return _error(
            "unsupported_database_url",
            "only SQLite and PostgreSQL database URLs are supported",
        )

    current_time = (now or (lambda: datetime.now(UTC)))()
    current_time = (
        current_time.astimezone(UTC)
        if current_time.tzinfo is not None
        else current_time.replace(tzinfo=UTC)
    )
    cutoff = current_time - timedelta(days=retention_days)
    database: Database | None = None
    try:
        database = Database(database_url, create_schema=False)
        if not database.ready():
            return _error(
                "database_not_ready",
                "the database is unavailable or is not at the required schema revision",
            )

        journal = SqlAgentRunJournal(database)
        candidate_count = _count_terminal_candidates(
            database,
            before=cutoff,
            limit=batch_size,
        )
        deleted_count = (
            journal.prune_terminal(before=cutoff, limit=batch_size) if apply else 0
        )
        remaining_candidate_count = _count_terminal_candidates(
            database,
            before=cutoff,
            limit=batch_size,
        )
        return {
            "success": True,
            "mode": "apply" if apply else "dry_run",
            "cutoff": cutoff.isoformat(),
            "retention_days": retention_days,
            "batch_limit": batch_size,
            "candidate_count": candidate_count,
            "deleted_count": deleted_count,
            "remaining_candidate_count": remaining_candidate_count,
            "batch_saturated": candidate_count == batch_size,
        }
    except Exception:
        # Driver and SQL exception strings can echo credentials, URLs, row
        # identifiers or statement parameters. Never include them in output.
        return _error(
            "database_operation_failed",
            "the database operation failed; inspect protected service telemetry",
        )
    finally:
        if database is not None:
            with suppress(Exception):
                database.close()


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    stdout: TextIO | None = None,
    now: Callable[[], datetime] | None = None,
) -> int:
    output = stdout or sys.stdout
    environment = os.environ if environ is None else environ
    try:
        args = _parser().parse_args(argv)
    except CliArgumentError:
        report = _error("invalid_arguments", "the command arguments are invalid")
    else:
        backend = str(args.journal_backend).strip().lower()
        if backend == "json":
            report = _error(
                "json_journal_not_supported",
                "this command does not automate JSON journal cleanup; use the SQL journal",
            )
        elif backend != "sql":
            report = _error(
                "unsupported_journal_backend",
                "only the SQL journal backend is supported",
            )
        else:
            explicit_url = args.database_url
            database_url = (
                explicit_url
                if explicit_url is not None
                else environment.get("MARKINOTE_DATABASE_URL", "")
            )
            report = maintain_agent_runs(
                database_url,
                apply=bool(args.apply),
                retention_days=int(args.retention_days),
                batch_size=int(args.batch_size),
                now=now,
            )
    output.write(json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    output.write("\n")
    return 0 if report["success"] else 2


if __name__ == "__main__":
    sys.exit(main())
