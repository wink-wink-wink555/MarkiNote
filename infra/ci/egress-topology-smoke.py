"""Prove the API has a dedicated outbound path without widening ingress."""

from __future__ import annotations

import json
import os
import re
import secrets
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = REPOSITORY_ROOT / "infra" / "compose.yaml"
FIXTURE_CODE = r'''
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_args):
        return

    def send_chunk(self, payload):
        self.wfile.write(f"{len(payload):x}\r\n".encode("ascii"))
        self.wfile.write(payload)
        self.wfile.write(b"\r\n")
        self.wfile.flush()

    def do_GET(self):
        if self.path != "/provider-health":
            self.send_error(404)
            return
        body = b'{"status":"ok"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path != "/chat/completions":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            request = json.loads(self.rfile.read(length))
        except (ValueError, json.JSONDecodeError):
            self.send_error(400)
            return
        authorization = self.headers.get("Authorization", "")
        if not authorization.startswith("Bearer ") or request.get("stream") is not True:
            self.send_error(401)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache, no-transform")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        first = (
            b'data: {"choices":[{"delta":{"content":"fixture-token-one"},'
            b'"finish_reason":null}]}\n\n'
        )
        second = (
            b'data: {"choices":[{"delta":{"content":" fixture-token-two"},'
            b'"finish_reason":null}]}\n\n'
        )
        self.send_chunk(first)
        time.sleep(2.25)
        self.send_chunk(second)
        time.sleep(0.5)
        self.send_chunk(b"data: [DONE]\n\n")
        self.wfile.write(b"0\r\n\r\n")
        self.wfile.flush()


ThreadingHTTPServer(("0.0.0.0", 8099), Handler).serve_forever()
'''


class EgressSmokeFailure(RuntimeError):
    pass


def execute(
    command: list[str],
    *,
    label: str,
    environment: dict[str, str] | None = None,
    check: bool = True,
    timeout: int = 60,
) -> subprocess.CompletedProcess[str]:
    print(f"[egress-smoke] {label}", file=sys.stderr, flush=True)
    try:
        completed = subprocess.run(
            command,
            cwd=REPOSITORY_ROOT,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        if check:
            raise EgressSmokeFailure(f"{label} could not complete") from error
        return subprocess.CompletedProcess(command, 1, "", "")
    if check and completed.returncode != 0:
        raise EgressSmokeFailure(f"{label} failed with exit code {completed.returncode}")
    return completed


def compose(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return execute(
        ["docker", "compose", "-f", str(COMPOSE_FILE), *arguments],
        label=f"compose {' '.join(arguments[:4])}",
        check=check,
    )


def json_object(command: list[str], label: str) -> dict[str, Any]:
    completed = execute(command, label=label)
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise EgressSmokeFailure(f"{label} returned invalid JSON") from error
    if isinstance(value, list) and len(value) == 1 and isinstance(value[0], dict):
        return value[0]
    if not isinstance(value, dict):
        raise EgressSmokeFailure(f"{label} returned an unexpected model")
    return value


def container_id(service_name: str) -> str:
    value = compose("ps", "--quiet", service_name).stdout.strip()
    if not value or "\n" in value:
        raise EgressSmokeFailure(f"expected one running {service_name} container")
    return value


def container_model(identifier: str) -> dict[str, Any]:
    return json_object(["docker", "container", "inspect", identifier], f"inspect {identifier}")


def attached_networks(container: dict[str, Any]) -> dict[str, Any]:
    network_settings = container.get("NetworkSettings")
    networks = network_settings.get("Networks") if isinstance(network_settings, dict) else None
    if not isinstance(networks, dict):
        raise EgressSmokeFailure("container network metadata is missing")
    return networks


def logical_networks(actual_names: set[str]) -> dict[str, tuple[str, dict[str, Any]]]:
    result: dict[str, tuple[str, dict[str, Any]]] = {}
    for actual_name in actual_names:
        model = json_object(
            ["docker", "network", "inspect", actual_name],
            f"inspect network {actual_name}",
        )
        labels = model.get("Labels")
        logical_name = (
            labels.get("com.docker.compose.network") if isinstance(labels, dict) else None
        )
        if isinstance(logical_name, str):
            result[logical_name] = (actual_name, model)
    return result


def require(condition: bool, message: str) -> None:
    if not condition:
        raise EgressSmokeFailure(message)


def render_compose() -> dict[str, Any]:
    completed = compose("--profile", "*", "config", "--format", "json")
    try:
        model = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise EgressSmokeFailure("Compose topology was not valid JSON") from error
    if not isinstance(model, dict):
        raise EgressSmokeFailure("Compose topology was not an object")
    return model


def service_network_names(service_model: object) -> set[str]:
    if not isinstance(service_model, dict):
        return set()
    networks = service_model.get("networks")
    if isinstance(networks, dict):
        return {str(name) for name in networks}
    if isinstance(networks, list):
        return {str(name) for name in networks}
    return set()


def main() -> int:
    api_id = container_id("api")
    gateway_id = container_id("gateway")
    api = container_model(api_id)
    gateway = container_model(gateway_id)
    api_actual_networks = set(attached_networks(api))
    gateway_actual_networks = set(attached_networks(gateway))
    api_logical_networks = logical_networks(api_actual_networks)
    require(
        {"backend", "telemetry", "egress"}.issubset(api_logical_networks),
        "running API is missing backend, telemetry, or egress",
    )
    require(
        api_logical_networks["backend"][1].get("Internal") is True,
        "backend is not internal at runtime",
    )
    require(
        api_logical_networks["telemetry"][1].get("Internal") is True,
        "telemetry is not internal at runtime",
    )
    require(
        api_logical_networks["egress"][1].get("Internal") is False,
        "egress is unexpectedly internal",
    )
    egress_name = api_logical_networks["egress"][0]
    require(egress_name not in gateway_actual_networks, "gateway is attached to API egress")
    api_host_config = api.get("HostConfig")
    require(
        isinstance(api_host_config, dict) and not api_host_config.get("PortBindings"),
        "API unexpectedly publishes a host port",
    )
    api_config = api.get("Config")
    api_environment = api_config.get("Env") if isinstance(api_config, dict) else None
    require(isinstance(api_environment, list), "API environment metadata is missing")
    require(
        "MARKINOTE_AI_PROVIDER_FIXTURE_URL=http://fake-provider:8099" in api_environment,
        "API is not pinned to the isolated test provider fixture",
    )

    rendered = render_compose()
    services = rendered.get("services")
    require(isinstance(services, dict), "rendered Compose services are missing")
    for service_name, service_model in services.items():
        if service_name != "api":
            require(
                "egress" not in service_network_names(service_model),
                f"{service_name} is attached to API egress",
            )

    raw_run = f"{secrets.token_hex(4)}-{int(time.time())}"
    suffix = re.sub(r"[^a-z0-9-]", "-", raw_run.casefold())[:24]
    fixture_name = f"markinote-egress-fixture-{suffix}"
    api_image = api.get("Image")
    require(isinstance(api_image, str) and bool(api_image), "API image identity is missing")
    created = False
    try:
        execute(
            [
                "docker",
                "run",
                "--detach",
                "--name",
                fixture_name,
                "--network",
                egress_name,
                "--network-alias",
                "fake-provider",
                "--read-only",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges:true",
                "--tmpfs",
                "/tmp:rw,noexec,nosuid,size=16m,uid=10001,gid=10001,mode=1777",
                "--entrypoint",
                "python",
                api_image,
                "-c",
                FIXTURE_CODE,
            ],
            label="start credential-free fake provider",
        )
        created = True
        fixture = container_model(fixture_name)
        require(
            set(attached_networks(fixture)) == {egress_name},
            "fake provider is not isolated to the egress network",
        )
        fixture_config = fixture.get("Config")
        fixture_environment = (
            fixture_config.get("Env") if isinstance(fixture_config, dict) else None
        )
        require(isinstance(fixture_environment, list), "fake provider environment is missing")
        forbidden_names = (
            "MARKINOTE_ACCESS_TOKEN=",
            "MARKINOTE_SECRET_KEY=",
            "MARKINOTE_AI_API_KEY=",
            "MARKINOTE_DATABASE_URL=",
        )
        require(
            not any(
                isinstance(item, str) and item.startswith(forbidden_names)
                for item in fixture_environment
            ),
            "fake provider received an application credential",
        )
        fixture_host_config = fixture.get("HostConfig")
        require(
            isinstance(fixture_host_config, dict)
            and not fixture_host_config.get("PortBindings"),
            "fake provider unexpectedly publishes a host port",
        )

        probe = (
            "import json, urllib.request; "
            "value=json.load(urllib.request.urlopen("
            "'http://fake-provider:8099/provider-health', timeout=2)); "
            "assert value == {'status':'ok'}"
        )
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            completed = execute(
                ["docker", "exec", api_id, "python", "-c", probe],
                label="probe fake provider DNS and TCP from API",
                check=False,
                timeout=5,
            )
            if completed.returncode == 0:
                break
            time.sleep(0.2)
        else:
            raise EgressSmokeFailure("API could not reach fake provider over DNS/TCP")

        gateway_smoke = execute(
            [sys.executable, str(REPOSITORY_ROOT / "infra" / "ci" / "gateway-document-smoke.py")],
            label="exercise full gateway flow against isolated provider fixture",
            environment={**os.environ, "MARKINOTE_PROVIDER_FIXTURE_ACTIVE": "true"},
            timeout=45,
        )
        try:
            gateway_evidence = json.loads(gateway_smoke.stdout)
        except json.JSONDecodeError as error:
            raise EgressSmokeFailure("gateway smoke returned invalid evidence JSON") from error
        require(
            isinstance(gateway_evidence, dict)
            and gateway_evidence.get("status") == "ok"
            and gateway_evidence.get("providerFixture") is True
            and gateway_evidence.get("realProviderContacted") is False,
            "gateway smoke did not prove isolated provider use",
        )
        evidence_path = os.environ.get("MARKINOTE_GATEWAY_EVIDENCE_PATH", "")
        if evidence_path:
            target = Path(evidence_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                json.dumps(gateway_evidence, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )
    finally:
        if created:
            execute(
                ["docker", "rm", "--force", fixture_name],
                label="remove fake provider",
                check=False,
            )

    removed = execute(
        ["docker", "container", "inspect", fixture_name],
        label="verify fake provider removal",
        check=False,
    ).returncode != 0
    require(removed, "fake provider was not removed")
    print(
        json.dumps(
            {
                "status": "ok",
                "dnsAndTcpReachable": True,
                "apiPortPublished": False,
                "backendInternal": True,
                "telemetryInternal": True,
                "dedicatedEgress": True,
                "gatewayOnEgress": False,
                "databaseOnEgress": False,
                "fakeProviderCredentialFree": True,
                "fakeProviderPortPublished": False,
                "fullIncrementalSse": True,
                "realProviderContacted": False,
                "resourcesRemoved": True,
            },
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except EgressSmokeFailure as error:
        print(f"egress topology smoke failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
