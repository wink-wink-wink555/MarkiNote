"""Exercise the deployed same-origin gateway without mocks or third-party clients."""
from __future__ import annotations

import http.client
import http.cookiejar
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from typing import Any


class GatewaySmokeFailure(RuntimeError):
    pass


def request(
    opener: urllib.request.OpenerDirector,
    method: str,
    url: str,
    *,
    expected_status: int,
    headers: Mapping[str, str] | None = None,
    payload: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], Mapping[str, str]]:
    request_headers = dict(headers or {})
    body: bytes | None = None
    if payload is not None:
        request_headers["Content-Type"] = "application/json"
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    outgoing = urllib.request.Request(url, data=body, headers=request_headers, method=method)
    try:
        with opener.open(outgoing, timeout=10) as response:
            status = response.status
            raw_body = response.read()
            response_headers = dict(response.headers.items())
    except urllib.error.HTTPError as error:
        status = error.code
        raw_body = error.read()
        response_headers = dict(error.headers.items())
    except OSError as error:
        raise GatewaySmokeFailure(f"{method} {url} failed to connect: {type(error).__name__}") from error

    if status != expected_status:
        preview = raw_body.decode("utf-8", errors="replace")[:500]
        raise GatewaySmokeFailure(
            f"{method} {urllib.parse.urlsplit(url).path} returned {status}, "
            f"expected {expected_status}: {preview}"
        )
    if not raw_body:
        return {}, response_headers
    try:
        parsed = json.loads(raw_body)
    except json.JSONDecodeError as error:
        raise GatewaySmokeFailure(
            f"{method} {urllib.parse.urlsplit(url).path} did not return JSON"
        ) from error
    if not isinstance(parsed, dict):
        raise GatewaySmokeFailure(f"{method} {urllib.parse.urlsplit(url).path} returned non-object JSON")
    return parsed, response_headers


def raw_request(
    opener: urllib.request.OpenerDirector,
    url: str,
    *,
    expected_status: int,
) -> tuple[bytes, Mapping[str, str]]:
    outgoing = urllib.request.Request(url, method="GET")
    try:
        with opener.open(outgoing, timeout=10) as response:
            status = response.status
            body = response.read()
            response_headers = dict(response.headers.items())
    except urllib.error.HTTPError as error:
        status = error.code
        body = error.read()
        response_headers = dict(error.headers.items())
    except OSError as error:
        raise GatewaySmokeFailure(
            f"GET {urllib.parse.urlsplit(url).path} failed to connect: {type(error).__name__}"
        ) from error
    if status != expected_status:
        raise GatewaySmokeFailure(
            f"GET {urllib.parse.urlsplit(url).path} returned {status}, expected {expected_status}"
        )
    return body, response_headers


def sse_request(
    opener: urllib.request.OpenerDirector,
    url: str,
    *,
    headers: Mapping[str, str],
    payload: Mapping[str, Any],
) -> tuple[str, Mapping[str, str], float, list[tuple[str, float]]]:
    request_headers = {**headers, "Accept": "text/event-stream", "Content-Type": "application/json"}
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    outgoing = urllib.request.Request(url, data=body, headers=request_headers, method="POST")
    started = time.monotonic()
    first_event_seconds: float | None = None
    event_timings: list[tuple[str, float]] = []
    lines: list[bytes] = []
    try:
        with opener.open(outgoing, timeout=30) as response:
            status = response.status
            response_headers = dict(response.headers.items())
            while line := response.readline():
                lines.append(line)
                if line.startswith(b"event: "):
                    observed_at = time.monotonic() - started
                    event_name = line[7:].decode("utf-8", errors="strict").strip()
                    event_timings.append((event_name, observed_at))
                    if first_event_seconds is None:
                        first_event_seconds = observed_at
    except urllib.error.HTTPError as error:
        status = error.code
        response_headers = dict(error.headers.items())
        lines = [error.read()]
    except (OSError, http.client.HTTPException) as error:
        raise GatewaySmokeFailure(
            f"POST {urllib.parse.urlsplit(url).path} SSE connection failed: {type(error).__name__}"
        ) from error

    raw_body = b"".join(lines)
    if status != 200:
        preview = raw_body.decode("utf-8", errors="replace")[:500]
        raise GatewaySmokeFailure(
            f"POST {urllib.parse.urlsplit(url).path} returned {status}, expected 200: {preview}"
        )
    if first_event_seconds is None:
        raise GatewaySmokeFailure("SSE response contained no event field")
    return raw_body.decode("utf-8"), response_headers, first_event_seconds, event_timings


def require(condition: bool, message: str) -> None:
    if not condition:
        raise GatewaySmokeFailure(message)


def main() -> None:
    token = os.environ.get("MARKINOTE_ACCESS_TOKEN", "")
    if not token:
        raise GatewaySmokeFailure("MARKINOTE_ACCESS_TOKEN is required")
    if (
        os.environ.get("MARKINOTE_PROVIDER_FIXTURE_ACTIVE", "").casefold() != "true"
        or os.environ.get("MARKINOTE_AI_PROVIDER_FIXTURE_URL", "")
        != "http://fake-provider:8099"
    ):
        raise GatewaySmokeFailure(
            "isolated provider fixture attestation is required; refusing a possible public request"
        )
    base_url = os.environ.get(
        "MARKINOTE_SMOKE_BASE_URL",
        f"http://127.0.0.1:{os.environ.get('MARKINOTE_HTTP_PORT', '8080')}",
    ).rstrip("/")
    run_id = os.environ.get("GITHUB_RUN_ID", "local")
    run_attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "1")
    document_name = f"ci-gateway-smoke-{run_id}-{run_attempt}.md"
    document_query = urllib.parse.urlencode({"path": document_name})
    origin_headers = {"Origin": base_url}

    cookie_jar = http.cookiejar.CookieJar()
    # The smoke must hit the selected gateway directly even on CI/workstations
    # that inject HTTP(S)_PROXY globally.
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        urllib.request.HTTPCookieProcessor(cookie_jar),
    )

    for path in ("/gateway-health", "/health/live", "/health/ready"):
        response, _ = request(opener, "GET", f"{base_url}{path}", expected_status=200)
        require(response.get("status") == "ok", f"{path} did not report ok")

    request(opener, "GET", f"{base_url}/api/v1", expected_status=401)
    exchanged, exchange_headers = request(
        opener,
        "POST",
        f"{base_url}/auth/access-token",
        expected_status=200,
        headers=origin_headers,
        payload={"accessToken": token},
    )
    require(exchanged == {"authenticated": True}, "token exchange response was unexpected")
    set_cookie = next(
        (value for name, value in exchange_headers.items() if name.casefold() == "set-cookie"),
        "",
    )
    require("HttpOnly" in set_cookie, "session cookie is not HttpOnly")
    require("SameSite=strict" in set_cookie, "session cookie is not SameSite=strict")
    require(token not in set_cookie, "raw access token was reflected into the session cookie")
    require(any(cookie.name == "markinote_access" for cookie in cookie_jar), "session cookie missing")

    api_root, _ = request(opener, "GET", f"{base_url}/api/v1", expected_status=200)
    expected_version = os.environ.get("MARKINOTE_VERSION", "")
    if expected_version:
        require(
            api_root.get("version") == expected_version,
            "API version does not match the configured release version",
        )
    providers, _ = request(
        opener,
        "GET",
        f"{base_url}/api/v1/agent/providers",
        expected_status=200,
    )
    server_key_configured = providers.get("serverKeyConfigured") is True
    if os.environ.get("MARKINOTE_EXPECT_SERVER_AI_KEY", "").casefold() == "true":
        require(server_key_configured, "server-managed AI key was not available inside the API")

    query_sentinel = os.environ.get(
        "MARKINOTE_QUERY_CREDENTIAL_SENTINEL",
        "gateway-query-secret-sentinel-must-not-appear",
    )
    for query_key in ("access_token", "api_key", "ToKeN"):
        rejected_body, rejected_headers = raw_request(
            opener,
            f"{base_url}/api/v1?{query_key}={urllib.parse.quote(query_sentinel)}",
            expected_status=400,
        )
        require(
            query_sentinel.encode() not in rejected_body,
            "gateway reflected a rejected query credential",
        )
        normalized_rejection_headers = {
            name.casefold(): value for name, value in rejected_headers.items()
        }
        require(
            normalized_rejection_headers.get("content-type", "").startswith("text/html")
            and "x-request-id" not in normalized_rejection_headers,
            "query credential rejection was forwarded to the instrumented application",
        )
    allowed_query, _ = request(
        opener,
        "GET",
        f"{base_url}/api/v1?tokenizer=normal-parameter",
        expected_status=200,
    )
    require(allowed_query.get("contract") == 1, "gateway overmatched a normal query key")

    # CI injects an application-level override that Settings accepts only for
    # the exact isolated ``fake-provider`` test origin. The synthetic key is
    # request-scoped and is never configured on the credential-free fixture.
    fixture_key = "ci-isolated-provider-fixture-key"
    sse_body, sse_headers, first_event_seconds, event_timings = sse_request(
        opener,
        f"{base_url}/api/v1/agent/chat",
        headers=origin_headers,
        payload={
            "message": "Verify the same-origin streaming contract.",
            "run_id": f"gateway-sse-{run_id}-{run_attempt}",
            "provider": "deepseek",
            "model": "deepseek-v4-flash",
            "api_key": fixture_key,
            "language": "en",
            "allow_write_tools": False,
        },
    )
    content_type = next(
        (value for name, value in sse_headers.items() if name.casefold() == "content-type"),
        "",
    )
    cache_control = next(
        (value for name, value in sse_headers.items() if name.casefold() == "cache-control"),
        "",
    )
    require(content_type.startswith("text/event-stream"), "gateway did not preserve SSE content type")
    require("no-cache" in cache_control, "gateway did not disable SSE response caching")
    require(first_event_seconds < 5, "NGINX buffered the initial SSE event")
    require(fixture_key not in sse_body, "transient provider key was reflected into the stream")

    sse_events: list[tuple[str, dict[str, Any]]] = []
    for block in sse_body.replace("\r\n", "\n").split("\n\n"):
        fields = {}
        for line in block.splitlines():
            if ": " in line:
                name, value = line.split(": ", 1)
                fields[name] = value
        if "event" not in fields or "data" not in fields:
            continue
        try:
            event_data = json.loads(fields["data"])
        except json.JSONDecodeError as error:
            raise GatewaySmokeFailure("gateway returned malformed SSE JSON") from error
        require(isinstance(event_data, dict), "SSE data was not an object")
        sse_events.append((fields["event"], event_data))

    require(len(sse_events) >= 4, "gateway returned an incomplete SSE stream")
    require(sse_events[0][0] == "conversation_id", "SSE stream did not start with conversation_id")
    require(sse_events[-1][0] == "done", "fixture SSE stream did not end with terminal done")
    token_payloads = [
        event[1].get("content")
        for event in sse_events
        if event[0] == "token"
    ]
    require(
        token_payloads == ["fixture-token-one", " fixture-token-two"],
        "fixture content chunks were not forwarded incrementally and in order",
    )
    token_timings = [observed_at for name, observed_at in event_timings if name == "token"]
    require(len(token_timings) == 2, "gateway did not expose both fixture token events")
    require(token_timings[0] < 2, "gateway buffered the first provider content event")
    require(
        token_timings[1] - token_timings[0] >= 2,
        "gateway collapsed the deliberately delayed provider chunks",
    )
    sequences = [event[1].get("sequence") for event in sse_events]
    require(
        all(event[1].get("schemaVersion") == 1 for event in sse_events),
        "SSE schemaVersion contract changed",
    )
    require(
        all(isinstance(value, int) for value in sequences)
        and sequences == sorted(set(sequences)),
        "SSE sequence contract changed",
    )

    created, _ = request(
        opener,
        "POST",
        f"{base_url}/api/v1/documents/files",
        expected_status=200,
        headers=origin_headers,
        payload={"path": "", "name": document_name, "content": "# Gateway smoke v1"},
    )
    require(created.get("success") is True and created.get("path") == document_name, "create failed")

    read_v1, _ = request(
        opener,
        "GET",
        f"{base_url}/api/v1/documents/content?{document_query}",
        expected_status=200,
    )
    version_v1 = read_v1.get("version")
    require(read_v1.get("content") == "# Gateway smoke v1", "initial content did not round-trip")
    require(isinstance(version_v1, str) and bool(version_v1), "initial version is missing")

    updated_markdown = "# Gateway smoke v2\n\nSaved through the same-origin gateway."
    saved, _ = request(
        opener,
        "PUT",
        f"{base_url}/api/v1/documents/content?{document_query}",
        expected_status=200,
        headers={**origin_headers, "If-Match": f'"{version_v1}"'},
        payload={"content": updated_markdown},
    )
    require(saved.get("success") is True and saved.get("version") != version_v1, "save failed")

    read_v2, _ = request(
        opener,
        "GET",
        f"{base_url}/api/v1/documents/content?{document_query}",
        expected_status=200,
    )
    require(read_v2.get("content") == updated_markdown, "saved content did not round-trip")

    previewed, _ = request(
        opener,
        "POST",
        f"{base_url}/api/v1/rendering/preview",
        expected_status=200,
        headers=origin_headers,
        payload={"markdown": updated_markdown},
    )
    html = previewed.get("html")
    require(isinstance(html, str) and "<h1" in html and "Gateway smoke v2" in html, "preview failed")

    deleted, _ = request(
        opener,
        "DELETE",
        f"{base_url}/api/v1/documents?{document_query}",
        expected_status=200,
        headers=origin_headers,
    )
    require(deleted.get("success") is True and deleted.get("item_type") == "file", "delete failed")

    print(
        json.dumps(
            {
                "status": "ok",
                "flow": "gateway-cookie-sse-document-crud-preview",
                "sseFirstEventMilliseconds": round(first_event_seconds * 1000, 3),
                "sseEvents": len(sse_events),
                "sseTokenGapMilliseconds": round((token_timings[1] - token_timings[0]) * 1000, 3),
                "providerFixture": True,
                "realProviderContacted": False,
                "queryCredentialsRejectedAtGateway": True,
                "queryCredentialSentinelReflected": False,
                "queryCredentialReachedApplication": False,
                "applicationVersion": api_root.get("version"),
                "serverKeyConfigured": server_key_configured,
                "document": document_name,
                "finalVersion": saved["version"],
            },
            separators=(",", ":"),
        )
    )


if __name__ == "__main__":
    try:
        main()
    except GatewaySmokeFailure as error:
        print(f"gateway smoke failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
