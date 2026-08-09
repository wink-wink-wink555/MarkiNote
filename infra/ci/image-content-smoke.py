"""Verify final image identities, users, and production filesystem allowlists."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Any

API_CHECK = r'''
from importlib.metadata import PackageNotFoundError, distribution, version
from importlib.util import find_spec
from pathlib import Path

root = Path("/srv/markinote")
license_file = Path("/usr/share/licenses/markinote/LICENSE")
required = [
    root / "alembic.ini",
    root / "apps/api/migrations/env.py",
    root / "apps/api/migrations/script.py.mako",
    root / "apps/api/migrations/versions",
    root / "apps/api/scripts/migrate_conversations.py",
    root / "apps/api/scripts/prune_agent_runs.py",
    root / "apps/api/scripts/prune_operation_records.py",
    root / "apps/api/scripts/reconcile_agent_runs.py",
]
missing = [str(path.relative_to(root)) for path in required if not path.exists()]
if not license_file.is_file() or "MIT License" not in license_file.read_text(encoding="utf-8"):
    raise SystemExit("runtime image is missing the MarkiNote license text")
forbidden_paths = [
    root / "app",
    root / "asgi.py",
    root / "main.py",
    root / "static",
    root / "templates",
    root / "apps/api/src/markinote_api",
]
forbidden_names = {
    ".git",
    ".github",
    ".pytest_cache",
    "__pycache__",
    "coverage",
    "e2e",
    "node_modules",
    "playwright-report",
    "test-results",
    "tests",
}
secret_file_names = {".env", ".npmrc", ".pypirc", ".netrc"}
secret_suffixes = {
    ".cer",
    ".crt",
    ".db",
    ".jks",
    ".key",
    ".keystore",
    ".log",
    ".p12",
    ".pem",
    ".pfx",
    ".secret",
    ".sqlite",
    ".sqlite3",
}
runtime_directory_names = {".ai_backups", ".ai_conversations", ".trash", "secrets"}
forbidden = [
    str(path.relative_to(root))
    for path in root.rglob("*")
    if (
        path.name in forbidden_names
        or path.name.endswith(".egg-info")
        or path.name.casefold() in runtime_directory_names
        or (
            path.is_file()
            and (
                path.name.casefold() in secret_file_names
                or path.name.casefold().startswith(".env.")
                or path.suffix.casefold() in secret_suffixes
            )
        )
    )
]
forbidden.extend(
    str(path.relative_to(root))
    for path in forbidden_paths
    if path.exists()
)
runtime_payloads = [str(path) for path in Path("/data").rglob("*") if path.is_file()]
try:
    installed_distribution = distribution("markinote")
except PackageNotFoundError as error:
    raise SystemExit("runtime image is missing the markinote distribution") from error
module_spec = find_spec("markinote_api")
if module_spec is None or module_spec.origin is None:
    raise SystemExit("runtime image cannot resolve the markinote_api package")
venv_root = Path("/opt/venv").resolve()
distribution_root = Path(installed_distribution.locate_file("")).resolve()
module_path = Path(module_spec.origin).resolve()
if venv_root not in distribution_root.parents or venv_root not in module_path.parents:
    raise SystemExit("markinote_api must load from the installed runtime distribution")
for package in ("pip", "setuptools", "wheel"):
    try:
        version(package)
    except PackageNotFoundError:
        continue
    raise SystemExit("runtime image contains Python build tooling")
if missing or forbidden or runtime_payloads:
    raise SystemExit("runtime filesystem allowlist failed")
'''

GATEWAY_CHECK = r'''
set -eu
test -f /etc/nginx/nginx.conf
test -f /usr/share/nginx/html/index.html
test -s /usr/share/licenses/markinote/LICENSE
grep -q 'MIT License' /usr/share/licenses/markinote/LICENSE
for path in \
  /usr/share/nginx/html/tests \
  /usr/share/nginx/html/e2e \
  /usr/share/nginx/html/coverage \
  /usr/share/nginx/html/playwright-report \
  /usr/share/nginx/html/test-results \
  /usr/share/nginx/html/node_modules
do
  test ! -e "$path"
done
if find /usr/share/nginx/html \
  \( -type d \( -name secrets -o -name .ai_backups -o -name .ai_conversations -o -name .trash \) \
  -o -type f \( -name .env -o -name '.env.*' -o -name .npmrc -o -name .pypirc \
  -o -name .netrc -o -name '*.pem' -o -name '*.key' -o -name '*.crt' -o -name '*.cer' \
  -o -name '*.p12' -o -name '*.pfx' -o -name '*.jks' -o -name '*.keystore' \
  -o -name '*.db' -o -name '*.sqlite' -o -name '*.sqlite3' -o -name '*.log' \
  -o -name '*.secret' \) \) -print -quit | grep -q .
then
  exit 1
fi
'''


class ImageSmokeFailure(RuntimeError):
    pass


def execute(command: list[str], label: str) -> subprocess.CompletedProcess[str]:
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=90,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ImageSmokeFailure(f"{label} could not complete") from error
    if completed.returncode != 0:
        raise ImageSmokeFailure(f"{label} failed with exit code {completed.returncode}")
    return completed


def inspect(reference: str) -> dict[str, Any]:
    completed = execute(["docker", "image", "inspect", reference], f"inspect {reference}")
    try:
        values = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise ImageSmokeFailure(f"inspect {reference} returned invalid JSON") from error
    if not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], dict):
        raise ImageSmokeFailure(f"inspect {reference} returned an unexpected result")
    return values[0]


def evidence(reference: str, expected_user: str) -> dict[str, object]:
    model = inspect(reference)
    config = model.get("Config")
    if not isinstance(config, dict) or config.get("User") != expected_user:
        raise ImageSmokeFailure(f"{reference} does not declare runtime user {expected_user}")
    labels = config.get("Labels")
    required_labels = {
        "org.opencontainers.image.source",
        "org.opencontainers.image.revision",
        "org.opencontainers.image.version",
        "org.opencontainers.image.licenses",
    }
    if not isinstance(labels, dict) or not required_labels.issubset(labels):
        raise ImageSmokeFailure(f"{reference} is missing OCI identity labels")
    expected_version = os.environ.get("MARKINOTE_VERSION", "ci")
    if labels.get("org.opencontainers.image.version") != expected_version:
        raise ImageSmokeFailure(f"{reference} OCI version does not match MARKINOTE_VERSION")
    image_id = model.get("Id")
    size = model.get("Size")
    if not isinstance(image_id, str) or not isinstance(size, int) or size <= 0:
        raise ImageSmokeFailure(f"{reference} inspect metadata is incomplete")
    return {
        "reference": reference,
        "id": image_id,
        "sizeBytes": size,
        "user": expected_user,
        "version": expected_version,
        "testsIncluded": False,
        "coverageIncluded": False,
        "e2eIncluded": False,
        "secretFilesIncluded": False,
        "runtimePayloadsIncluded": False,
    }


def main() -> int:
    version = os.environ.get("MARKINOTE_VERSION", "ci")
    api_reference = f"{os.environ.get('MARKINOTE_API_IMAGE', 'markinote-api')}:{version}"
    gateway_reference = f"{os.environ.get('MARKINOTE_GATEWAY_IMAGE', 'markinote-gateway')}:{version}"
    api_evidence = evidence(api_reference, "10001:10001")
    gateway_evidence = evidence(gateway_reference, "101:101")
    if api_evidence["id"] == gateway_evidence["id"]:
        raise ImageSmokeFailure("API and gateway unexpectedly resolve to the same image")

    execute(
        [
            "docker",
            "run",
            "--rm",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            "--entrypoint",
            "python",
            api_reference,
            "-c",
            API_CHECK,
        ],
        "verify API runtime filesystem",
    )
    execute(
        [
            "docker",
            "run",
            "--rm",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            "--entrypoint",
            "sh",
            gateway_reference,
            "-c",
            GATEWAY_CHECK,
        ],
        "verify gateway runtime filesystem",
    )
    print(
        json.dumps(
            {
                "status": "ok",
                "api": api_evidence,
                "gateway": gateway_evidence,
                "readOnlyExecution": True,
                "capDropAllExecution": True,
                "noNewPrivilegesExecution": True,
                "apiInstalledDistribution": True,
                "apiSourceTreeIncluded": False,
            },
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ImageSmokeFailure as error:
        print(f"image content smoke failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
