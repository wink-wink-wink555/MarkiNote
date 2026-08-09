"""Auditable and idempotent JSON-to-SQL conversation migration.

Dry-run is the default. Use --apply only after reviewing the generated report.
The source directory is never changed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from markinote_api.modules.conversations.repository import (
    Database,
    JsonConversationRepository,
    SqlConversationRepository,
)


class MigrationRecordError(RuntimeError):
    """A reviewed per-record migration failure safe for an audit report."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.public_message = message


def canonical_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def migrate(
    source: JsonConversationRepository,
    destination: SqlConversationRepository,
    *,
    apply: bool,
    overwrite_existing: bool = False,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "started_at": datetime.now(UTC).isoformat(),
        "dry_run": not apply,
        "source_count": 0,
        "migrated_count": 0,
        "verified_count": 0,
        "message_count": 0,
        "errors": [],
        "items": [],
    }
    conversations, source_errors = source.scan()
    report["source_file_count"] = len(conversations) + len(source_errors)
    report["errors"].extend(source_errors)
    for finding in source_errors:
        report["items"].append({**finding, "status": "error"})
    for conversation in conversations:
        report["source_count"] += 1
        conversation_id = str(conversation.get("id", ""))
        item = {
            "id": conversation_id,
            "messages": len(conversation.get("messages", [])),
            "source_hash": canonical_hash(conversation),
            "status": "audited",
        }
        report["message_count"] += item["messages"]
        try:
            if apply:
                saved = destination.get(conversation_id)
                if saved is not None:
                    comparable_existing = {**saved}
                    comparable_source = {**conversation}
                    comparable_existing.pop("updated_at", None)
                    comparable_source.pop("updated_at", None)
                    if canonical_hash(comparable_existing) != canonical_hash(comparable_source):
                        if not overwrite_existing:
                            raise MigrationRecordError(
                                "destination_conflict",
                                "destination differs from source; freeze writes and use --overwrite-existing",
                            )
                        destination.save(conversation)
                        report["migrated_count"] += 1
                        saved = destination.get(conversation_id)
                else:
                    destination.save(conversation)
                    report["migrated_count"] += 1
                    saved = destination.get(conversation_id)
                if saved is None:
                    raise MigrationRecordError(
                        "destination_record_missing",
                        "destination record is missing after migration",
                    )
                comparable_source = {**conversation}
                comparable_saved = {**saved}
                comparable_source.pop("updated_at", None)
                comparable_saved.pop("updated_at", None)
                item["destination_hash"] = canonical_hash(comparable_saved)
                item["verification_hash"] = canonical_hash(comparable_source)
                if item["destination_hash"] != item["verification_hash"]:
                    raise MigrationRecordError(
                        "verification_mismatch",
                        "destination content hash does not match the source",
                    )
                item["status"] = "verified"
                report["verified_count"] += 1
        except MigrationRecordError as error:
            item["status"] = "error"
            item["error_code"] = error.code
            item["error"] = error.public_message
            report["errors"].append(
                {
                    "id": conversation_id,
                    "code": error.code,
                    "error": error.public_message,
                }
            )
        except Exception:
            # Database drivers and serializers can include connection URLs,
            # filesystem paths, or document values in exception messages.
            # Preserve the affected record identifier in the operator-owned
            # report, but expose only a stable failure contract.
            item["status"] = "error"
            item["error_code"] = "migration_record_failed"
            item["error"] = "record migration failed; inspect protected service telemetry"
            report["errors"].append(
                {
                    "id": conversation_id,
                    "code": "migration_record_failed",
                    "error": "record migration failed; inspect protected service telemetry",
                }
            )
        report["items"].append(item)
    report["completed_at"] = datetime.now(UTC).isoformat()
    report["success"] = not report["errors"] and (
        not apply or report["verified_count"] == report["source_count"]
    )
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--overwrite-existing",
        action="store_true",
        help="replace a differing destination only after application writes are frozen",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    # The destination schema must already be at the reviewed Alembic revision.
    database: Database | None = None
    try:
        database = Database(args.database_url, create_schema=False)
        report = migrate(
            JsonConversationRepository(args.source),
            SqlConversationRepository(database),
            apply=args.apply,
            overwrite_existing=args.overwrite_existing,
        )
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        # Stdout is commonly retained by CI. Keep identifiers and detailed
        # findings only in the explicitly selected, operator-protected report.
        summary_keys = (
            "success",
            "dry_run",
            "source_file_count",
            "source_count",
            "migrated_count",
            "verified_count",
            "message_count",
        )
        print(json.dumps({key: report.get(key) for key in summary_keys}, ensure_ascii=False))
        return 0 if report["success"] else 1
    except Exception:
        print(
            json.dumps(
                {
                    "success": False,
                    "error_code": "migration_failed",
                    "message": "conversation migration could not be completed",
                },
                ensure_ascii=False,
            )
        )
        return 2
    finally:
        if database is not None:
            with suppress(Exception):
                database.close()


if __name__ == "__main__":
    sys.exit(main())
