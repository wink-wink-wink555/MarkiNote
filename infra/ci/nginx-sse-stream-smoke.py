"""Prove that the built NGINX gateway forwards SSE before stream completion."""

from __future__ import annotations

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
from collections.abc import Mapping

FIXTURE_CODE = r'''
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_args):
        return

    def do_GET(self):
        if self.path != "/health/ready":
            self.send_error(404)
            return
        body = b'{"status":"ok"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path != "/api/v1/agent/chat":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        if length:
            self.rfile.read(length)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-transform")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Connection", "close")
        self.end_headers()
        first = {
            "schemaVersion": 1,
            "sequence": 0,
            "conversationId": "nginx-stream-fixture",
        }
        self.wfile.write(
            b"event: conversation_id\n"
            + b"data: "
            + json.dumps(first, separators=(",", ":")).encode()
            + b"\n\n"
        )
        self.wfile.flush()
        time.sleep(4)
        terminal = {"schemaVersion": 1, "sequence": 1, "status": "completed"}
        self.wfile.write(
            b"event: done\n"
            + b"data: "
            + json.dumps(terminal, separators=(",", ":")).encode()
            + b"\n\n"
        )
        self.wfile.flush()
        self.close_connection = True


ThreadingHTTPServer(("0.0.0.0", 8000), Handler).serve_forever()
'''


class StreamSmokeFailure(RuntimeError):
    pass


def execute(
    command: list[str],
    *,
    label: str,
    check: bool = True,
    timeout: int = 60,
) -> subprocess.CompletedProcess[str]:
    print(f"[nginx-sse-smoke] {label}", file=sys.stderr, flush=True)
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        if check:
            raise StreamSmokeFailure(f"{label} could not complete") from error
        return subprocess.CompletedProcess(command, 1, "", "")
    if check and completed.returncode != 0:
        raise StreamSmokeFailure(f"{label} failed with exit code {completed.returncode}")
    return completed


def image_id(reference: str) -> str:
    return execute(
        ["docker", "image", "inspect", reference, "--format", "{{.Id}}"],
        label=f"inspect {reference}",
    ).stdout.strip()


def wait_for_fixture(container: str) -> None:
    deadline = time.monotonic() + 15
    probe = (
        "import urllib.request; "
        "urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=1).read()"
    )
    while time.monotonic() < deadline:
        completed = execute(
            ["docker", "exec", container, "python", "-c", probe],
            label="wait for delayed SSE fixture",
            check=False,
            timeout=5,
        )
        if completed.returncode == 0:
            return
        time.sleep(0.2)
    raise StreamSmokeFailure("delayed SSE fixture did not become ready")


def available_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def wait_for_gateway(base_url: str) -> None:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        try:
            with opener.open(f"{base_url}/gateway-health", timeout=1) as response:
                if response.status == 200:
                    return
        except (OSError, urllib.error.URLError):
            time.sleep(0.2)
    raise StreamSmokeFailure("gateway did not become ready")


def consume_stream(base_url: str) -> tuple[list[tuple[str, dict[str, object], float]], Mapping[str, str]]:
    payload = json.dumps({"fixture": True}, separators=(",", ":")).encode()
    outgoing = urllib.request.Request(
        f"{base_url}/api/v1/agent/chat",
        data=payload,
        headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
        method="POST",
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    started = time.monotonic()
    events: list[tuple[str, dict[str, object], float]] = []
    current_event: str | None = None
    try:
        with opener.open(outgoing, timeout=15) as response:
            if response.status != 200:
                raise StreamSmokeFailure(f"gateway returned SSE status {response.status}")
            headers = {
                key.casefold(): ", ".join(response.headers.get_all(key) or [])
                for key in response.headers
            }
            while line := response.readline():
                decoded = line.decode().strip()
                if decoded.startswith("event: "):
                    current_event = decoded.removeprefix("event: ")
                elif decoded.startswith("data: ") and current_event is not None:
                    try:
                        data = json.loads(decoded.removeprefix("data: "))
                    except json.JSONDecodeError as error:
                        raise StreamSmokeFailure("gateway returned malformed SSE JSON") from error
                    if not isinstance(data, dict):
                        raise StreamSmokeFailure("gateway returned non-object SSE data")
                    events.append((current_event, data, time.monotonic() - started))
                    current_event = None
    except (OSError, urllib.error.URLError) as error:
        raise StreamSmokeFailure("gateway SSE request failed") from error
    return events, headers


def cleanup(container_names: list[str], network: str) -> bool:
    for container in container_names:
        execute(
            ["docker", "rm", "--force", container],
            label=f"remove isolated container {container}",
            check=False,
        )
    execute(
        ["docker", "network", "rm", network],
        label=f"remove isolated network {network}",
        check=False,
    )
    containers_removed = all(
        execute(
            ["docker", "container", "inspect", container],
            label=f"verify container removal {container}",
            check=False,
        ).returncode
        != 0
        for container in container_names
    )
    network_removed = (
        execute(
            ["docker", "network", "inspect", network],
            label=f"verify network removal {network}",
            check=False,
        ).returncode
        != 0
    )
    return containers_removed and network_removed


def require(condition: bool, message: str) -> None:
    if not condition:
        raise StreamSmokeFailure(message)


def main() -> int:
    version = os.environ.get("MARKINOTE_VERSION", "ci")
    api_image = f"{os.environ.get('MARKINOTE_API_IMAGE', 'markinote-api')}:{version}"
    gateway_image = f"{os.environ.get('MARKINOTE_GATEWAY_IMAGE', 'markinote-gateway')}:{version}"
    raw_run = os.environ.get("GITHUB_RUN_ID", "local") + "-" + os.environ.get(
        "GITHUB_RUN_ATTEMPT", "1"
    )
    safe_run = re.sub(r"[^a-z0-9-]+", "-", raw_run.casefold()).strip("-")[:20] or "local"
    suffix = f"{safe_run}-{secrets.token_hex(3)}"
    network = f"markinote-sse-{suffix}"
    api_container = f"markinote-sse-api-{suffix}"
    gateway_container = f"markinote-sse-gateway-{suffix}"
    created_containers: list[str] = []
    network_created = False
    gateway_port = available_loopback_port()
    evidence: dict[str, object] = {
        "status": "failed",
        "images": {"api": image_id(api_image), "gateway": image_id(gateway_image)},
    }

    try:
        # A normal private bridge keeps the published loopback port reachable
        # on Docker Desktop as well as Linux. Both containers run deterministic
        # local code and make no external requests, so the smoke has no network
        # service dependency.
        execute(["docker", "network", "create", network], label="create network")
        network_created = True
        execute(
            [
                "docker",
                "run",
                "--detach",
                "--name",
                api_container,
                "--network",
                network,
                "--network-alias",
                "api",
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
            label="start delayed SSE fixture",
        )
        created_containers.append(api_container)
        wait_for_fixture(api_container)
        execute(
            [
                "docker",
                "run",
                "--detach",
                "--name",
                gateway_container,
                "--network",
                network,
                "--publish",
                f"127.0.0.1:{gateway_port}:8080",
                "--read-only",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges:true",
                "--tmpfs",
                "/tmp:rw,noexec,nosuid,size=64m,uid=101,gid=101,mode=1777",
                gateway_image,
            ],
            label="start real NGINX gateway",
        )
        created_containers.append(gateway_container)
        base_url = f"http://127.0.0.1:{gateway_port}"
        wait_for_gateway(base_url)
        events, headers = consume_stream(base_url)

        require([event[0] for event in events] == ["conversation_id", "done"], "SSE event order changed")
        require(
            [event[1].get("sequence") for event in events] == [0, 1],
            "SSE sequence contract changed",
        )
        content_type = headers.get("content-type", "")
        cache_control = headers.get("cache-control", "")
        require(content_type.startswith("text/event-stream"), "NGINX changed the SSE content type")
        require("no-cache" in cache_control, "NGINX did not preserve the no-cache policy")
        require("no-transform" in cache_control, "NGINX did not preserve the no-transform policy")
        first_seconds = events[0][2]
        terminal_seconds = events[-1][2]
        require(first_seconds < 2, "NGINX withheld the first event until stream completion")
        require(terminal_seconds >= 3.5, "delayed terminal fixture completed too early")
        require(
            terminal_seconds - first_seconds >= 3,
            "SSE events were not observed incrementally through NGINX",
        )

        cleaned = cleanup(created_containers[::-1], network)
        created_containers.clear()
        network_created = False
        require(cleaned, "isolated SSE resources were not fully cleaned")
        evidence.update(
            {
                "status": "ok",
                "events": [event[0] for event in events],
                "firstEventMilliseconds": round(first_seconds * 1000, 3),
                "terminalEventMilliseconds": round(terminal_seconds * 1000, 3),
                "incrementalGapMilliseconds": round(
                    (terminal_seconds - first_seconds) * 1000,
                    3,
                ),
                "resourcesRemoved": cleaned,
            }
        )
        print(json.dumps(evidence, separators=(",", ":")))
        return 0
    finally:
        if created_containers:
            cleanup(created_containers[::-1], network)
        elif network_created:
            execute(
                ["docker", "network", "rm", network],
                label=f"remove isolated network {network}",
                check=False,
            )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except StreamSmokeFailure as error:
        print(f"NGINX SSE smoke failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
