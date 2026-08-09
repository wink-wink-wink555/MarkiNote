"""Optional OpenTelemetry setup.

The application remains operational without the optional otel dependency
group. Production enables it explicitly after configuring a collector.
"""
from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any, cast
from urllib.parse import urlsplit, urlunsplit

from fastapi import FastAPI

from markinote_api.config import Settings

LOGGER = logging.getLogger(__name__)

_QUERY_ATTRIBUTE_KEYS = frozenset(
    {
        "http.query",
        "http.request.query",
        "url.query",
        "url.query_string",
    }
)
_FULL_URL_ATTRIBUTE_KEYS = frozenset({"http.url", "url.full", "url.original"})
_TARGET_ATTRIBUTE_KEYS = frozenset({"http.target", "url.target"})
_SENSITIVE_ATTRIBUTE_MARKERS = (
    "access_token",
    "access.token",
    "api_key",
    "api.key",
    "authorization",
    "proxy_authorization",
    "proxy.authorization",
    "cookie",
    "set_cookie",
    "set.cookie",
)
_SENSITIVE_EVENT_ATTRIBUTE_KEYS = frozenset(
    {
        "exception.message",
        "exception.stacktrace",
    }
)


def _url_without_query(value: str) -> str:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return value.split("?", 1)[0].split("#", 1)[0]
    if parsed.scheme or parsed.netloc:
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
    return value.split("?", 1)[0].split("#", 1)[0]


def _sanitized_attributes(attributes: Any, *, event: bool = False) -> dict[str, Any]:
    if not isinstance(attributes, Mapping):
        return {}
    sanitized: dict[str, Any] = {}
    for raw_key, value in attributes.items():
        key = str(raw_key).casefold().replace("-", "_")
        if (
            key in _QUERY_ATTRIBUTE_KEYS
            or (event and key in _SENSITIVE_EVENT_ATTRIBUTE_KEYS)
            or any(marker in key for marker in _SENSITIVE_ATTRIBUTE_MARKERS)
        ):
            continue
        if key in _FULL_URL_ATTRIBUTE_KEYS or key in _TARGET_ATTRIBUTE_KEYS:
            value = _url_without_query(value) if isinstance(value, str) else value
        sanitized[str(raw_key)] = value
    return sanitized


def _sanitize_span(span: Any) -> None:
    """Remove query strings and credential-bearing data before export."""
    name = getattr(span, "_name", None)
    if isinstance(name, str) and ("?" in name or "#" in name):
        span._name = _url_without_query(name)
    span._attributes = _sanitized_attributes(getattr(span, "_attributes", None))
    for event in getattr(span, "_events", ()) or ():
        event._attributes = _sanitized_attributes(
            getattr(event, "_attributes", None),
            event=True,
        )
    for link in getattr(span, "_links", ()) or ():
        link._attributes = _sanitized_attributes(getattr(link, "_attributes", None))
    status = getattr(span, "_status", None)
    if status is not None and getattr(status, "description", None):
        # SDK exception status descriptions interpolate ``str(exception)``.
        # The status code remains useful while the unreviewed text is removed.
        status._description = None


class _SanitizingSpanProcessor:
    """Runs before the exporter processor and mutates only SDK-owned span attributes."""

    def on_start(self, span: Any, parent_context: Any = None) -> None:
        del span, parent_context

    def _on_ending(self, span: Any) -> None:
        # Newer SDKs invoke this hook before constructing the ReadableSpan,
        # which also guarantees exception events/status are scrubbed in time.
        _sanitize_span(span)

    def on_end(self, span: Any) -> None:
        _sanitize_span(span)

    def shutdown(self) -> None:
        return None

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        del timeout_millis
        return True


def configure_telemetry(
    app: FastAPI,
    settings: Settings,
    *,
    span_exporter: Any | None = None,
    set_global_provider: bool = True,
) -> bool:
    if not settings.otel_enabled:
        return False
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        from opentelemetry.instrumentation.requests import RequestsInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import SpanProcessor, TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        LOGGER.warning("OpenTelemetry is enabled but optional dependencies are unavailable")
        return False

    provider = TracerProvider(
        # Build an explicit allowlist rather than merging arbitrary
        # OTEL_RESOURCE_ATTRIBUTES into every exported span.
        resource=Resource(
            {
                "service.name": settings.otel_service_name,
                "service.version": settings.app_version,
                "deployment.environment": settings.environment,
            }
        )
    )
    provider.add_span_processor(cast(SpanProcessor, _SanitizingSpanProcessor()))
    provider.add_span_processor(
        BatchSpanProcessor(
            span_exporter or OTLPSpanExporter(endpoint=settings.otel_endpoint)
        )
    )
    if set_global_provider:
        trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(
        app,
        tracer_provider=provider,
        excluded_urls="/health/live,/health/ready,/metrics",
    )
    HTTPXClientInstrumentor().instrument(tracer_provider=provider)
    RequestsInstrumentor().instrument(tracer_provider=provider)
    app.state.tracer_provider = provider
    return True
