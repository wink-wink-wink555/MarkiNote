"""Capture a small reproducible gateway latency baseline without secret data."""

from __future__ import annotations

import argparse
import hashlib
import http.cookiejar
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

SYNTHETIC_MARKDOWN = """# Synthetic performance fixture

This deterministic document measures the same rendering path on every run.

## Structured content

| component | status | count |
| --- | --- | ---: |
| gateway | ready | 1 |
| document | synthetic | 3 |

```python
def deterministic(value: int) -> int:
    return value * 2
```

- item one
- item two
- item three

The payload contains no production document data or credentials.
"""


class BaselineFailure(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Measure gateway p50/p95/p99 latency samples.")
    parser.add_argument("--warmup", type=int, default=3)
    parser.add_argument("--samples", type=int, default=20)
    parser.add_argument("--minimum-interval-ms", type=float, default=125.0)
    args = parser.parse_args()
    if args.warmup < 0 or args.samples < 5 or args.minimum_interval_ms < 0:
        parser.error("warmup must be >= 0, samples >= 5, and interval >= 0")
    return args


def request(
    opener: urllib.request.OpenerDirector,
    method: str,
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    payload: Mapping[str, Any] | None = None,
) -> tuple[int, Mapping[str, str], bytes, float]:
    request_headers = dict(headers or {})
    body: bytes | None = None
    if payload is not None:
        request_headers["Content-Type"] = "application/json"
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    outgoing = urllib.request.Request(url, data=body, headers=request_headers, method=method)
    started = time.perf_counter_ns()
    try:
        with opener.open(outgoing, timeout=15) as response:
            status = response.status
            response_headers = dict(response.headers.items())
            response_body = response.read()
    except urllib.error.HTTPError as error:
        status = error.code
        response_headers = dict(error.headers.items())
        response_body = error.read()
    except OSError as error:
        raise BaselineFailure(
            f"{method} {urllib.parse.urlsplit(url).path} could not connect"
        ) from error
    elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
    return status, response_headers, response_body, elapsed_ms


def header(headers: Mapping[str, str], name: str) -> str:
    return next((value for key, value in headers.items() if key.casefold() == name.casefold()), "")


def json_object(body: bytes, operation: str) -> dict[str, Any]:
    try:
        value = json.loads(body)
    except json.JSONDecodeError as error:
        raise BaselineFailure(f"{operation} returned invalid JSON") from error
    if not isinstance(value, dict):
        raise BaselineFailure(f"{operation} returned non-object JSON")
    return value


def require_status(status: int, expected: int, operation: str) -> None:
    if status != expected:
        raise BaselineFailure(f"{operation} returned {status}, expected {expected}")


def percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def summary(values: list[float]) -> dict[str, float | int]:
    return {
        "samples": len(values),
        "minMs": round(min(values), 3),
        "p50Ms": round(percentile(values, 0.50), 3),
        "p95Ms": round(percentile(values, 0.95), 3),
        "p99Ms": round(percentile(values, 0.99), 3),
        "maxMs": round(max(values), 3),
    }


def main() -> int:
    args = parse_args()
    token = os.environ.get("MARKINOTE_ACCESS_TOKEN", "")
    if not token:
        raise BaselineFailure("MARKINOTE_ACCESS_TOKEN is required")
    configured_base_url = os.environ.get(
        "MARKINOTE_BASELINE_BASE_URL",
        os.environ.get(
            "MARKINOTE_SMOKE_BASE_URL",
            f"http://127.0.0.1:{os.environ.get('MARKINOTE_HTTP_PORT', '8080')}",
        ),
    )
    try:
        parsed_target = urllib.parse.urlsplit(configured_base_url)
        target_host = parsed_target.hostname
        target_port = parsed_target.port
    except ValueError as error:
        raise BaselineFailure("baseline target is not a valid HTTP(S) origin") from error
    if (
        parsed_target.scheme not in {"http", "https"}
        or not target_host
        or parsed_target.username
        or parsed_target.password
        or parsed_target.path not in {"", "/"}
        or parsed_target.query
        or parsed_target.fragment
    ):
        raise BaselineFailure("baseline target must be an HTTP(S) origin without credentials")
    safe_host = f"[{target_host}]" if ":" in target_host else target_host
    safe_authority = f"{safe_host}:{target_port}" if target_port is not None else safe_host
    base_url = f"{parsed_target.scheme}://{safe_authority}"

    cookie_jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        urllib.request.HTTPCookieProcessor(cookie_jar),
    )
    status, exchange_headers, _, authentication_ms = request(
        opener,
        "POST",
        f"{base_url}/auth/access-token",
        headers={"Origin": base_url},
        payload={"accessToken": token},
    )
    require_status(status, 200, "cookie authentication")
    set_cookie = header(exchange_headers, "Set-Cookie")
    if "HttpOnly" not in set_cookie or token in set_cookie:
        raise BaselineFailure("cookie authentication security contract changed")

    def gateway_index() -> float:
        response_status, headers, body, elapsed = request(opener, "GET", f"{base_url}/")
        require_status(response_status, 200, "gateway index")
        if "text/html" not in header(headers, "Content-Type") or not body:
            raise BaselineFailure("gateway index response contract changed")
        return elapsed

    def document_list() -> float:
        response_status, _, body, elapsed = request(
            opener,
            "GET",
            f"{base_url}/api/v1/documents",
        )
        require_status(response_status, 200, "document list")
        if not isinstance(json_object(body, "document list").get("items"), list):
            raise BaselineFailure("document list response contract changed")
        return elapsed

    def markdown_render() -> float:
        response_status, _, body, elapsed = request(
            opener,
            "POST",
            f"{base_url}/api/v1/rendering/preview",
            headers={"Origin": base_url},
            payload={"markdown": SYNTHETIC_MARKDOWN},
        )
        require_status(response_status, 200, "Markdown render")
        if not isinstance(json_object(body, "Markdown render").get("html"), str):
            raise BaselineFailure("Markdown render response contract changed")
        return elapsed

    operations: dict[str, Callable[[], float]] = {
        "gatewayIndex": gateway_index,
        "documentList": document_list,
        "markdownRender": markdown_render,
    }
    samples = {name: [] for name in operations}
    interval_seconds = args.minimum_interval_ms / 1000
    for iteration in range(args.warmup + args.samples):
        for name, operation in operations.items():
            elapsed = operation()
            if iteration >= args.warmup:
                samples[name].append(elapsed)
            if interval_seconds:
                time.sleep(interval_seconds)

    evidence = {
        "schemaVersion": 1,
        "status": "ok",
        "capturedAt": datetime.now(UTC).isoformat(),
        "target": {"scheme": parsed_target.scheme, "authority": safe_authority},
        "method": {
            "warmupIterations": args.warmup,
            "sampleIterations": args.samples,
            "minimumIntervalMs": args.minimum_interval_ms,
            "percentile": "linear interpolation over sorted samples",
            "thresholdEnforced": False,
        },
        "fixture": {
            "bytes": len(SYNTHETIC_MARKDOWN.encode()),
            "sha256": hashlib.sha256(SYNTHETIC_MARKDOWN.encode()).hexdigest(),
        },
        "authentication": {
            "exchangeMs": round(authentication_ms, 3),
            "httpOnlyCookie": True,
            "rawTokenReflected": False,
        },
        "operations": {name: summary(values) for name, values in samples.items()},
    }
    print(json.dumps(evidence, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BaselineFailure as error:
        print(f"gateway performance baseline failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
