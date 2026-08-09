"""Rehearse isolated backup/restore for every local persistent data volume."""

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
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = REPOSITORY_ROOT / "infra" / "compose.yaml"
ARCHIVE_ROOTS = {
    "library": "/data/library",
    "backups": "/data/backups",
    "trash": "/data/trash",
    "conversations-json": "/data/conversations",
    "state": "/data/state",
}
SNAPSHOT_CODE = r'''
import hashlib, json, sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
files = {}
for path in sorted(root.rglob("*")):
    if path.is_symlink():
        raise SystemExit("persistent volume contains a symbolic link")
    if path.is_file():
        relative = path.relative_to(root).as_posix()
        value = path.read_bytes()
        files[relative] = {"bytes": len(value), "sha256": hashlib.sha256(value).hexdigest()}
print(json.dumps({"files": files}, separators=(",", ":")))
'''
BACKUP_VALIDATION_CODE = r'''
import json, sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
manifest_count = 0
before_images = 0
for manifest_path in sorted(root.glob("*/manifest.json")):
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("state") != "completed":
        raise SystemExit("backup manifest is not a completed object")
    operations = manifest.get("operations")
    if not isinstance(operations, list) or not operations:
        raise SystemExit("backup manifest has no operations")
    manifest_count += 1
    for operation in operations:
        if not isinstance(operation, dict):
            raise SystemExit("backup operation is invalid")
        if operation.get("has_backup") is True:
            relative = operation.get("snapshot")
            if not isinstance(relative, str) or not relative:
                raise SystemExit("backup snapshot reference is missing")
            candidate = (manifest_path.parent / "before" / relative).resolve()
            candidate.relative_to((manifest_path.parent / "before").resolve())
            if not candidate.exists():
                raise SystemExit("backup snapshot reference is broken")
            before_images += 1
if manifest_count < 1 or before_images < 1:
    raise SystemExit("no real backup manifest/before-image was found")
print(json.dumps({"manifestCount": manifest_count, "beforeImageCount": before_images}, separators=(",", ":")))
'''
TRASH_VALIDATION_CODE = r'''
import json, sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
records = 0
payloads = 0
for record in sorted(root.iterdir()):
    if not record.is_dir() or record.is_symlink():
        continue
    metadata_path = record / "metadata.json"
    payload = record / "payload"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if not isinstance(metadata, dict) or metadata.get("id") != record.name:
        raise SystemExit("trash metadata is invalid")
    if not payload.exists() or payload.is_symlink():
        raise SystemExit("trash payload is missing")
    records += 1
    payloads += 1
if records < 1:
    raise SystemExit("no real trash record was found")
print(json.dumps({"recordCount": records, "payloadCount": payloads}, separators=(",", ":")))
'''
JSON_VALIDATION_CODE = r'''
import json, sys
from pathlib import Path
from markinote_api.modules.conversations.repository import JsonConversationRepository

repository = JsonConversationRepository(Path(sys.argv[1]))
conversations, errors = repository.scan()
if errors:
    raise SystemExit("JSON conversation repository reported corruption")
message_count = sum(len(item.get("messages", [])) for item in conversations)
print(json.dumps({"conversationCount": len(conversations), "messageCount": message_count}, separators=(",", ":")))
'''
STATE_VALIDATION_CODE = r'''
import hashlib, json, sqlite3, sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
files = sorted(path for path in root.rglob("*") if path.is_file())
if not files:
    print(json.dumps({"mode": "unused", "fileCount": 0}, separators=(",", ":")))
    raise SystemExit(0)
databases = [path for path in files if path.suffix in {".db", ".sqlite", ".sqlite3"}]
if len(databases) != 1:
    raise SystemExit("state volume is populated without one identifiable SQLite database")
database = databases[0]
with sqlite3.connect(database) as connection:
    integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
if integrity != "ok":
    raise SystemExit("SQLite integrity check failed")
value = database.read_bytes()
print(json.dumps({"mode": "sqlite", "fileCount": len(files), "databaseBytes": len(value), "databaseSha256": hashlib.sha256(value).hexdigest(), "integrity": "ok"}, separators=(",", ":")))
'''


class LocalRestoreFailure(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Restore all MarkiNote local data volumes.")
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=Path(".artifacts/restore-rehearsal/local-volumes"),
    )
    return parser.parse_args()


def timestamp() -> str:
    return datetime.now(UTC).isoformat()


def execute(
    command: list[str],
    *,
    label: str,
    environment: dict[str, str] | None = None,
    input_bytes: bytes | None = None,
    timeout: int = 240,
    check: bool = True,
) -> subprocess.CompletedProcess[bytes]:
    print(f"[local-restore] {label}", file=sys.stderr, flush=True)
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
            raise LocalRestoreFailure(f"{label} could not complete") from error
        return subprocess.CompletedProcess(command, 1, b"", b"")
    if check and completed.returncode != 0:
        raise LocalRestoreFailure(f"{label} failed with exit code {completed.returncode}")
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


def available_ports(count: int) -> list[int]:
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


def project_environment(prefix: str, http_port: int, token: str, secret: str) -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(
        {
            "MARKINOTE_VERSION": os.environ.get("MARKINOTE_VERSION", "ci"),
            "MARKINOTE_VOLUME_PREFIX": prefix,
            "MARKINOTE_ENVIRONMENT": "test",
            "MARKINOTE_HTTP_BIND": "127.0.0.1",
            "MARKINOTE_HTTP_PORT": str(http_port),
            "MARKINOTE_CONVERSATION_BACKEND": "json",
            "MARKINOTE_DATABASE_URL": "sqlite:////data/state/markinote.db",
            "MARKINOTE_AUTO_CREATE_DATABASE": "true",
            "MARKINOTE_ACCESS_TOKEN": token,
            "MARKINOTE_SECRET_KEY": secret,
            "MARKINOTE_PUBLIC_ORIGIN": "",
            "MARKINOTE_TRUSTED_ORIGINS": "[]",
            "MARKINOTE_TRUSTED_HOSTS": '["127.0.0.1","localhost","testserver","api"]',
            "MARKINOTE_OTEL_ENABLED": "false",
            "MARKINOTE_AI_API_KEY": "",
        }
    )
    return environment


def request_json(
    base_url: str,
    token: str,
    method: str,
    path: str,
    *,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {token}", "Origin": base_url}
    body: bytes | None = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    request = urllib.request.Request(base_url + path, data=body, headers=headers, method=method)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=15) as response:
            status = response.status
            raw = response.read()
    except urllib.error.HTTPError as error:
        status = error.code
        raw = error.read()
    except OSError as error:
        raise LocalRestoreFailure(f"{method} request failed") from error
    if status != 200:
        raise LocalRestoreFailure(f"{method} {urllib.parse.urlsplit(path).path} returned {status}")
    try:
        value = json.loads(raw) if raw else {}
    except json.JSONDecodeError as error:
        raise LocalRestoreFailure(f"{method} response was not JSON") from error
    if not isinstance(value, dict):
        raise LocalRestoreFailure(f"{method} response was not an object")
    return value


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def json_stdout(completed: subprocess.CompletedProcess[bytes], label: str) -> dict[str, Any]:
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise LocalRestoreFailure(f"{label} returned invalid JSON") from error
    if not isinstance(value, dict):
        raise LocalRestoreFailure(f"{label} returned an unexpected result")
    return value


def run_volume_code(
    project: str,
    environment: dict[str, str],
    code: str,
    root: str,
    label: str,
) -> dict[str, Any]:
    completed = compose(
        project,
        environment,
        "run",
        "--rm",
        "--no-deps",
        "-T",
        "api",
        "python",
        "-c",
        code,
        root,
    )
    return json_stdout(completed, label)


def volume_snapshot(project: str, environment: dict[str, str], root: str) -> dict[str, Any]:
    value = run_volume_code(project, environment, SNAPSHOT_CODE, root, f"snapshot {root}")
    files = value.get("files")
    if not isinstance(files, dict):
        raise LocalRestoreFailure("volume snapshot did not contain a file map")
    return value


def snapshot_summary(snapshot: dict[str, Any]) -> dict[str, Any]:
    files = snapshot["files"]
    encoded = json.dumps(files, sort_keys=True, separators=(",", ":")).encode()
    return {
        "fileCount": len(files),
        "totalBytes": sum(item["bytes"] for item in files.values()),
        "treeSha256": sha256(encoded),
    }


def archive_volume(project: str, environment: dict[str, str], root: str) -> bytes:
    code = r'''
import sys, tarfile
with tarfile.open(fileobj=sys.stdout.buffer, mode="w|gz") as archive:
    archive.add(sys.argv[1], arcname=".")
'''
    value = compose(
        project,
        environment,
        "run",
        "--rm",
        "--no-deps",
        "-T",
        "api",
        "python",
        "-c",
        code,
        root,
    ).stdout
    if len(value) < 64:
        raise LocalRestoreFailure(f"archive for {root} is unexpectedly small")
    return value


def restore_volume(project: str, environment: dict[str, str], root: str, archive: bytes) -> None:
    code = r'''
import sys, tarfile
with tarfile.open(fileobj=sys.stdin.buffer, mode="r|gz") as archive:
    archive.extractall(path=sys.argv[1], filter="data")
'''
    compose(
        project,
        environment,
        "run",
        "--rm",
        "--no-deps",
        "-T",
        "api",
        "python",
        "-c",
        code,
        root,
        input_bytes=archive,
    )


def cleanup(project: str, environment: dict[str, str]) -> bool:
    down = compose(
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
    queries = (
        (["docker", "ps", "-a"], "{{.ID}}"),
        (["docker", "volume", "ls"], "{{.Name}}"),
        (["docker", "network", "ls"], "{{.ID}}"),
    )
    residuals = [
        execute(
            [
                *command,
                "--filter",
                f"label=com.docker.compose.project={project}",
                "--format",
                output_format,
            ],
            label=f"verify cleanup for {project}",
            check=False,
        )
        for command, output_format in queries
    ]
    return down.returncode == 0 and all(
        item.returncode == 0 and not item.stdout.strip() for item in residuals
    )


def write_evidence(artifact_dir: Path, evidence: dict[str, Any]) -> None:
    evidence_path = artifact_dir / "local-volume-restore-evidence.json"
    evidence_path.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    entries = [
        f"{sha256(path.read_bytes())}  {path.name}"
        for path in sorted(artifact_dir.iterdir())
        if path.is_file() and path.name != "SHA256SUMS"
    ]
    (artifact_dir / "SHA256SUMS").write_text("\n".join(entries) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    artifact_dir = args.artifact_dir.resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)
    protected = {
        "library.tar.gz",
        "backups.tar.gz",
        "trash.tar.gz",
        "conversations-json.tar.gz",
        "state.tar.gz",
        "local-volume-restore-evidence.json",
        "SHA256SUMS",
    }
    if any((artifact_dir / name).exists() for name in protected):
        raise LocalRestoreFailure("artifact directory already contains local restore evidence")

    suffix = f"{int(time.time())}-{secrets.token_hex(3)}"
    safe_suffix = re.sub(r"[^a-z0-9-]", "-", suffix.casefold())[:28]
    source_project = f"markinote-local-restore-{safe_suffix}-source"
    restore_project = f"markinote-local-restore-{safe_suffix}-restore"
    source_port, restore_port = available_ports(2)
    token = secrets.token_urlsafe(36)
    secret = secrets.token_urlsafe(48)
    source_environment = project_environment(
        f"markinote_local_restore_{safe_suffix}_source", source_port, token, secret
    )
    restore_environment = project_environment(
        f"markinote_local_restore_{safe_suffix}_restore", restore_port, token, secret
    )
    started = time.monotonic()
    evidence: dict[str, Any] = {
        "status": "failed",
        "startedAt": timestamp(),
        "sourceProject": source_project,
        "restoreProject": restore_project,
    }

    try:
        compose(
            source_project,
            source_environment,
            "up",
            "--detach",
            "--wait",
            "--no-build",
            "api",
            "gateway",
        )
        source_url = f"http://127.0.0.1:{source_port}"
        library_content = f"# Local restore proof\n\nrun={safe_suffix}\n"
        backup_before = "# Agent backup before-image\n\noriginal synthetic value\n"
        trash_content = "# Recoverable trash fixture\n\nsynthetic deleted value\n"
        for name, content in (
            ("local-restore-proof.md", library_content),
            ("agent-backup-proof.md", backup_before),
            ("trash-restore-proof.md", trash_content),
        ):
            request_json(
                source_url,
                token,
                "POST",
                "/api/v1/documents/files",
                payload={"path": "", "name": name, "content": content},
            )
        request_json(
            source_url,
            token,
            "DELETE",
            "/api/v1/documents?"
            + urllib.parse.urlencode({"path": "trash-restore-proof.md"}),
        )

        seed_code = r'''
import json
from markinote_api.application import create_application
from markinote_api.config import Settings
from markinote_api.modules.agent.tools import execute_tool

settings = Settings()
application = create_application(settings)
manager = application.state.backup_manager
group = manager.create_operation_group("local-restore-conversation")
_, backup = execute_tool(
    "write_file",
    {"path": "agent-backup-proof.md", "content": "# Agent backup after-image\n\nmutated synthetic value\n"},
    settings.library_folder,
    manager,
    group,
)
if not isinstance(backup, dict) or not isinstance(backup.get("operation_index"), int):
    raise SystemExit("AI backup operation did not return an index")
manager.complete_operation_group(group)
service = application.state.conversation_service
conversation = service.create("Local restore fixture", "system")
conversation["messages"].extend([
    {"role": "user", "content": "synthetic restore request"},
    {"role": "assistant", "content": "synthetic restore response"},
])
service.repository.save(conversation)
print(json.dumps({"conversationId": conversation["id"], "messageCount": len(conversation["messages"])}, separators=(",", ":")))
'''
        seeded = json_stdout(
            compose(
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
            ),
            "seed local volume fixtures",
        )
        conversation_id = seeded.get("conversationId")
        expected_raw_message_count = seeded.get("messageCount")
        if not isinstance(conversation_id, str) or not isinstance(expected_raw_message_count, int):
            raise LocalRestoreFailure("JSON conversation fixture metadata was invalid")
        source_conversation = request_json(
            source_url,
            token,
            "GET",
            f"/api/v1/conversations/{conversation_id}",
        )
        source_messages = source_conversation.get("conversation", {}).get("messages", [])
        if not isinstance(source_messages, list):
            raise LocalRestoreFailure("source conversation API returned invalid messages")
        source_display_message_count = len(source_messages)

        source_backup_validation = run_volume_code(
            source_project,
            source_environment,
            BACKUP_VALIDATION_CODE,
            ARCHIVE_ROOTS["backups"],
            "validate source backups",
        )
        source_trash_validation = run_volume_code(
            source_project,
            source_environment,
            TRASH_VALIDATION_CODE,
            ARCHIVE_ROOTS["trash"],
            "validate source trash",
        )
        source_json_validation = run_volume_code(
            source_project,
            source_environment,
            JSON_VALIDATION_CODE,
            ARCHIVE_ROOTS["conversations-json"],
            "validate source JSON conversations",
        )
        if source_json_validation != {
            "conversationCount": 1,
            "messageCount": expected_raw_message_count,
        }:
            raise LocalRestoreFailure("source JSON conversation counts were unexpected")
        source_state = run_volume_code(
            source_project,
            source_environment,
            STATE_VALIDATION_CODE,
            "/data/state",
            "validate source state",
        )

        compose(source_project, source_environment, "stop", "gateway", "api")
        source_snapshots = {
            name: volume_snapshot(source_project, source_environment, root)
            for name, root in ARCHIVE_ROOTS.items()
        }
        backup_hashes = {
            item["sha256"]
            for relative, item in source_snapshots["backups"]["files"].items()
            if "/before/" in f"/{relative}"
        }
        trash_hashes = {
            item["sha256"]
            for relative, item in source_snapshots["trash"]["files"].items()
            if relative.endswith("/payload")
        }
        if sha256(backup_before.encode()) not in backup_hashes:
            raise LocalRestoreFailure("AI backup before-image hash was not retained")
        if sha256(trash_content.encode()) not in trash_hashes:
            raise LocalRestoreFailure("trash payload hash was not retained")

        archives = {
            name: archive_volume(source_project, source_environment, root)
            for name, root in ARCHIVE_ROOTS.items()
        }
        for name, value in archives.items():
            (artifact_dir / f"{name}.tar.gz").write_bytes(value)
            restore_volume(restore_project, restore_environment, ARCHIVE_ROOTS[name], value)

        restored_snapshots = {
            name: volume_snapshot(restore_project, restore_environment, root)
            for name, root in ARCHIVE_ROOTS.items()
        }
        if restored_snapshots != source_snapshots:
            raise LocalRestoreFailure("restored local volume tree differs from its restore point")
        restored_backup_validation = run_volume_code(
            restore_project,
            restore_environment,
            BACKUP_VALIDATION_CODE,
            ARCHIVE_ROOTS["backups"],
            "validate restored backups",
        )
        restored_trash_validation = run_volume_code(
            restore_project,
            restore_environment,
            TRASH_VALIDATION_CODE,
            ARCHIVE_ROOTS["trash"],
            "validate restored trash",
        )
        restored_json_validation = run_volume_code(
            restore_project,
            restore_environment,
            JSON_VALIDATION_CODE,
            ARCHIVE_ROOTS["conversations-json"],
            "validate restored JSON conversations",
        )
        restored_state = run_volume_code(
            restore_project,
            restore_environment,
            STATE_VALIDATION_CODE,
            "/data/state",
            "validate restored state",
        )
        if restored_backup_validation != source_backup_validation:
            raise LocalRestoreFailure("restored backup manifest counts changed")
        if restored_trash_validation != source_trash_validation:
            raise LocalRestoreFailure("restored trash record counts changed")
        if restored_json_validation != source_json_validation:
            raise LocalRestoreFailure("restored JSON conversation counts changed")
        if restored_state != source_state:
            raise LocalRestoreFailure("restored state usage differs from the source")

        compose(
            restore_project,
            restore_environment,
            "up",
            "--detach",
            "--wait",
            "--no-build",
            "api",
            "gateway",
        )
        restore_url = f"http://127.0.0.1:{restore_port}"
        restored_document = request_json(
            restore_url,
            token,
            "GET",
            "/api/v1/documents/content?"
            + urllib.parse.urlencode({"path": "local-restore-proof.md"}),
        )
        if sha256(str(restored_document.get("content", "")).encode()) != sha256(
            library_content.encode()
        ):
            raise LocalRestoreFailure("restored document hash changed")
        restored_trash = request_json(
            restore_url,
            token,
            "GET",
            "/api/v1/documents/trash",
        )
        if len(restored_trash.get("items", [])) != source_trash_validation["recordCount"]:
            raise LocalRestoreFailure("restored trash API count changed")
        restored_conversation = request_json(
            restore_url,
            token,
            "GET",
            f"/api/v1/conversations/{conversation_id}",
        )
        messages = restored_conversation.get("conversation", {}).get("messages", [])
        if not isinstance(messages, list) or len(messages) != source_display_message_count:
            raise LocalRestoreFailure("restored JSON conversation message count changed")

        source_clean = cleanup(source_project, source_environment)
        restore_clean = cleanup(restore_project, restore_environment)
        if not source_clean or not restore_clean:
            raise LocalRestoreFailure("local restore resources were not fully cleaned")

        volume_evidence = {}
        for name, snapshot in source_snapshots.items():
            archive = archives[name]
            volume_evidence[name] = {
                **snapshot_summary(snapshot),
                "archiveBytes": len(archive),
                "archiveSha256": sha256(archive),
                "treeMatchedAfterRestore": True,
            }
        evidence.update(
            {
                "status": "ok",
                "completedAt": timestamp(),
                "durationSeconds": round(time.monotonic() - started, 3),
                "volumes": volume_evidence,
                "semanticVerification": {
                    "libraryDocumentHashMatched": True,
                    "backupManifestCount": source_backup_validation["manifestCount"],
                    "backupBeforeImageCount": source_backup_validation["beforeImageCount"],
                    "backupReferencesValid": True,
                    "trashRecordCount": source_trash_validation["recordCount"],
                    "trashPayloadCount": source_trash_validation["payloadCount"],
                    "jsonConversationCount": source_json_validation["conversationCount"],
                    "jsonMessageCount": source_json_validation["messageCount"],
                    "displayMessageCount": source_display_message_count,
                    "state": source_state,
                },
                "verification": {
                    "sourceResourcesRemoved": source_clean,
                    "restoreResourcesRemoved": restore_clean,
                    "noDocumentBodyInEvidence": True,
                    "noCredentialInEvidence": True,
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
                    "errorCode": "local_volume_restore_rehearsal_failed",
                    "failureType": type(error).__name__,
                    "cleanupComplete": source_clean and restore_clean,
                },
                separators=(",", ":"),
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
