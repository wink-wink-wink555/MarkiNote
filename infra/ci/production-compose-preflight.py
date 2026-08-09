"""Fail closed when the rendered production Compose model is not immutable."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}\Z")
STABLE_RELEASE_VERSION_PATTERN = re.compile(
    r"v(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\Z"
)
HOSTNAME_PATTERN = re.compile(
    r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)"
    r"(?:\.(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?))*$"
)
AI_SSE_TOOL_EVENT_OVERHEAD_BYTES = 64 * 1024
AI_SSE_TOOL_ARGUMENT_COPIES = 2


class PreflightFailure(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render and validate the digest-only production Compose contract.",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        help="Optional Docker Compose dotenv file (for example .env.production).",
    )
    parser.add_argument(
        "--base-compose",
        type=Path,
        default=REPOSITORY_ROOT / "infra" / "compose.yaml",
    )
    parser.add_argument(
        "--production-compose",
        type=Path,
        default=REPOSITORY_ROOT / "infra" / "compose.production.yaml",
    )
    return parser.parse_args()


def render_compose(args: argparse.Namespace) -> dict[str, Any]:
    command = ["docker", "compose"]
    if args.env_file is not None:
        command.extend(("--env-file", str(args.env_file.resolve())))
    command.extend(
        (
            "--profile",
            "*",
            "-f",
            str(args.base_compose.resolve()),
            "-f",
            str(args.production_compose.resolve()),
            "config",
            "--format",
            "json",
        )
    )
    try:
        completed = subprocess.run(
            command,
            cwd=REPOSITORY_ROOT,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except OSError as error:
        raise PreflightFailure("Docker Compose is unavailable") from error
    if completed.returncode != 0:
        raise PreflightFailure(
            "Docker Compose rejected the production model; check required variables privately"
        )
    try:
        rendered = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise PreflightFailure("Docker Compose did not return a JSON model") from error
    if not isinstance(rendered, dict):
        raise PreflightFailure("Docker Compose returned an unexpected model")
    return rendered


def service(model: dict[str, Any], name: str) -> dict[str, Any]:
    services = model.get("services")
    value = services.get(name) if isinstance(services, dict) else None
    if not isinstance(value, dict):
        raise PreflightFailure(f"production Compose service is missing: {name}")
    return value


def immutable_reference(value: object, service_name: str) -> str:
    if not isinstance(value, str) or "@" not in value:
        raise PreflightFailure(f"{service_name} image must use repository@sha256:digest")
    repository, digest = value.rsplit("@", 1)
    if not repository or any(character.isspace() for character in repository):
        raise PreflightFailure(f"{service_name} image repository is invalid")
    if ":" in repository.rsplit("/", 1)[-1]:
        raise PreflightFailure(
            f"{service_name} image must not combine a mutable tag with its digest"
        )
    if DIGEST_PATTERN.fullmatch(digest) is None:
        raise PreflightFailure(f"{service_name} image digest must be lowercase sha256")
    return value


def environment(service_model: dict[str, Any], service_name: str) -> dict[str, str]:
    value = service_model.get("environment")
    if not isinstance(value, dict):
        raise PreflightFailure(f"{service_name} environment is missing")
    return {str(key): str(item) for key, item in value.items() if item is not None}


def require_value(values: dict[str, str], key: str, service_name: str) -> str:
    value = values.get(key, "")
    if not value:
        raise PreflightFailure(f"{service_name} requires {key}")
    return value


def validate_release_version(value: str) -> str:
    if STABLE_RELEASE_VERSION_PATTERN.fullmatch(value) is None:
        raise PreflightFailure(
            "MARKINOTE_APP_VERSION must be the exact stable vMAJOR.MINOR.PATCH release tag"
        )
    return value


def trusted_host_matches(hostname: str, pattern: str) -> bool:
    if pattern.startswith("*."):
        return hostname.endswith(pattern[1:]) and hostname != pattern[2:]
    return hostname == pattern


def validate_runtime_hardening(service_model: dict[str, Any], service_name: str) -> None:
    cap_drop = service_model.get("cap_drop")
    security_options = service_model.get("security_opt")
    tmpfs = service_model.get("tmpfs")
    if service_model.get("init") is not True or service_model.get("read_only") is not True:
        raise PreflightFailure(f"{service_name} must use init and a read-only root filesystem")
    if not isinstance(cap_drop, list) or "ALL" not in cap_drop:
        raise PreflightFailure(f"{service_name} must drop all Linux capabilities")
    if not isinstance(security_options, list) or "no-new-privileges:true" not in security_options:
        raise PreflightFailure(f"{service_name} must enable no-new-privileges")
    if not isinstance(tmpfs, list) or not tmpfs:
        raise PreflightFailure(f"{service_name} must use an explicit writable tmpfs")


def service_networks(service_model: dict[str, Any], service_name: str) -> set[str]:
    value = service_model.get("networks")
    if isinstance(value, dict):
        return {str(name) for name in value}
    if isinstance(value, list):
        return {str(name) for name in value}
    raise PreflightFailure(f"{service_name} networks are missing")


def validate_network_topology(model: dict[str, Any]) -> None:
    networks = model.get("networks")
    services = model.get("services")
    if not isinstance(networks, dict) or not isinstance(services, dict):
        raise PreflightFailure("production network topology is missing")
    for network_name in ("backend", "telemetry"):
        network = networks.get(network_name)
        if not isinstance(network, dict) or network.get("internal") is not True:
            raise PreflightFailure(f"{network_name} must remain an internal Docker network")
    egress = networks.get("egress")
    if not isinstance(egress, dict) or egress.get("internal") is True:
        raise PreflightFailure("egress must be a dedicated non-internal Docker network")

    api_model = service(model, "api")
    api_networks = service_networks(api_model, "api")
    if not {"backend", "telemetry", "egress"}.issubset(api_networks):
        raise PreflightFailure("api must attach to backend, telemetry, and egress")
    if api_model.get("ports"):
        raise PreflightFailure("api must not publish a host port")
    for service_name, service_model in services.items():
        if service_name == "api" or not isinstance(service_model, dict):
            continue
        if "egress" in service_networks(service_model, service_name):
            raise PreflightFailure(f"{service_name} must not attach to the API egress network")


def validate_api_environment(api_model: dict[str, Any]) -> None:
    values = environment(api_model, "api")
    expected = {
        "MARKINOTE_ENVIRONMENT": "production",
        "MARKINOTE_JSON_LOGS": "true",
        "MARKINOTE_AUTO_CREATE_DATABASE": "false",
        "MARKINOTE_AGENT_RUN_RECONCILE_ON_STARTUP": "true",
        "MARKINOTE_AGENT_RUN_SINGLE_WRITER": "true",
    }
    for key, required in expected.items():
        if values.get(key, "").casefold() != required:
            raise PreflightFailure(f"api production invariant failed: {key}={required}")

    validate_release_version(require_value(values, "MARKINOTE_APP_VERSION", "api"))
    try:
        reconcile_limit = int(require_value(values, "MARKINOTE_AGENT_RUN_RECONCILE_LIMIT", "api"))
    except ValueError as error:
        raise PreflightFailure("MARKINOTE_AGENT_RUN_RECONCILE_LIMIT must be an integer") from error
    if not 1 <= reconcile_limit <= 10_000:
        raise PreflightFailure("MARKINOTE_AGENT_RUN_RECONCILE_LIMIT must be between 1 and 10000")
    if values.get("MARKINOTE_AI_PROVIDER_FIXTURE_URL", ""):
        raise PreflightFailure("production must not configure a test AI provider fixture")

    token = require_value(values, "MARKINOTE_ACCESS_TOKEN", "api")
    secret = require_value(values, "MARKINOTE_SECRET_KEY", "api")
    if len(token) < 24 or len(secret) < 32 or token == secret:
        raise PreflightFailure("api credentials do not satisfy the production length/separation policy")

    public_origin = require_value(values, "MARKINOTE_PUBLIC_ORIGIN", "api")
    parsed_origin = urlsplit(public_origin)
    try:
        origin_port = parsed_origin.port
    except ValueError as error:
        raise PreflightFailure("MARKINOTE_PUBLIC_ORIGIN contains an invalid TCP port") from error
    if (
        parsed_origin.scheme != "https"
        or not parsed_origin.hostname
        or parsed_origin.username
        or parsed_origin.password
        or parsed_origin.path not in {"", "/"}
        or parsed_origin.query
        or parsed_origin.fragment
        or (origin_port is not None and not 1 <= origin_port <= 65535)
    ):
        raise PreflightFailure(
            "MARKINOTE_PUBLIC_ORIGIN must be an HTTPS origin without credentials or paths"
        )
    trusted_hosts_raw = require_value(values, "MARKINOTE_TRUSTED_HOSTS", "api")
    try:
        trusted_hosts = json.loads(trusted_hosts_raw)
    except json.JSONDecodeError as error:
        raise PreflightFailure("MARKINOTE_TRUSTED_HOSTS must be a JSON array") from error
    if not isinstance(trusted_hosts, list) or any(
        not isinstance(host, str) or not host.strip() for host in trusted_hosts
    ):
        raise PreflightFailure("MARKINOTE_TRUSTED_HOSTS must contain non-empty hostnames")
    normalized_hosts = {host.strip().casefold().rstrip(".") for host in trusted_hosts}
    if "*" in normalized_hosts or any(
        not HOSTNAME_PATTERN.fullmatch(host[2:] if host.startswith("*.") else host)
        for host in normalized_hosts
    ):
        raise PreflightFailure(
            "MARKINOTE_TRUSTED_HOSTS entries must be hostnames and cannot contain '*'"
        )
    public_hostname = parsed_origin.hostname.casefold().rstrip(".")
    if not any(trusted_host_matches(public_hostname, host) for host in normalized_hosts):
        raise PreflightFailure(
            "MARKINOTE_TRUSTED_HOSTS must include the public hostname and cannot contain '*'"
        )
    required_internal_hosts = {"127.0.0.1", "api"}
    if not required_internal_hosts.issubset(normalized_hosts):
        raise PreflightFailure(
            "MARKINOTE_TRUSTED_HOSTS must include 127.0.0.1 and api for internal health traffic"
        )

    for key in (
        "MARKINOTE_MAX_LIBRARY_BYTES",
        "MARKINOTE_TRASH_MAX_ITEMS",
        "MARKINOTE_TRASH_MAX_BYTES",
    ):
        raw_value = require_value(values, key, "api")
        try:
            value = int(raw_value)
        except ValueError as error:
            raise PreflightFailure(f"{key} must be a positive integer") from error
        if value <= 0:
            raise PreflightFailure(f"{key} must be a positive integer")

    stream_limit_bounds = {
        "MARKINOTE_AI_MAX_PROVIDER_FRAME_BYTES": (1_024, 4 * 1_024 * 1_024),
        "MARKINOTE_AI_MAX_PROVIDER_EVENTS": (1, 100_000),
        "MARKINOTE_AI_MAX_PROVIDER_BYTES": (4_096, 64 * 1_024 * 1_024),
        "MARKINOTE_AI_MAX_CONTENT_BYTES_PER_ROUND": (1_024, 16 * 1_024 * 1_024),
        "MARKINOTE_AI_MAX_CONTENT_BYTES_TOTAL": (1_024, 32 * 1_024 * 1_024),
        "MARKINOTE_AI_MAX_TOOL_ARGUMENTS_BYTES": (256, 1_024 * 1_024),
        "MARKINOTE_AI_MAX_SSE_EVENT_BYTES": (1_024, 4 * 1_024 * 1_024),
        "MARKINOTE_AI_MAX_STREAM_SECONDS": (1, 3_600),
    }
    stream_limits: dict[str, int] = {}
    for key, (minimum, maximum) in stream_limit_bounds.items():
        raw_value = require_value(values, key, "api")
        try:
            stream_limits[key] = int(raw_value)
        except ValueError as error:
            raise PreflightFailure(f"{key} must be an integer within policy") from error
        if not minimum <= stream_limits[key] <= maximum:
            raise PreflightFailure(f"{key} is outside the bounded stream policy")
    if (
        stream_limits["MARKINOTE_AI_MAX_CONTENT_BYTES_TOTAL"]
        < stream_limits["MARKINOTE_AI_MAX_CONTENT_BYTES_PER_ROUND"]
    ):
        raise PreflightFailure("AI total content limit must cover the per-round limit")
    if (
        stream_limits["MARKINOTE_AI_MAX_PROVIDER_BYTES"]
        < stream_limits["MARKINOTE_AI_MAX_CONTENT_BYTES_TOTAL"]
    ):
        raise PreflightFailure("AI provider byte limit must cover the total content limit")
    if (
        stream_limits["MARKINOTE_AI_MAX_SSE_EVENT_BYTES"]
        < stream_limits["MARKINOTE_AI_MAX_TOOL_ARGUMENTS_BYTES"]
        * AI_SSE_TOOL_ARGUMENT_COPIES
        + AI_SSE_TOOL_EVENT_OVERHEAD_BYTES
    ):
        raise PreflightFailure(
            "AI SSE event limit must cover both tool-argument copies and the result envelope"
        )


def validate_model(model: dict[str, Any]) -> dict[str, object]:
    api = service(model, "api")
    gateway = service(model, "gateway")
    migrate = service(model, "migrate")
    validate_network_topology(model)

    api_reference = immutable_reference(api.get("image"), "api")
    gateway_reference = immutable_reference(gateway.get("image"), "gateway")
    migrate_reference = immutable_reference(migrate.get("image"), "migrate")
    if migrate_reference != api_reference:
        raise PreflightFailure("migrate must use the exact API image digest")
    if gateway_reference.rsplit("@", 1)[1] == api_reference.rsplit("@", 1)[1]:
        raise PreflightFailure("api and gateway must use distinct image digests")
    for name, value in (("api", api), ("gateway", gateway), ("migrate", migrate)):
        if value.get("pull_policy") != "always":
            raise PreflightFailure(f"{name} must retain pull_policy=always")
        if "build" in value:
            raise PreflightFailure(f"{name} must not retain a production source-build path")
        validate_runtime_hardening(value, name)

    validate_api_environment(api)
    deploy = api.get("deploy")
    if isinstance(deploy, dict) and deploy.get("replicas") not in {None, 1}:
        raise PreflightFailure("startup reconciliation requires exactly one API replica")
    api_environment = environment(api, "api")
    migrate_environment = environment(migrate, "migrate")
    if migrate_environment.get("MARKINOTE_ENVIRONMENT") != "production":
        raise PreflightFailure("migrate must run with MARKINOTE_ENVIRONMENT=production")
    if migrate_environment.get("MARKINOTE_AUTO_CREATE_DATABASE") != "false":
        raise PreflightFailure("migrate must never auto-create the production schema")
    if migrate_environment.get("MARKINOTE_APP_VERSION") != api_environment.get(
        "MARKINOTE_APP_VERSION"
    ):
        raise PreflightFailure("migrate and api must report the same application version")

    return {
        "status": "ok",
        "apiImage": api_reference,
        "gatewayImage": gateway_reference,
        "applicationVersion": api_environment["MARKINOTE_APP_VERSION"],
        "migrateMatchesApi": True,
        "implicitSchemaCreation": False,
        "sourceBuildAvailable": False,
        "publicOriginPortValid": True,
        "internalHealthHostsTrusted": True,
        "capacityLimitsPositive": True,
        "aiStreamLimitsBounded": True,
        "aiToolResultEnvelopeCovered": True,
        "startupReconciliation": {
            "enabled": True,
            "singleWriterAttested": True,
            "boundedLimit": True,
            "apiReplicas": 1,
        },
        "testProviderFixtureConfigured": False,
        "networkTopology": {
            "backendInternal": True,
            "telemetryInternal": True,
            "apiDedicatedEgress": True,
            "apiPortPublished": False,
            "gatewayOnEgress": False,
            "databaseOnEgress": False,
        },
        "runtimeHardening": {
            "readOnlyRoot": True,
            "capDropAll": True,
            "noNewPrivileges": True,
        },
    }


def main() -> int:
    try:
        evidence = validate_model(render_compose(parse_args()))
    except PreflightFailure as error:
        print(f"production compose preflight failed: {error}", file=sys.stderr)
        return 2
    print(json.dumps(evidence, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
