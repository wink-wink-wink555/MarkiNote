"""Audit or prune bounded SQL tool-command and operation-audit retention batches.

Dry-run is the default. Output is one identifier-free JSON summary; database
URLs, command IDs, document paths, results and backup IDs are never emitted.
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

from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
API_SOURCE = REPOSITORY_ROOT / "apps" / "api" / "src"
sys.path.insert(0, str(REPOSITORY_ROOT))
sys.path.insert(0, str(API_SOURCE))

from markinote_api.modules.conversations.repository import Database  # noqa: E402
from markinote_api.modules.operations.journal import SqlCommandJournal  # noqa: E402

DEFAULT_COMMAND_RETENTION_DAYS = 30
DEFAULT_AUDIT_RETENTION_DAYS = 90
DEFAULT_BATCH_SIZE = 1_000
DEFAULT_SCAN_LIMIT = 10_000
MAX_RETENTION_DAYS = 3_650
MAX_BATCH_SIZE = 10_000
MAX_SCAN_LIMIT = 100_000
MAX_BACKUP_INDEX_ENTRIES = 100_000


class CliArgumentError(ValueError):
    """An invalid invocation rendered without echoing unsafe input."""


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        del message
        raise CliArgumentError


def _parser() -> argparse.ArgumentParser:
    parser = JsonArgumentParser(
        description="Dry-run or prune one bounded SQL operation-retention batch."
    )
    parser.add_argument(
        "--database-url",
        help="SQLAlchemy URL; MARKINOTE_DATABASE_URL is the fallback",
    )
    parser.add_argument(
        "--backups-folder",
        help=(
            "mounted backup root; MARKINOTE_BACKUPS_FOLDER is the fallback. "
            "When omitted, all backup-referencing commands are retained."
        ),
    )
    parser.add_argument(
        "--command-retention-days",
        type=int,
        default=DEFAULT_COMMAND_RETENTION_DAYS,
    )
    parser.add_argument(
        "--audit-retention-days",
        type=int,
        default=DEFAULT_AUDIT_RETENTION_DAYS,
    )
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--scan-limit", type=int, default=DEFAULT_SCAN_LIMIT)
    parser.add_argument("--apply", action="store_true")
    return parser


def _error(code: str, message: str) -> dict[str, object]:
    return {"success": False, "error_code": code, "message": message}


def _as_utc(value: datetime) -> datetime:
    return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)


def _validate_database_url(database_url: str) -> None:
    try:
        backend = make_url(database_url).get_backend_name()
    except (ArgumentError, ValueError) as error:
        raise CliArgumentError from error
    if backend not in {"sqlite", "postgresql"}:
        raise CliArgumentError


def _live_backup_groups(backups_folder: str | None) -> tuple[set[str] | None, str]:
    if backups_folder is None or not backups_folder.strip():
        return None, "conservative"
    try:
        configured = Path(backups_folder)
        if configured.is_symlink():
            raise CliArgumentError
        root = configured.resolve()
        if not root.is_dir():
            raise CliArgumentError
        values: set[str] = set()
        for scanned_entries, path in enumerate(root.iterdir(), start=1):
            if scanned_entries > MAX_BACKUP_INDEX_ENTRIES:
                # A partial index could make a live backup look expired. Refuse
                # the whole maintenance batch instead of deleting from it.
                raise CliArgumentError
            if path.is_dir() and not path.is_symlink() and (path / "manifest.json").is_file():
                values.add(path.name)
        return values, "mounted_backup_index"
    except CliArgumentError:
        raise
    except (OSError, RuntimeError, ValueError) as error:
        raise CliArgumentError from error


def maintain_operation_records(
    database_url: str,
    *,
    backups_folder: str | None,
    apply: bool,
    command_retention_days: int,
    audit_retention_days: int,
    batch_size: int,
    scan_limit: int,
    now: Callable[[], datetime] | None = None,
) -> dict[str, object]:
    if not 1 <= command_retention_days <= MAX_RETENTION_DAYS:
        return _error("unsafe_command_retention_days", "command retention days are outside policy")
    if not 1 <= audit_retention_days <= MAX_RETENTION_DAYS:
        return _error("unsafe_audit_retention_days", "audit retention days are outside policy")
    if audit_retention_days < command_retention_days:
        return _error(
            "audit_retention_too_short",
            "audit retention must be at least as long as command retention",
        )
    if not 1 <= batch_size <= MAX_BATCH_SIZE:
        return _error("unsafe_batch_size", "batch size is outside policy")
    if not batch_size <= scan_limit <= MAX_SCAN_LIMIT:
        return _error("unsafe_scan_limit", "scan limit must cover the batch and remain bounded")
    if not database_url.strip():
        return _error("database_url_missing", "a database URL is required")
    try:
        _validate_database_url(database_url)
        protected_groups, backup_verification = _live_backup_groups(backups_folder)
    except (CliArgumentError, OSError):
        return _error("unsafe_configuration", "database or backup storage configuration is invalid")

    current_time = _as_utc((now or (lambda: datetime.now(UTC)))())
    command_cutoff = current_time - timedelta(days=command_retention_days)
    audit_cutoff = current_time - timedelta(days=audit_retention_days)
    database: Database | None = None
    try:
        database = Database(database_url, create_schema=False)
        if not database.ready():
            return _error(
                "database_not_ready",
                "the database is unavailable or is not at the required schema revision",
            )
        journal = SqlCommandJournal(database)
        command_ids, scanned_count, protected_count = journal.terminal_retention_candidates(
            before=command_cutoff,
            limit=batch_size,
            scan_limit=scan_limit,
            protected_backup_groups=protected_groups,
        )
        audit_ids = journal.audit_retention_candidates(before=audit_cutoff, limit=batch_size)
        deleted_commands = 0
        deleted_audits = 0
        if apply:
            deleted_commands = journal.prune_terminal(
                before=command_cutoff,
                limit=batch_size,
                scan_limit=scan_limit,
                protected_backup_groups=protected_groups,
            )
            # Re-evaluate after command deletion: old audit rows tied only to a
            # just-expired command may now be safely eligible in this batch.
            deleted_audits = journal.prune_audit(before=audit_cutoff, limit=batch_size)
        remaining_commands, remaining_scanned, remaining_protected = (
            journal.terminal_retention_candidates(
                before=command_cutoff,
                limit=batch_size,
                scan_limit=scan_limit,
                protected_backup_groups=protected_groups,
            )
        )
        remaining_audits = journal.audit_retention_candidates(
            before=audit_cutoff,
            limit=batch_size,
        )
        return {
            "success": True,
            "mode": "apply" if apply else "dry_run",
            "backup_verification": backup_verification,
            "command_cutoff": command_cutoff.isoformat(),
            "audit_cutoff": audit_cutoff.isoformat(),
            "batch_limit": batch_size,
            "scan_limit": scan_limit,
            "command_candidate_count": len(command_ids),
            "command_scanned_count": scanned_count,
            "command_protected_count": protected_count,
            "audit_candidate_count": len(audit_ids),
            "deleted_command_count": deleted_commands,
            "deleted_audit_count": deleted_audits,
            "remaining_command_candidate_count": len(remaining_commands),
            "remaining_command_scanned_count": remaining_scanned,
            "remaining_command_protected_count": remaining_protected,
            "remaining_audit_candidate_count": len(remaining_audits),
            "batch_saturated": len(command_ids) == batch_size or len(audit_ids) == batch_size,
            "scan_saturated": scanned_count == scan_limit or remaining_scanned == scan_limit,
        }
    except Exception:
        return _error(
            "database_operation_failed",
            "the retention operation failed; inspect protected service telemetry",
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
        report = maintain_operation_records(
            args.database_url
            if args.database_url is not None
            else environment.get("MARKINOTE_DATABASE_URL", ""),
            backups_folder=(
                args.backups_folder
                if args.backups_folder is not None
                else environment.get("MARKINOTE_BACKUPS_FOLDER")
            ),
            apply=bool(args.apply),
            command_retention_days=int(args.command_retention_days),
            audit_retention_days=int(args.audit_retention_days),
            batch_size=int(args.batch_size),
            scan_limit=int(args.scan_limit),
            now=now,
        )
    output.write(json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    output.write("\n")
    return 0 if report["success"] else 2


if __name__ == "__main__":
    sys.exit(main())
