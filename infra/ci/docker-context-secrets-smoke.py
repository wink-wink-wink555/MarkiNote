"""Prove that the real root .dockerignore excludes nested secret/runtime files."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


class ContextSmokeFailure(RuntimeError):
    pass


def write_probe(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def build_context(context: Path, output: Path) -> None:
    command = [
        "docker",
        "build",
        "--no-cache",
        "--progress",
        "plain",
        "--file",
        str(context / "Dockerfile"),
        "--output",
        f"type=local,dest={output}",
        str(context),
    ]
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ContextSmokeFailure("Docker context probe could not complete") from error
    if completed.returncode != 0:
        diagnostic = " ".join(completed.stderr.strip().splitlines())[-800:]
        raise ContextSmokeFailure(
            f"Docker context probe failed with exit code {completed.returncode}: {diagnostic}"
        )


def main() -> int:
    sentinel = f"markinote-context-secret-{uuid.uuid4().hex}"
    with tempfile.TemporaryDirectory(prefix="markinote-context-") as temporary:
        root = Path(temporary)
        context = root / "context"
        output = root / "output"
        context.mkdir()
        shutil.copy2(REPOSITORY_ROOT / ".dockerignore", context / ".dockerignore")
        write_probe(context / "Dockerfile", "FROM scratch\nCOPY . /context\n")

        safe_paths = (
            Path("apps/api/src/markinote_api/context_safe.py"),
            Path("apps/web/src/context-safe.ts"),
            Path("packages/api-client/src/context-safe.ts"),
        )
        for safe_path in safe_paths:
            write_probe(context / safe_path, "safe-build-input\n")

        forbidden_paths = (
            Path("apps/web/.env.local"),
            Path("apps/web/src/nested/private.pem"),
            Path("apps/api/src/markinote_api/nested/state.sqlite3"),
            Path("apps/api/src/markinote_api/nested/runtime.log"),
            Path("packages/api-client/.npmrc"),
            Path("apps/api/src/markinote_api/secrets/provider.secret"),
            Path("apps/api/src/markinote_api/.ai_backups/snapshot.md"),
        )
        for forbidden_path in forbidden_paths:
            write_probe(context / forbidden_path, sentinel)

        build_context(context, output)
        exported = output / "context"
        missing_safe = [str(path) for path in safe_paths if not (exported / path).is_file()]
        leaked_paths = [str(path) for path in forbidden_paths if (exported / path).exists()]
        leaked_content = any(
            sentinel.encode("utf-8") in path.read_bytes()
            for path in exported.rglob("*")
            if path.is_file()
        )
        if missing_safe or leaked_paths or leaked_content:
            raise ContextSmokeFailure("Docker context secret boundary did not hold")

    print("Docker context secret exclusion smoke passed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ContextSmokeFailure as error:
        print(f"docker context smoke failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
