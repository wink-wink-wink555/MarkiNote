from __future__ import annotations

import builtins
import json
from contextlib import suppress
from pathlib import Path

import requests
from fastapi import FastAPI
from fastapi.testclient import TestClient

from markinote_api.config import Settings
from markinote_api.platform.telemetry import configure_telemetry

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def test_compose_does_not_expose_unreviewed_generic_otel_environment() -> None:
    reviewed_configuration = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            REPOSITORY_ROOT / "infra/compose.yaml",
            REPOSITORY_ROOT / "infra/compose.production.yaml",
            REPOSITORY_ROOT / ".env.example",
            REPOSITORY_ROOT / "README.md",
        )
    )
    lines = [line.strip() for line in reviewed_configuration.splitlines()]
    for forbidden in (
        "OTEL_SERVICE_NAME",
        "OTEL_RESOURCE_ATTRIBUTES",
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        "OTEL_EXPORTER_OTLP_PROTOCOL",
    ):
        assert not any(
            line.startswith(f"{forbidden}=") or line.startswith(f"{forbidden}:")
            for line in lines
        )


def test_telemetry_is_a_graceful_noop_without_optional_dependencies(monkeypatch) -> None:
    original_import = builtins.__import__

    def import_without_otel(name, *args, **kwargs):
        if name.startswith("opentelemetry"):
            raise ImportError("optional dependency unavailable")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_without_otel)
    app = FastAPI()

    assert configure_telemetry(app, Settings(environment="test", otel_enabled=True)) is False


def test_exported_server_and_requests_spans_never_contain_queries_or_credentials(
    monkeypatch,
) -> None:
    monkeypatch.setenv(
        "OTEL_INSTRUMENTATION_HTTP_CAPTURE_HEADERS_SERVER_REQUEST",
        "authorization,x-access-token,cookie",
    )
    monkeypatch.setenv(
        "OTEL_INSTRUMENTATION_HTTP_CAPTURE_HEADERS_CLIENT_REQUEST",
        "authorization,x-access-token,cookie",
    )

    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    from opentelemetry.instrumentation.requests import RequestsInstrumentor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    from opentelemetry.trace import SpanKind

    def provider_response(_adapter, request, **_kwargs):
        if "/failure" in request.url:
            raise requests.ConnectionError(
                "provider failed at https://provider.invalid/failure?access_token=exception-query-secret "
                "Authorization=exception-authorization-secret"
            )
        response = requests.Response()
        response.status_code = 200
        response.url = request.url
        response.request = request
        response._content = b"{}"
        return response

    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", provider_response)
    app = FastAPI()

    @app.get("/probe")
    def probe() -> dict[str, bool]:
        response = requests.get(
            "https://provider.invalid/v1/models?access_token=client-query-secret",
            headers={
                "Authorization": "Bearer client-authorization-secret",
                "X-Access-Token": "client-header-secret",
            },
            timeout=1,
        )
        with suppress(requests.ConnectionError):
            requests.get("https://provider.invalid/failure", timeout=1)
        return {"ok": response.status_code == 200}

    exporter = InMemorySpanExporter()
    settings = Settings(environment="test", otel_enabled=True)
    assert configure_telemetry(
        app,
        settings,
        span_exporter=exporter,
        set_global_provider=False,
    )
    provider = app.state.tracer_provider
    try:
        with TestClient(app) as client:
            response = client.get(
                "/probe?access_token=server-query-secret",
                headers={
                    "Authorization": "Bearer server-authorization-secret",
                    "X-Access-Token": "server-header-secret",
                    "Cookie": "markinote_access=server-cookie-secret",
                },
            )
        assert response.status_code == 200
        assert provider.force_flush()

        spans = exporter.get_finished_spans()
        assert any(span.kind == SpanKind.SERVER for span in spans)
        assert any(span.kind == SpanKind.CLIENT for span in spans)
        exception_events = [
            event
            for span in spans
            for event in span.events
            if event.name == "exception"
        ]
        assert exception_events
        assert all(
            "exception.message" not in (event.attributes or {})
            and "exception.stacktrace" not in (event.attributes or {})
            for event in exception_events
        )
        assert all(span.status.description is None for span in spans)
        exported = json.dumps(
            [
                {
                    "name": span.name,
                    "attributes": dict(span.attributes or {}),
                    "events": [
                        {"name": event.name, "attributes": dict(event.attributes or {})}
                        for event in span.events
                    ],
                    "status": {
                        "code": span.status.status_code.name,
                        "description": span.status.description,
                    },
                    "resource": dict(span.resource.attributes),
                }
                for span in spans
            ],
            ensure_ascii=False,
            default=str,
        )
        for sentinel in (
            "server-query-secret",
            "server-authorization-secret",
            "server-header-secret",
            "server-cookie-secret",
            "client-query-secret",
            "client-authorization-secret",
            "client-header-secret",
            "exception-query-secret",
            "exception-authorization-secret",
        ):
            assert sentinel not in exported
        assert "access_token" not in exported.casefold()
        assert not any(
            "query" in str(key).casefold()
            for span in spans
            for key in (span.attributes or {})
        )
    finally:
        FastAPIInstrumentor.uninstrument_app(app)
        RequestsInstrumentor().uninstrument()
        HTTPXClientInstrumentor().uninstrument()
        provider.shutdown()
