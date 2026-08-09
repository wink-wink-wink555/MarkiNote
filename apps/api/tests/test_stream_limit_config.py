from __future__ import annotations

import pytest
from pydantic import ValidationError

from markinote_api.config import Settings


@pytest.mark.parametrize(
    "field",
    (
        "ai_max_provider_frame_bytes",
        "ai_max_provider_events",
        "ai_max_provider_bytes",
        "ai_max_content_bytes_per_round",
        "ai_max_content_bytes_total",
        "ai_max_tool_arguments_bytes",
        "ai_max_sse_event_bytes",
        "ai_max_stream_seconds",
    ),
)
def test_ai_stream_limits_must_be_positive(field: str) -> None:
    with pytest.raises(ValidationError):
        Settings(**{field: 0})


def test_ai_stream_limit_relationships_fail_closed() -> None:
    with pytest.raises(ValidationError, match="total must be at least"):
        Settings(
            ai_max_content_bytes_per_round=2_048,
            ai_max_content_bytes_total=1_024,
        )
    with pytest.raises(ValidationError, match="provider_bytes must be at least"):
        Settings(
            ai_max_content_bytes_per_round=1_024,
            ai_max_content_bytes_total=8_192,
            ai_max_provider_bytes=4_096,
        )
    with pytest.raises(ValidationError, match="cover ai_max_tool_arguments_bytes"):
        Settings(
            ai_max_tool_arguments_bytes=2_048,
            ai_max_sse_event_bytes=2_048 + 64 * 1_024 - 1,
        )
    with pytest.raises(ValidationError, match="cover ai_max_tool_arguments_bytes"):
        Settings(
            ai_max_tool_arguments_bytes=200_000,
            ai_max_sse_event_bytes=200_000 + 64 * 1_024 - 1,
        )
    assert Settings(
        ai_max_tool_arguments_bytes=2_048,
        ai_max_sse_event_bytes=2_048 + 64 * 1_024,
    )
