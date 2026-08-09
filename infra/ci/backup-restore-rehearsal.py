"""Create and verify an isolated PostgreSQL plus document-volume restore point."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = REPOSITORY_ROOT / "infra" / "compose.yaml"
AGENT_RUN_ID = "restore-rehearsal-run"
AGENT_REQUEST_ID = "restore-rehearsal-request"
PRUNE_TERMINAL_RUN_ID = "restore-prune-terminal"
PRUNE_RUNNING_RUN_ID = "restore-prune-running"
OPERATION_ELIGIBLE_COMMAND_ID = "restore-operation-expired"
OPERATION_RUNNING_COMMAND_ID = "restore-operation-running"
OPERATION_RECOVERY_COMMAND_ID = "restore-operation-recovery-required"
OPERATION_BACKUP_COMMAND_ID = "restore-operation-live-backup"


class RehearsalFailure(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Back up and restore a real PostgreSQL database and document volume.",
    )
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=Path(os.environ.get("MARKINOTE_REHEARSAL_ARTIFACT_DIR", ".artifacts/restore-rehearsal")),
    )
    return parser.parse_args()


def timestamp() -> str:
    return datetime.now(UTC).isoformat()


def safe_run_id() -> str:
    raw = os.environ.get("GITHUB_RUN_ID", "local") + "-" + os.environ.get(
        "GITHUB_RUN_ATTEMPT", "1"
    )
    value = re.sub(r"[^a-z0-9-]+", "-", raw.casefold()).strip("-")[:32]
    return value or "local-1"


def available_loopback_ports(count: int) -> list[int]:
    """Select distinct ephemeral ports while holding every reservation open."""
    listeners: list[socket.socket] = []
    try:
        for _ in range(count):
            listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            listener.bind(("127.0.0.1", 0))
            listeners.append(listener)
        return [int(listener.getsockname()[1]) for listener in listeners]
    finally:
        for listener in listeners:
            listener.close()


def execute(
    command: list[str],
    *,
    label: str,
    environment: dict[str, str] | None = None,
    input_bytes: bytes | None = None,
    timeout: int = 240,
    check: bool = True,
) -> subprocess.CompletedProcess[bytes]:
    print(f"[restore-rehearsal] {label}", file=sys.stderr, flush=True)
    try:
        completed = subprocess.run(
            command,
            cwd=REPOSITORY_ROOT,
            env=environment,
            input=input_bytes,
            capture_output=True,
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        if check:
            raise RehearsalFailure(f"{label} could not complete") from error
        return subprocess.CompletedProcess(command, 1, b"", b"")
    if check and completed.returncode != 0:
        raise RehearsalFailure(f"{label} failed with exit code {completed.returncode}")
    return completed


def compose(
    project: str,
    environment: dict[str, str],
    *arguments: str,
    input_bytes: bytes | None = None,
    timeout: int = 240,
    check: bool = True,
) -> subprocess.CompletedProcess[bytes]:
    return execute(
        ["docker", "compose", "-p", project, "-f", str(COMPOSE_FILE), *arguments],
        label=f"{project}: {' '.join(arguments[:5])}",
        environment=environment,
        input_bytes=input_bytes,
        timeout=timeout,
        check=check,
    )


def project_environment(
    *,
    prefix: str,
    http_port: int,
    postgres_port: int,
    password: str,
    access_token: str,
    secret_key: str,
) -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(
        {
            "MARKINOTE_VERSION": os.environ.get("MARKINOTE_VERSION", "ci"),
            "MARKINOTE_VOLUME_PREFIX": prefix,
            "MARKINOTE_ENVIRONMENT": "test",
            "MARKINOTE_HTTP_BIND": "127.0.0.1",
            "MARKINOTE_HTTP_PORT": str(http_port),
            "MARKINOTE_POSTGRES_PORT": str(postgres_port),
            "MARKINOTE_POSTGRES_DB": "markinote",
            "MARKINOTE_POSTGRES_USER": "markinote",
            "MARKINOTE_POSTGRES_PASSWORD": password,
            "MARKINOTE_DATABASE_URL": (
                f"postgresql+psycopg://markinote:{password}@postgres:5432/markinote"
            ),
            "MARKINOTE_CONVERSATION_BACKEND": "database",
            "MARKINOTE_AUTO_CREATE_DATABASE": "false",
            "MARKINOTE_ACCESS_TOKEN": access_token,
            "MARKINOTE_SECRET_KEY": secret_key,
            "MARKINOTE_PUBLIC_ORIGIN": "",
            "MARKINOTE_TRUSTED_ORIGINS": "[]",
            "MARKINOTE_TRUSTED_HOSTS": '["127.0.0.1","localhost","testserver","api"]',
            "MARKINOTE_OTEL_ENABLED": "false",
        }
    )
    return environment


def request_json(
    base_url: str,
    access_token: str,
    method: str,
    path: str,
    *,
    payload: dict[str, Any] | None = None,
    expected_status: int = 200,
) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {access_token}", "Origin": base_url}
    body: bytes | None = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    outgoing = urllib.request.Request(
        base_url + path,
        data=body,
        headers=headers,
        method=method,
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(outgoing, timeout=15) as response:
            status = response.status
            raw = response.read()
    except urllib.error.HTTPError as error:
        status = error.code
        raw = error.read()
    except OSError as error:
        raise RehearsalFailure(f"HTTP verification failed for {path}") from error
    if status != expected_status:
        raise RehearsalFailure(f"{method} {path} returned {status}, expected {expected_status}")
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise RehearsalFailure(f"{method} {path} returned invalid JSON") from error
    if not isinstance(value, dict):
        raise RehearsalFailure(f"{method} {path} returned non-object JSON")
    return value


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def write_bytes_exclusive(path: Path, value: bytes) -> None:
    with path.open("xb") as destination:
        destination.write(value)


def image_id(reference: str) -> str:
    completed = execute(
        ["docker", "image", "inspect", reference, "--format", "{{.Id}}"],
        label=f"inspect image {reference}",
    )
    return completed.stdout.decode().strip()


def database_counts(project: str, environment: dict[str, str]) -> dict[str, int]:
    query = (
        "SELECT (SELECT count(*) FROM conversations),"
        "(SELECT count(*) FROM messages),(SELECT count(*) FROM tool_commands),"
        "(SELECT count(*) FROM agent_runs);"
    )
    completed = compose(
        project,
        environment,
        "--profile",
        "postgres",
        "exec",
        "-T",
        "postgres",
        "psql",
        "--no-align",
        "--tuples-only",
        "--field-separator=,",
        "--username",
        "markinote",
        "--dbname",
        "markinote",
        "--command",
        query,
    )
    values = completed.stdout.decode().strip().split(",")
    if len(values) != 4:
        raise RehearsalFailure("database count query returned an unexpected result")
    return dict(
        zip(
            ("conversations", "messages", "toolCommands", "agentRuns"),
            map(int, values),
            strict=True,
        )
    )


def agent_run_snapshot(project: str, environment: dict[str, str]) -> dict[str, Any]:
    query = (
        "SELECT json_build_object("
        "'runId',run_id,'requestId',request_id,'conversationId',conversation_id,"
        "'provider',provider,'model',model,'state',state,"
        "'hasStartedAt',started_at IS NOT NULL,"
        "'hasConversationAttachedAt',conversation_attached_at IS NOT NULL,"
        "'hasFirstContentAt',first_content_at IS NOT NULL,"
        "'hasFinishedAt',finished_at IS NOT NULL,"
        "'errorCode',error_code)::text FROM agent_runs "
        f"WHERE run_id='{AGENT_RUN_ID}' AND request_id='{AGENT_REQUEST_ID}';"
    )
    completed = compose(
        project,
        environment,
        "--profile",
        "postgres",
        "exec",
        "-T",
        "postgres",
        "psql",
        "--no-align",
        "--tuples-only",
        "--username",
        "markinote",
        "--dbname",
        "markinote",
        "--command",
        query,
    )
    try:
        value = json.loads(completed.stdout.decode().strip())
    except json.JSONDecodeError as error:
        raise RehearsalFailure("agent run snapshot query returned invalid JSON") from error
    if not isinstance(value, dict):
        raise RehearsalFailure("agent run snapshot query returned an unexpected result")
    return value


def prune_fixture_counts(project: str, environment: dict[str, str]) -> dict[str, int]:
    query = (
        f"SELECT count(*) FILTER (WHERE run_id='{PRUNE_TERMINAL_RUN_ID}'),"
        f"count(*) FILTER (WHERE run_id='{PRUNE_RUNNING_RUN_ID}') FROM agent_runs;"
    )
    completed = compose(
        project,
        environment,
        "--profile",
        "postgres",
        "exec",
        "-T",
        "postgres",
        "psql",
        "--no-align",
        "--tuples-only",
        "--field-separator=,",
        "--username",
        "markinote",
        "--dbname",
        "markinote",
        "--command",
        query,
    )
    values = completed.stdout.decode().strip().split(",")
    if len(values) != 2:
        raise RehearsalFailure("agent run maintenance query returned an unexpected result")
    return dict(zip(("terminal", "running"), map(int, values), strict=True))


def operation_prune_fixture_counts(project: str, environment: dict[str, str]) -> dict[str, int]:
    command_ids = (
        OPERATION_ELIGIBLE_COMMAND_ID,
        OPERATION_RUNNING_COMMAND_ID,
        OPERATION_RECOVERY_COMMAND_ID,
        OPERATION_BACKUP_COMMAND_ID,
    )
    escaped = ",".join(f"'{value}'" for value in command_ids)
    query = (
        f"SELECT count(*) FILTER (WHERE command_id='{OPERATION_ELIGIBLE_COMMAND_ID}'),"
        f"count(*) FILTER (WHERE command_id='{OPERATION_RUNNING_COMMAND_ID}'),"
        f"count(*) FILTER (WHERE command_id='{OPERATION_RECOVERY_COMMAND_ID}'),"
        f"count(*) FILTER (WHERE command_id='{OPERATION_BACKUP_COMMAND_ID}'),"
        f"(SELECT count(*) FROM operation_audit WHERE command_id IN ({escaped}) "
        "OR command_id IS NULL) FROM tool_commands;"
    )
    completed = compose(
        project,
        environment,
        "--profile",
        "postgres",
        "exec",
        "-T",
        "postgres",
        "psql",
        "--no-align",
        "--tuples-only",
        "--field-separator=,",
        "--username",
        "markinote",
        "--dbname",
        "markinote",
        "--command",
        query,
    )
    values = completed.stdout.decode().strip().split(",")
    if len(values) != 5:
        raise RehearsalFailure("operation maintenance query returned an unexpected result")
    return dict(
        zip(
            ("eligible", "running", "recoveryRequired", "liveBackup", "auditRows"),
            map(int, values),
            strict=True,
        )
    )


def cleanup(project: str, environment: dict[str, str]) -> bool:
    completed = compose(
        project,
        environment,
        "--profile",
        "*",
        "down",
        "--volumes",
        "--remove-orphans",
        timeout=180,
        check=False,
    )
    residual_commands = {
        "containers": (["docker", "ps", "-a"], "{{.ID}}"),
        "volumes": (["docker", "volume", "ls"], "{{.Name}}"),
        "networks": (["docker", "network", "ls"], "{{.ID}}"),
    }
    residuals = []
    for resource, (command, output_format) in residual_commands.items():
        residuals.append(
            execute(
                [
                    *command,
                    "--filter",
                    f"label=com.docker.compose.project={project}",
                    "--format",
                    output_format,
                ],
                label=f"verify {resource} cleanup for {project}",
                check=False,
            )
        )
    return completed.returncode == 0 and all(
        residual.returncode == 0 and not residual.stdout.strip() for residual in residuals
    )


def write_evidence(artifact_dir: Path, evidence: dict[str, Any]) -> None:
    evidence_path = artifact_dir / "restore-evidence.json"
    evidence_path.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    entries = []
    for path in sorted(artifact_dir.iterdir()):
        if path.is_file() and path.name != "SHA256SUMS":
            entries.append(f"{sha256(path.read_bytes())}  {path.name}")
    (artifact_dir / "SHA256SUMS").write_text("\n".join(entries) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    artifact_dir = args.artifact_dir.resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)
    protected_names = {
        "postgres.dump",
        "postgres.contents",
        "library.tar.gz",
        "backups.tar.gz",
        "restore-evidence.json",
        "SHA256SUMS",
    }
    if any((artifact_dir / name).exists() for name in protected_names):
        raise RehearsalFailure("artifact directory already contains rehearsal evidence")

    # A CI run ID is unique per workflow but local invocations otherwise share
    # `local-1`. Add an unguessable suffix so concurrent rehearsals can never
    # attach to, restore into, or clean up one another's projects and volumes.
    run_id = f"{safe_run_id()[:24]}-{secrets.token_hex(3)}"
    source_project = f"markinote-rehearsal-{run_id}-source"
    restore_project = f"markinote-rehearsal-{run_id}-restore"
    password = os.environ.get("MARKINOTE_REHEARSAL_POSTGRES_PASSWORD") or secrets.token_urlsafe(32)
    access_token = secrets.token_urlsafe(36)
    secret_key = secrets.token_urlsafe(48)
    source_http_port, source_postgres_port, restore_http_port, restore_postgres_port = (
        available_loopback_ports(4)
    )
    source_environment = project_environment(
        prefix=f"markinote_rehearsal_{run_id}_source",
        http_port=source_http_port,
        postgres_port=source_postgres_port,
        password=password,
        access_token=access_token,
        secret_key=secret_key,
    )
    restore_environment = project_environment(
        prefix=f"markinote_rehearsal_{run_id}_restore",
        http_port=restore_http_port,
        postgres_port=restore_postgres_port,
        password=password,
        access_token=access_token,
        secret_key=secret_key,
    )
    version = source_environment["MARKINOTE_VERSION"]
    api_image = f"{source_environment.get('MARKINOTE_API_IMAGE', 'markinote-api')}:{version}"
    gateway_image = f"{source_environment.get('MARKINOTE_GATEWAY_IMAGE', 'markinote-gateway')}:{version}"
    started = time.monotonic()
    evidence: dict[str, Any] = {
        "status": "failed",
        "startedAt": timestamp(),
        "sourceProject": source_project,
        "restoreProject": restore_project,
        "images": {"api": image_id(api_image), "gateway": image_id(gateway_image)},
    }

    try:
        for project, environment in (
            (source_project, source_environment),
            (restore_project, restore_environment),
        ):
            compose(project, environment, "--profile", "postgres", "up", "--detach", "--wait", "postgres")

        compose(
            source_project,
            source_environment,
            "--profile",
            "migration",
            "--profile",
            "postgres",
            "run",
            "--rm",
            "--no-deps",
            "migrate",
        )
        compose(
            source_project,
            source_environment,
            "--profile",
            "postgres",
            "up",
            "--detach",
            "--wait",
            "--no-build",
            "api",
            "gateway",
        )

        source_url = f"http://127.0.0.1:{source_http_port}"
        document_name = "restore-rehearsal.md"
        document_content = f"# Restore rehearsal\n\nrun={run_id}\n数据库与文档必须同时恢复。\n"
        created = request_json(
            source_url,
            access_token,
            "POST",
            "/api/v1/documents/files",
            payload={"path": "", "name": document_name, "content": document_content},
        )
        if created.get("path") != document_name:
            raise RehearsalFailure("source document creation failed")

        seed_code = """
from markinote_api.application import create_application
from markinote_api.config import Settings
from markinote_api.modules.conversations.repository import OperationAuditRecord
from markinote_api.modules.agent.run_journal import SqlAgentRunJournal
from markinote_api.modules.operations.journal import SqlCommandJournal
from datetime import UTC, datetime, timedelta
from pathlib import Path
app = create_application(Settings())
service = app.state.conversation_service
conversation = service.create("Restore rehearsal", "system")
conversation["messages"].extend([
    {"role": "user", "content": "persist across restore"},
    {"role": "assistant", "content": "database restored"},
])
service.repository.save(conversation)
journal = SqlAgentRunJournal(app.state.database)
assert journal.start(
    run_id="restore-rehearsal-run",
    request_id="restore-rehearsal-request",
    provider="fixture-provider",
    model="fixture-model",
)
assert journal.attach_conversation(
    "restore-rehearsal-run",
    "restore-rehearsal-request",
    conversation["id"],
)
assert journal.mark_first_content("restore-rehearsal-run", "restore-rehearsal-request")
assert journal.finish("restore-rehearsal-run", "restore-rehearsal-request", "completed")
old_clock = datetime.now(UTC) - timedelta(days=45)
maintenance = SqlAgentRunJournal(app.state.database, now=lambda: old_clock)
assert maintenance.start(
    run_id="restore-prune-terminal",
    request_id="restore-prune-terminal-request",
    provider="fixture-provider",
    model="fixture-model",
)
assert maintenance.finish(
    "restore-prune-terminal",
    "restore-prune-terminal-request",
    "completed",
)
assert maintenance.start(
    run_id="restore-prune-running",
    request_id="restore-prune-running-request",
    provider="fixture-provider",
    model="fixture-model",
)
operation_clock = datetime.now(UTC) - timedelta(days=120)
operations = SqlCommandJournal(app.state.database, now=lambda: operation_clock)
assert operations.claim(
    "restore-operation-expired",
    run_id="operation-retention-run",
    conversation_id=conversation["id"],
    tool_name="write_file",
)[0]
assert operations.complete("restore-operation-expired", {"success": True})
assert operations.claim(
    "restore-operation-running",
    run_id="operation-retention-run",
    conversation_id=conversation["id"],
    tool_name="write_file",
)[0]
assert operations.claim(
    "restore-operation-recovery-required",
    run_id="operation-retention-run",
    conversation_id=conversation["id"],
    tool_name="write_file",
)[0]
assert operations.fail(
    "restore-operation-recovery-required",
    {"recovery_required": True},
)
backup_group = Path("/data/backups/restore-operation-live-backup")
backup_group.mkdir(parents=True, exist_ok=True)
(backup_group / "manifest.json").write_text("{}", encoding="utf-8")
assert operations.claim(
    "restore-operation-live-backup",
    run_id="operation-retention-run",
    conversation_id=conversation["id"],
    tool_name="write_file",
)[0]
assert operations.complete(
    "restore-operation-live-backup",
    {"backup_group_id": "restore-operation-live-backup"},
)
with app.state.database.session() as session, session.begin():
    for command_id in (
        "restore-operation-expired",
        "restore-operation-running",
        "restore-operation-recovery-required",
        "restore-operation-live-backup",
        None,
    ):
        session.add(
            OperationAuditRecord(
                request_id="operation-retention-request",
                conversation_id=conversation["id"],
                command_id=command_id,
                action="retention_fixture",
                target=None,
                outcome="success",
                content_hash=None,
                details={},
                created_at=operation_clock,
            )
        )
print("REHEARSAL_CONVERSATION_ID=" + conversation["id"])
if app.state.database is not None:
    app.state.database.close()
"""
        seeded = compose(
            source_project,
            source_environment,
            "run",
            "--rm",
            "--no-deps",
            "-T",
            "api",
            "python",
            "-c",
            seed_code,
        ).stdout.decode()
        identifier = re.search(r"REHEARSAL_CONVERSATION_ID=([a-zA-Z0-9_-]+)", seeded)
        if identifier is None:
            raise RehearsalFailure("source conversation seed did not return an identifier")
        conversation_id = identifier.group(1)

        maintenance_command = (
            "python",
            "apps/api/scripts/prune_agent_runs.py",
            "--retention-days",
            "30",
            "--batch-size",
            "100",
        )
        dry_run = compose(
            source_project,
            source_environment,
            "run",
            "--rm",
            "--no-deps",
            "-T",
            "api",
            *maintenance_command,
        )
        try:
            dry_run_report = json.loads(dry_run.stdout)
        except json.JSONDecodeError as error:
            raise RehearsalFailure("agent run maintenance dry-run returned invalid JSON") from error
        if not isinstance(dry_run_report, dict) or {
            "success": dry_run_report.get("success"),
            "mode": dry_run_report.get("mode"),
            "candidate_count": dry_run_report.get("candidate_count"),
            "deleted_count": dry_run_report.get("deleted_count"),
            "remaining_candidate_count": dry_run_report.get("remaining_candidate_count"),
        } != {
            "success": True,
            "mode": "dry_run",
            "candidate_count": 1,
            "deleted_count": 0,
            "remaining_candidate_count": 1,
        }:
            raise RehearsalFailure("agent run maintenance dry-run summary was unexpected")
        if prune_fixture_counts(source_project, source_environment) != {
            "terminal": 1,
            "running": 1,
        }:
            raise RehearsalFailure("agent run maintenance dry-run changed journal rows")

        applied = compose(
            source_project,
            source_environment,
            "run",
            "--rm",
            "--no-deps",
            "-T",
            "api",
            *maintenance_command,
            "--apply",
        )
        try:
            apply_report = json.loads(applied.stdout)
        except json.JSONDecodeError as error:
            raise RehearsalFailure("agent run maintenance apply returned invalid JSON") from error
        if not isinstance(apply_report, dict) or {
            "success": apply_report.get("success"),
            "mode": apply_report.get("mode"),
            "candidate_count": apply_report.get("candidate_count"),
            "deleted_count": apply_report.get("deleted_count"),
            "remaining_candidate_count": apply_report.get("remaining_candidate_count"),
        } != {
            "success": True,
            "mode": "apply",
            "candidate_count": 1,
            "deleted_count": 1,
            "remaining_candidate_count": 0,
        }:
            raise RehearsalFailure("agent run maintenance apply summary was unexpected")
        if prune_fixture_counts(source_project, source_environment) != {
            "terminal": 0,
            "running": 1,
        }:
            raise RehearsalFailure("agent run maintenance removed a non-terminal row")

        operation_maintenance_command = (
            "python",
            "apps/api/scripts/prune_operation_records.py",
            "--backups-folder",
            "/data/backups",
            "--command-retention-days",
            "30",
            "--audit-retention-days",
            "90",
            "--batch-size",
            "100",
            "--scan-limit",
            "100",
        )
        operation_before = operation_prune_fixture_counts(source_project, source_environment)
        if operation_before != {
            "eligible": 1,
            "running": 1,
            "recoveryRequired": 1,
            "liveBackup": 1,
            "auditRows": 5,
        }:
            raise RehearsalFailure("operation maintenance fixture counts were unexpected")
        operation_dry_run = compose(
            source_project,
            source_environment,
            "run",
            "--rm",
            "--no-deps",
            "-T",
            "api",
            *operation_maintenance_command,
        )
        try:
            operation_dry_report = json.loads(operation_dry_run.stdout)
        except json.JSONDecodeError as error:
            raise RehearsalFailure("operation maintenance dry-run returned invalid JSON") from error
        if not isinstance(operation_dry_report, dict) or {
            "success": operation_dry_report.get("success"),
            "mode": operation_dry_report.get("mode"),
            "backup_verification": operation_dry_report.get("backup_verification"),
            "command_candidate_count": operation_dry_report.get("command_candidate_count"),
            "command_protected_count": operation_dry_report.get("command_protected_count"),
            "audit_candidate_count": operation_dry_report.get("audit_candidate_count"),
            "deleted_command_count": operation_dry_report.get("deleted_command_count"),
            "deleted_audit_count": operation_dry_report.get("deleted_audit_count"),
        } != {
            "success": True,
            "mode": "dry_run",
            "backup_verification": "mounted_backup_index",
            "command_candidate_count": 1,
            "command_protected_count": 2,
            "audit_candidate_count": 1,
            "deleted_command_count": 0,
            "deleted_audit_count": 0,
        }:
            raise RehearsalFailure("operation maintenance dry-run summary was unexpected")
        if operation_prune_fixture_counts(source_project, source_environment) != operation_before:
            raise RehearsalFailure("operation maintenance dry-run changed durable records")

        operation_applied = compose(
            source_project,
            source_environment,
            "run",
            "--rm",
            "--no-deps",
            "-T",
            "api",
            *operation_maintenance_command,
            "--apply",
        )
        try:
            operation_apply_report = json.loads(operation_applied.stdout)
        except json.JSONDecodeError as error:
            raise RehearsalFailure("operation maintenance apply returned invalid JSON") from error
        if not isinstance(operation_apply_report, dict) or {
            "success": operation_apply_report.get("success"),
            "mode": operation_apply_report.get("mode"),
            "deleted_command_count": operation_apply_report.get("deleted_command_count"),
            "deleted_audit_count": operation_apply_report.get("deleted_audit_count"),
            "remaining_command_candidate_count": operation_apply_report.get(
                "remaining_command_candidate_count"
            ),
            "remaining_command_protected_count": operation_apply_report.get(
                "remaining_command_protected_count"
            ),
            "remaining_audit_candidate_count": operation_apply_report.get(
                "remaining_audit_candidate_count"
            ),
        } != {
            "success": True,
            "mode": "apply",
            "deleted_command_count": 1,
            "deleted_audit_count": 2,
            "remaining_command_candidate_count": 0,
            "remaining_command_protected_count": 2,
            "remaining_audit_candidate_count": 0,
        }:
            raise RehearsalFailure("operation maintenance apply summary was unexpected")
        if operation_prune_fixture_counts(source_project, source_environment) != {
            "eligible": 0,
            "running": 1,
            "recoveryRequired": 1,
            "liveBackup": 1,
            "auditRows": 3,
        }:
            raise RehearsalFailure("operation maintenance removed a protected record")

        source_counts = database_counts(source_project, source_environment)
        source_agent_run = agent_run_snapshot(source_project, source_environment)
        if source_agent_run != {
            "runId": AGENT_RUN_ID,
            "requestId": AGENT_REQUEST_ID,
            "conversationId": conversation_id,
            "provider": "fixture-provider",
            "model": "fixture-model",
            "state": "completed",
            "hasStartedAt": True,
            "hasConversationAttachedAt": True,
            "hasFirstContentAt": True,
            "hasFinishedAt": True,
            "errorCode": None,
        }:
            raise RehearsalFailure("source agent run journal metadata was unexpected")

        compose(source_project, source_environment, "stop", "gateway", "api")
        postgres_dump = compose(
            source_project,
            source_environment,
            "--profile",
            "postgres",
            "exec",
            "-T",
            "postgres",
            "sh",
            "-c",
            'pg_dump --format=custom --no-owner --no-acl --username "$POSTGRES_USER" "$POSTGRES_DB"',
        ).stdout
        if len(postgres_dump) < 1024:
            raise RehearsalFailure("PostgreSQL dump is unexpectedly small")
        write_bytes_exclusive(artifact_dir / "postgres.dump", postgres_dump)

        postgres_contents = compose(
            source_project,
            source_environment,
            "--profile",
            "postgres",
            "exec",
            "-T",
            "postgres",
            "pg_restore",
            "--list",
            input_bytes=postgres_dump,
        ).stdout
        write_bytes_exclusive(artifact_dir / "postgres.contents", postgres_contents)

        archive_code = """
import sys, tarfile
with tarfile.open(fileobj=sys.stdout.buffer, mode="w|gz") as archive:
    archive.add(sys.argv[1], arcname=".")
"""
        library_archive = compose(
            source_project,
            source_environment,
            "run",
            "--rm",
            "--no-deps",
            "-T",
            "api",
            "python",
            "-c",
            archive_code,
            "/data/library",
        ).stdout
        if len(library_archive) < 64:
            raise RehearsalFailure("document archive is unexpectedly small")
        write_bytes_exclusive(artifact_dir / "library.tar.gz", library_archive)
        backups_archive = compose(
            source_project,
            source_environment,
            "run",
            "--rm",
            "--no-deps",
            "-T",
            "api",
            "python",
            "-c",
            archive_code,
            "/data/backups",
        ).stdout
        if len(backups_archive) < 64:
            raise RehearsalFailure("backup metadata archive is unexpectedly small")
        write_bytes_exclusive(artifact_dir / "backups.tar.gz", backups_archive)

        compose(
            restore_project,
            restore_environment,
            "--profile",
            "postgres",
            "exec",
            "-T",
            "postgres",
            "pg_restore",
            "--exit-on-error",
            "--no-owner",
            "--no-acl",
            "--username",
            "markinote",
            "--dbname",
            "markinote",
            input_bytes=postgres_dump,
        )
        compose(
            restore_project,
            restore_environment,
            "run",
            "--rm",
            "--no-deps",
            "-T",
            "api",
            "true",
        )
        extract_code = """
import sys, tarfile
with tarfile.open(fileobj=sys.stdin.buffer, mode="r|gz") as archive:
    archive.extractall(path=sys.argv[1], filter="data")
"""
        compose(
            restore_project,
            restore_environment,
            "run",
            "--rm",
            "--no-deps",
            "-T",
            "api",
            "python",
            "-c",
            extract_code,
            "/data/library",
            input_bytes=library_archive,
        )
        compose(
            restore_project,
            restore_environment,
            "run",
            "--rm",
            "--no-deps",
            "-T",
            "api",
            "python",
            "-c",
            extract_code,
            "/data/backups",
            input_bytes=backups_archive,
        )
        compose(
            restore_project,
            restore_environment,
            "--profile",
            "postgres",
            "up",
            "--detach",
            "--wait",
            "--no-build",
            "api",
            "gateway",
        )

        restore_url = f"http://127.0.0.1:{restore_http_port}"
        restored_document = request_json(
            restore_url,
            access_token,
            "GET",
            "/api/v1/documents/content?path=restore-rehearsal.md",
        )
        if restored_document.get("content") != document_content:
            raise RehearsalFailure("restored document content differs from the restore point")
        restored_conversation = request_json(
            restore_url,
            access_token,
            "GET",
            f"/api/v1/conversations/{conversation_id}",
        )
        messages = restored_conversation.get("conversation", {}).get("messages", [])
        if [item.get("content") for item in messages] != [
            "persist across restore",
            "database restored",
        ]:
            raise RehearsalFailure("restored conversation messages differ from the restore point")
        restored_counts = database_counts(restore_project, restore_environment)
        if restored_counts != source_counts:
            raise RehearsalFailure("restored PostgreSQL table counts differ from the restore point")
        restored_agent_run = agent_run_snapshot(restore_project, restore_environment)
        if restored_agent_run != source_agent_run:
            raise RehearsalFailure("restored agent run journal differs from the restore point")
        compose(
            restore_project,
            restore_environment,
            "run",
            "--rm",
            "--no-deps",
            "-T",
            "api",
            "python",
            "-c",
            (
                "from pathlib import Path; "
                "assert Path('/data/backups/restore-operation-live-backup/manifest.json').is_file()"
            ),
        )

        alembic_current = compose(
            restore_project,
            restore_environment,
            "--profile",
            "migration",
            "run",
            "--rm",
            "--no-deps",
            "migrate",
            "alembic",
            "current",
        ).stdout.decode()
        revision = re.search(r"([0-9]{8}_[0-9]{4}) \(head\)", alembic_current)
        if revision is None:
            raise RehearsalFailure("restored database is not at Alembic head")

        source_clean = cleanup(source_project, source_environment)
        restore_clean = cleanup(restore_project, restore_environment)
        if not source_clean or not restore_clean:
            raise RehearsalFailure("isolated rehearsal resources were not fully cleaned")

        evidence.update(
            {
                "status": "ok",
                "completedAt": timestamp(),
                "durationSeconds": round(time.monotonic() - started, 3),
                "restorePoint": {
                    "document": {
                        "path": document_name,
                        "sha256": sha256(document_content.encode()),
                    },
                    "conversationId": conversation_id,
                    "databaseCounts": source_counts,
                    "agentRun": source_agent_run,
                    "alembicRevision": revision.group(1),
                },
                "backupArtifacts": {
                    "postgres.dump": {"bytes": len(postgres_dump), "sha256": sha256(postgres_dump)},
                    "library.tar.gz": {
                        "bytes": len(library_archive),
                        "sha256": sha256(library_archive),
                    },
                    "backups.tar.gz": {
                        "bytes": len(backups_archive),
                        "sha256": sha256(backups_archive),
                    },
                },
                "verification": {
                    "documentHashMatched": True,
                    "conversationMessagesMatched": True,
                    "databaseCountsMatched": True,
                    "agentRunMetadataMatched": True,
                    "agentRunMaintenanceDryRunSafe": True,
                    "agentRunMaintenanceDeletedOnlyTerminal": True,
                    "operationMaintenanceDryRunSafe": True,
                    "operationMaintenanceDeletedOnlyExpired": True,
                    "operationMaintenanceProtectedRunning": True,
                    "operationMaintenanceProtectedRecoveryRequired": True,
                    "operationMaintenanceProtectedLiveBackup": True,
                    "operationBackupReferenceRestored": True,
                    "operationMaintenanceEvidenceIdentifierFree": True,
                    "alembicAtHead": True,
                    "sourceResourcesRemoved": source_clean,
                    "restoreResourcesRemoved": restore_clean,
                },
            }
        )
        write_evidence(artifact_dir, evidence)
        print(json.dumps(evidence, separators=(",", ":")))
        return 0
    except Exception as error:
        source_clean = cleanup(source_project, source_environment)
        restore_clean = cleanup(restore_project, restore_environment)
        evidence.update(
            {
                "completedAt": timestamp(),
                "durationSeconds": round(time.monotonic() - started, 3),
                "failureType": type(error).__name__,
                "cleanup": {"source": source_clean, "restore": restore_clean},
            }
        )
        write_evidence(artifact_dir, evidence)
        print(
            json.dumps(
                {
                    "success": False,
                    "errorCode": "postgres_restore_rehearsal_failed",
                    "failureType": type(error).__name__,
                    "cleanupComplete": source_clean and restore_clean,
                },
                separators=(",", ":"),
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
