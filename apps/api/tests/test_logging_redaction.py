from __future__ import annotations

import json
import logging
import sys

from markinote_api.platform.logging import JsonFormatter, SafeTextFormatter, request_id_var


def test_json_formatter_is_allowlisted_and_omits_messages_from_exceptions() -> None:
    try:
        raise ValueError("exception-secret document.md")
    except ValueError:
        exception = sys.exc_info()

    record = logging.LogRecord(
        name="markinote.test",
        level=logging.ERROR,
        pathname=__file__,
        lineno=14,
        msg="provider failed for %s",
        args=("argument-secret",),
        exc_info=exception,
    )
    record.request_id = "req-safe"
    record.run_id = "run-safe"
    record.api_key = "extra-secret"
    record.details = {"content": "document-secret"}

    token = request_id_var.set("req-context")
    try:
        payload = json.loads(JsonFormatter().format(record))
    finally:
        request_id_var.reset(token)

    serialized = json.dumps(payload)
    assert payload["message"] == "provider failed for %s"
    assert payload["request_id"] == "req-safe"
    assert payload["run_id"] == "run-safe"
    assert payload["exception"]["type"] == "ValueError"
    assert payload["exception"]["frames"]
    assert "api_key" not in payload
    assert "details" not in payload
    for secret in (
        "argument-secret",
        "exception-secret",
        "document.md",
        "extra-secret",
        "document-secret",
    ):
        assert secret not in serialized


def test_json_formatter_redacts_credentials_embedded_in_event_templates() -> None:
    record = logging.LogRecord(
        name="markinote.test",
        level=logging.WARNING,
        pathname=__file__,
        lineno=54,
        msg="Authorization Bearer top-secret; api_key=sk-private password=hunter2",
        args=(),
        exc_info=None,
    )

    serialized = JsonFormatter().format(record)

    assert serialized.count("[REDACTED]") == 3
    assert "top-secret" not in serialized
    assert "sk-private" not in serialized
    assert "hunter2" not in serialized
    text = SafeTextFormatter().format(record)
    assert "[REDACTED]" in text
    assert "top-secret" not in text


def test_json_formatter_redacts_and_bounds_allowlisted_metadata() -> None:
    record = logging.LogRecord(
        name="markinote.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=80,
        msg="bounded metadata",
        args=(),
        exc_info=None,
    )
    record.run_id = "access_token:do-not-log"
    record.command_id = "sk-provider-secret-value"
    record.conversation_id = "conversation\nforged" + ("x" * 400)
    record.duration_ms = "not-a-number"
    record.http_status = 200
    record.tool_name = {"content": "must-not-be-serialized"}

    payload = json.loads(JsonFormatter().format(record))
    serialized = json.dumps(payload)

    assert payload["run_id"] == "[REDACTED]"
    assert payload["command_id"] == "[REDACTED]"
    assert "\n" not in payload["conversation_id"]
    assert len(payload["conversation_id"]) == 256
    assert "duration_ms" not in payload
    assert payload["http_status"] == 200
    assert "tool_name" not in payload
    for secret in ("do-not-log", "provider-secret-value", "must-not-be-serialized"):
        assert secret not in serialized
