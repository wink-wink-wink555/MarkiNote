from __future__ import annotations

import re
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def test_python_project_build_backend_is_exactly_locked_and_offline() -> None:
    pyproject = (REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    dockerfile = (REPOSITORY_ROOT / "Dockerfile.api").read_text(encoding="utf-8")
    uv_lock = (REPOSITORY_ROOT / "uv.lock").read_text(encoding="utf-8")

    expected = ("setuptools==83.0.0", "wheel==0.47.0")
    for requirement in expected:
        assert pyproject.count(f'"{requirement}"') == 2
        name, version = requirement.split("==", 1)
        assert f'name = "{name}"\nversion = "{version}"' in uv_lock

    assert re.search(
        r"^FROM ghcr\.io/astral-sh/uv:"
        r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
        r"@sha256:[0-9a-f]{64} AS uv$",
        dockerfile,
        re.MULTILINE,
    )
    assert "COPY --from=uv /uv /usr/local/bin/uv" in dockerfile
    assert "COPY pyproject.toml uv.lock README.md ./" in dockerfile
    assert dockerfile.count("uv export --frozen") == 2
    assert dockerfile.count("--require-hashes") == 2
    assert dockerfile.count("--only-binary=:all:") == 2
    assert "RUN --network=none" in dockerfile
    assert "--no-build-isolation" in dockerfile
    assert "pip install --no-compile --no-deps ." not in dockerfile
    assert "pip uninstall --yes pip" in dockerfile


def test_docker_context_secret_exclusions_follow_every_allowlist_rule() -> None:
    lines = [
        line.strip()
        for line in (REPOSITORY_ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    last_allowlist = max(index for index, line in enumerate(lines) if line.startswith("!"))
    required_exclusions = {
        "**/.env",
        "**/.env.*",
        "**/.npmrc",
        "**/.pypirc",
        "**/.netrc",
        "**/*.pem",
        "**/*.key",
        "**/*.p12",
        "**/*.pfx",
        "**/*.db",
        "**/*.sqlite",
        "**/*.log",
        "**/*.egg-info",
        "**/*.egg-info/**",
        "**/secrets/**",
    }
    for pattern in required_exclusions:
        assert pattern in lines
        assert lines.index(pattern) > last_allowlist

    assert "!uv.lock" in lines

    image_smoke = (REPOSITORY_ROOT / "infra/ci/image-content-smoke.py").read_text(
        encoding="utf-8"
    )
    assert 'path.name.endswith(".egg-info")' in image_smoke


def test_git_never_offers_local_credentials_or_private_keys_for_commit() -> None:
    lines = {
        line.strip()
        for line in (REPOSITORY_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    assert {
        ".npmrc",
        ".pypirc",
        ".netrc",
        "*.pem",
        "*.key",
        "*.crt",
        "*.cer",
        "*.p12",
        "*.pfx",
        "*.jks",
        "*.keystore",
        "*.secret",
    } <= lines


def test_web_dependencies_do_not_link_back_to_the_repository_root() -> None:
    package = (REPOSITORY_ROOT / "apps/web/package.json").read_text(encoding="utf-8")
    lock = (REPOSITORY_ROOT / "apps/web/package-lock.json").read_text(encoding="utf-8")

    assert '"markinote": "file:../.."' not in package
    assert '"markinote": "file:../.."' not in lock
    assert '"node_modules/markinote"' not in lock


def test_dependabot_allows_only_one_open_update_per_ecosystem() -> None:
    dependabot = (REPOSITORY_ROOT / ".github/dependabot.yml").read_text(encoding="utf-8")

    assert dependabot.count("open-pull-requests-limit: 1") == 6
    assert "open-pull-requests-limit: 3" not in dependabot


def test_ci_executes_the_dynamic_docker_context_secret_probe() -> None:
    workflow = (REPOSITORY_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    probe = (REPOSITORY_ROOT / "infra/ci/docker-context-secrets-smoke.py").read_text(
        encoding="utf-8"
    )

    assert "python3 infra/ci/docker-context-secrets-smoke.py" in workflow
    assert "FROM scratch" in probe
    assert "COPY . /context" in probe
    assert "apps/web/.env.local" in probe
    assert "packages/api-client/.npmrc" in probe
    assert "apps/api/src/markinote_api/.ai_backups/snapshot.md" in probe


def test_read_only_gateway_redirects_every_nginx_temp_path_to_tmpfs() -> None:
    nginx_config = (REPOSITORY_ROOT / "infra/nginx/nginx.conf").read_text(encoding="utf-8")

    for directive in (
        "client_body_temp_path",
        "proxy_temp_path",
        "fastcgi_temp_path",
        "uwsgi_temp_path",
        "scgi_temp_path",
    ):
        assert re.search(rf"^\s*{directive}\s+/tmp/[A-Za-z0-9_-]+;", nginx_config, re.MULTILINE)


def test_final_images_include_the_project_license_text() -> None:
    api_dockerfile = (REPOSITORY_ROOT / "Dockerfile.api").read_text(encoding="utf-8")
    web_dockerfile = (REPOSITORY_ROOT / "Dockerfile.web").read_text(encoding="utf-8")
    image_smoke = (REPOSITORY_ROOT / "infra/ci/image-content-smoke.py").read_text(
        encoding="utf-8"
    )

    destination = "/usr/share/licenses/markinote/LICENSE"
    assert f"LICENSE {destination}" in api_dockerfile
    assert f"LICENSE {destination}" in web_dockerfile
    assert image_smoke.count(destination) >= 2
    assert '"MIT License"' in image_smoke
