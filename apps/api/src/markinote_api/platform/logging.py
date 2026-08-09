"""Small dependency-free JSON logging setup with correlation context."""
from __future__ import annotations

import contextvars
import json
import logging
import math
import re
import traceback
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="")


class JsonFormatter(logging.Formatter):
    _reserved: ClassVar[set[str]] = set(logging.makeLogRecord({}).__dict__)
    # Log schemas are allowlisted. Arbitrary ``extra`` values can contain a
    # prompt, document body, request payload, credential, or user-controlled
    # path and must never become an accidental telemetry channel.
    _allowed_extra: ClassVar[set[str]] = {
        "agent_run_state",
        "backup_group_id",
        "command_id",
        "conversation_id",
        "duration_ms",
        "error_code",
        "http_method",
        "http_route",
        "http_status",
        "provider",
        "request_id",
        "run_id",
        "tool_name",
    }
    _credential_pattern: ClassVar[re.Pattern[str]] = re.compile(
        r"(?i)(?:bearer\s+[^\s,;]+|(?:api[_-]?key|access[_-]?token|password|secret)\s*[:=]\s*[^\s,;]+|\bsk-[A-Za-z0-9_-]{8,})"
    )
    _unsafe_text: ClassVar[re.Pattern[str]] = re.compile(
        r"[\x00-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069]"
    )
    _numeric_extra: ClassVar[set[str]] = {"duration_ms", "http_status"}
    _max_message_length: ClassVar[int] = 512
    _max_extra_length: ClassVar[int] = 256

    @classmethod
    def _safe_text(cls, value: str, *, maximum: int) -> str:
        redacted = cls._credential_pattern.sub("[REDACTED]", value)
        normalized = cls._unsafe_text.sub(" ", redacted)
        return normalized[:maximum]

    @classmethod
    def _safe_message(cls, record: logging.LogRecord) -> str:
        # Logging arguments are very often user identifiers or exception
        # strings. Preserve the stable event template and put reviewed,
        # low-cardinality context in allowlisted ``extra`` fields instead.
        message = record.msg if isinstance(record.msg, str) else type(record.msg).__name__
        return cls._safe_text(message, maximum=cls._max_message_length)

    @classmethod
    def _safe_extra_value(cls, key: str, value: object) -> str | int | float | None:
        if key in cls._numeric_extra:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return None
            if isinstance(value, float) and not math.isfinite(value):
                return None
            return value
        if not isinstance(value, str):
            return None
        return cls._safe_text(value, maximum=cls._max_extra_length)

    @staticmethod
    def _safe_exception(record: logging.LogRecord) -> dict[str, object] | None:
        if not record.exc_info:
            return None
        exception_type, _exception, trace = record.exc_info
        frames = [
            {
                "file": Path(frame.filename).name,
                "line": frame.lineno,
                "function": frame.name,
            }
            for frame in traceback.extract_tb(trace)[-20:]
        ]
        # Exception messages are deliberately omitted: HTTP libraries, path
        # validators, parsers and provider SDKs may echo URLs, filenames,
        # prompts, response bodies or credentials into them.
        return {
            "type": getattr(exception_type, "__name__", "Exception"),
            "frames": frames,
        }

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": self._safe_message(record),
            "request_id": self._safe_extra_value("request_id", request_id_var.get()) or "",
        }
        for key, value in record.__dict__.items():
            if key not in self._reserved and key in self._allowed_extra:
                safe_value = self._safe_extra_value(key, value)
                if safe_value is not None:
                    payload[key] = safe_value
        exception = self._safe_exception(record)
        if exception is not None:
            payload["exception"] = exception
        return json.dumps(payload, ensure_ascii=False, default=str)


class SafeTextFormatter(JsonFormatter):
    """Human-readable rendering of the same redacted, allowlisted schema."""

    def format(self, record: logging.LogRecord) -> str:
        payload = json.loads(super().format(record))
        ordered = ["timestamp", "level", "logger", "message", "request_id"]
        ordered.extend(sorted(key for key in payload if key not in ordered))
        return " ".join(
            f"{key}={json.dumps(payload[key], ensure_ascii=False, default=str)}"
            for key in ordered
            if key in payload and payload[key] is not None and payload[key] != ""
        )


def configure_logging(level: str = "INFO", *, json_logs: bool = True) -> logging.Logger:
    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter() if json_logs else SafeTextFormatter())
    root.addHandler(handler)
    root.setLevel(level.upper())
    return logging.getLogger("markinote")
