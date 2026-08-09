"""Safely audit or reconcile stranded agent runs for a sole API writer.

Dry-run is the default. Applying reconciliation requires an explicit
``--confirm-single-writer`` acknowledgement because a second live API process
could otherwise have legitimate ownership of a row that still says running.
Only identifier-free counts and stable error codes are emitted.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import NoReturn, TextIO

from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
API_SOURCE = REPOSITORY_ROOT / "apps" / "api" / "src"
sys.path.insert(0, str(REPOSITORY_ROOT))
sys.path.insert(0, str(API_SOURCE))

from markinote_api.modules.agent.ports import AgentRunJournal  # noqa: E402
from markinote_api.modules.agent.run_journal import (  # noqa: E402
    JsonAgentRunJournal,
    SqlAgentRunJournal,
)
from markinote_api.modules.conversations.repository import Database  # noqa: E402

DEFAULT_BATCH_SIZE = 1_000
MAX_BATCH_SIZE = 10_000
SUPPORTED_BACKENDS = {"json", "database"}


class CliArgumentError(ValueError):
    """An argument error rendered only as a stable JSON code."""


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        del message
        raise CliArgumentError


def _parser() -> argparse.ArgumentParser:
    parser = JsonArgumentParser(
        description=("Audit or reconcile one bounded batch of running agent-run records. The default is dry-run.")
    )
    parser.add_argument(
        "--journal-backend",
        help="'json' or 'database'; MARKINOTE_CONVERSATION_BACKEND is the fallback",
    )
    parser.add_argument(
        "--database-url",
        help="SQLite/PostgreSQL URL; MARKINOTE_DATABASE_URL is the fallback",
    )
    parser.add_argument(
        "--backups-folder",
        help="JSON journal root; MARKINOTE_BACKUPS_FOLDER is the fallback",
    )
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--apply", action="store_true", help="fail one bounded batch")
    parser.add_argument(
        "--confirm-single-writer",
        action="store_true",
        help="attest that no other API process can own a running record",
    )
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


def reconcile_agent_runs(
    *,
    journal_backend: str,
    database_url: str,
    backups_folder: str,
    apply: bool,
    confirm_single_writer: bool,
    batch_size: int,
    now: Callable[[], datetime] | None = None,
) -> dict[str, object]:
    """Audit or terminalize a bounded batch without exposing row metadata."""
    backend = journal_backend.strip().lower()
    if backend not in SUPPORTED_BACKENDS:
        return _error(
            "unsupported_journal_backend",
            "the journal backend must be 'json' or 'database'",
        )
    if not 1 <= batch_size <= MAX_BATCH_SIZE:
        return _error(
            "unsafe_batch_size",
            f"batch size must be between 1 and {MAX_BATCH_SIZE}",
        )
    if apply and not confirm_single_writer:
        return _error(
            "single_writer_confirmation_required",
            "apply requires confirmation that exactly one API writer exists",
        )

    current_time = (now or (lambda: datetime.now(UTC)))()
    current_time = current_time.astimezone(UTC) if current_time.tzinfo is not None else current_time.replace(tzinfo=UTC)
    database: Database | None = None
    journal: AgentRunJournal
    try:
        if backend == "database":
            if not database_url.strip():
                return _error("database_url_missing", "a database URL is required")
            try:
                _validate_database_url(database_url)
            except CliArgumentError:
                return _error(
                    "unsupported_database_url",
                    "only SQLite and PostgreSQL database URLs are supported",
                )
            database = Database(database_url, create_schema=False)
            if not database.ready():
                return _error(
                    "database_not_ready",
                    "the database is unavailable or is not at the required schema revision",
                )
            journal = SqlAgentRunJournal(database, now=lambda: current_time)
        else:
            if not backups_folder.strip():
                return _error("backups_folder_missing", "a backups folder is required")
            root = Path(backups_folder).expanduser()
            if not root.is_dir():
                return _error(
                    "backups_folder_not_ready",
                    "the backups folder does not exist or is not a directory",
                )
            journal = JsonAgentRunJournal(root, now=lambda: current_time)

        candidate_count = journal.reconcile_running(limit=batch_size)
        reconciled_count = journal.reconcile_running(limit=batch_size, apply=True) if apply else 0
        remaining_candidate_count = journal.reconcile_running(limit=batch_size)
        return {
            "success": True,
            "operation": "reconcile_running",
            "journal_backend": backend,
            "mode": "apply" if apply else "dry_run",
            "batch_limit": batch_size,
            "candidate_count": candidate_count,
            "reconciled_count": reconciled_count,
            "remaining_candidate_count": remaining_candidate_count,
            "batch_saturated": candidate_count == batch_size,
        }
    except Exception:
        # Exception strings may contain connection credentials, record IDs,
        # paths or statement parameters. Keep stdout identifier-free.
        return _error(
            "journal_operation_failed",
            "the journal operation failed; inspect protected service telemetry",
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
        report = reconcile_agent_runs(
            journal_backend=(
                args.journal_backend
                if args.journal_backend is not None
                else environment.get("MARKINOTE_CONVERSATION_BACKEND", "json")
            ),
            database_url=(
                args.database_url if args.database_url is not None else environment.get("MARKINOTE_DATABASE_URL", "")
            ),
            backups_folder=(
                args.backups_folder
                if args.backups_folder is not None
                else environment.get("MARKINOTE_BACKUPS_FOLDER", "")
            ),
            apply=bool(args.apply),
            confirm_single_writer=bool(args.confirm_single_writer),
            batch_size=int(args.batch_size),
            now=now,
        )
    output.write(json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    output.write("\n")
    return 0 if report["success"] else 2


if __name__ == "__main__":
    sys.exit(main())
