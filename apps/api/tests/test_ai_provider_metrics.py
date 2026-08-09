from __future__ import annotations

from unittest import mock

from prometheus_client import REGISTRY, generate_latest

from markinote_api.modules.agent.provider import stream_chat_completion


class _StreamingResponse:
    def __init__(self, lines: list[str], *, status_code: int = 200):
        self.lines = lines
        self.status_code = status_code
        self.encoding = "utf-8"
        self.text = "provider failure"

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def iter_lines(self, *, decode_unicode: bool):
        assert decode_unicode is True
        yield from self.lines

    def json(self):
        return {"error": {"message": "provider failure"}}


class _ChunkedStreamingResponse(_StreamingResponse):
    def __init__(self, chunks: list[bytes], *, status_code: int = 200):
        super().__init__([], status_code=status_code)
        self.chunks = chunks

    def iter_content(self, *, chunk_size: int, decode_unicode: bool):
        assert chunk_size == 8192
        assert decode_unicode is False
        yield from self.chunks


def _sample(name: str, labels: dict[str, str]) -> float:
    return float(REGISTRY.get_sample_value(name, labels) or 0.0)


def test_provider_metrics_record_first_content_and_total_upstream_wait_without_secrets():
    provider_labels = {"provider": "deepseek"}
    success_labels = {"provider": "deepseek", "outcome": "success"}
    first_before = _sample(
        "markinote_ai_provider_time_to_first_content_seconds_count", provider_labels
    )
    total_before = _sample(
        "markinote_ai_provider_upstream_wait_seconds_count", success_labels
    )
    response = _StreamingResponse(
        [
            'data: {"choices":[{"delta":{"content":"hello"},"finish_reason":null}]}',
            "data: [DONE]",
        ]
    )

    with mock.patch(
        "markinote_api.modules.agent.provider.requests.post", return_value=response
    ):
        events = list(
            stream_chat_completion(
                [{"role": "user", "content": "hello"}],
                [],
                "provider-metric-secret",
                "deepseek",
                "deepseek-v4-flash",
            )
        )

    assert events == [
        {"type": "content", "content": "hello"},
        {"type": "done"},
    ]
    assert _sample(
        "markinote_ai_provider_time_to_first_content_seconds_count", provider_labels
    ) == first_before + 1
    assert _sample(
        "markinote_ai_provider_upstream_wait_seconds_count", success_labels
    ) == total_before + 1
    assert "provider-metric-secret" not in generate_latest().decode("utf-8")


def test_provider_stream_uses_the_explicit_isolated_fixture_origin() -> None:
    response = _StreamingResponse(["data: [DONE]"])
    with mock.patch(
        "markinote_api.modules.agent.provider.requests.post",
        return_value=response,
    ) as provider_post:
        assert list(
            stream_chat_completion(
                [],
                [],
                "synthetic-key",
                "deepseek",
                "deepseek-v4-flash",
                base_url_override="http://fake-provider:8099",
            )
        ) == [{"type": "done"}]

    assert provider_post.call_args.args[0] == "http://fake-provider:8099/chat/completions"


def test_provider_metrics_classify_http_failure_without_fake_first_content():
    provider_labels = {"provider": "deepseek"}
    failure_labels = {"provider": "deepseek", "outcome": "error"}
    first_before = _sample(
        "markinote_ai_provider_time_to_first_content_seconds_count", provider_labels
    )
    failure_before = _sample(
        "markinote_ai_provider_upstream_wait_seconds_count", failure_labels
    )

    with mock.patch(
        "markinote_api.modules.agent.provider.requests.post",
        return_value=_StreamingResponse([], status_code=503),
    ):
        events = list(
            stream_chat_completion([], [], "secret", "deepseek", "deepseek-v4-flash")
        )

    assert events[0]["type"] == "error"
    assert _sample(
        "markinote_ai_provider_time_to_first_content_seconds_count", provider_labels
    ) == first_before
    assert _sample(
        "markinote_ai_provider_upstream_wait_seconds_count", failure_labels
    ) == failure_before + 1


def test_provider_metrics_classify_consumer_disconnect_as_cancelled():
    cancelled_labels = {"provider": "deepseek", "outcome": "cancelled"}
    cancelled_before = _sample(
        "markinote_ai_provider_upstream_wait_seconds_count", cancelled_labels
    )
    response = _StreamingResponse(
        [
            'data: {"choices":[{"delta":{"content":"partial"},"finish_reason":null}]}',
            'data: {"choices":[{"delta":{"content":"unused"},"finish_reason":null}]}',
        ]
    )

    with mock.patch(
        "markinote_api.modules.agent.provider.requests.post", return_value=response
    ):
        stream = stream_chat_completion(
            [], [], "secret", "deepseek", "deepseek-v4-flash"
        )
        assert next(stream) == {"type": "content", "content": "partial"}
        stream.close()

    assert _sample(
        "markinote_ai_provider_upstream_wait_seconds_count", cancelled_labels
    ) == cancelled_before + 1


def test_provider_eof_without_terminal_marker_fails_closed() -> None:
    failure_labels = {"provider": "deepseek", "outcome": "error"}
    failure_before = _sample(
        "markinote_ai_provider_upstream_wait_seconds_count", failure_labels
    )
    response = _StreamingResponse(
        ['data: {"choices":[{"delta":{"content":"partial"},"finish_reason":null}]}']
    )

    with mock.patch(
        "markinote_api.modules.agent.provider.requests.post", return_value=response
    ):
        events = list(
            stream_chat_completion([], [], "secret", "deepseek", "deepseek-v4-flash")
        )

    assert events == [
        {"type": "content", "content": "partial"},
        {"type": "error", "message": "AI 服务流在完成前中断，请重试"},
    ]
    assert _sample(
        "markinote_ai_provider_upstream_wait_seconds_count", failure_labels
    ) == failure_before + 1


def test_provider_http_error_never_echoes_upstream_body() -> None:
    response = _StreamingResponse([], status_code=401)
    response.text = "api_key=upstream-secret prompt=document-body"

    with mock.patch(
        "markinote_api.modules.agent.provider.requests.post", return_value=response
    ):
        events = list(
            stream_chat_completion([], [], "secret", "deepseek", "deepseek-v4-flash")
        )

    serialized = repr(events)
    assert events == [
        {"type": "error", "message": "AI 服务拒绝了请求，请检查配置后重试"}
    ]
    assert "upstream-secret" not in serialized
    assert "document-body" not in serialized


def test_provider_accepts_a_frame_exactly_at_the_byte_boundary() -> None:
    line = "data: [DONE]"
    response = _StreamingResponse([line])

    with mock.patch(
        "markinote_api.modules.agent.provider.requests.post", return_value=response
    ):
        events = list(
            stream_chat_completion(
                [],
                [],
                "secret",
                "deepseek",
                "deepseek-v4-flash",
                max_frame_bytes=len(line.encode("utf-8")) + 1,
            )
        )

    assert events == [{"type": "done"}]


def test_provider_bounds_a_chunked_frame_before_newline_without_echoing_it() -> None:
    sentinel = b"provider-secret-sentinel"
    response = _ChunkedStreamingResponse([b"data: " + sentinel])

    with mock.patch(
        "markinote_api.modules.agent.provider.requests.post", return_value=response
    ):
        events = list(
            stream_chat_completion(
                [],
                [],
                "secret",
                "deepseek",
                "deepseek-v4-flash",
                max_frame_bytes=16,
            )
        )

    assert events == [
        {
            "type": "error",
            "code": "provider_frame_limit_exceeded",
            "message": "AI provider sent an oversized stream frame.",
        }
    ]
    assert "provider-secret-sentinel" not in repr(events)


def test_provider_bounds_total_upstream_events_with_a_stable_code() -> None:
    response = _StreamingResponse(
        [
            'data: {"choices":[{"delta":{"content":"kept"},"finish_reason":null}]}',
            "data: [DONE]",
        ]
    )

    with mock.patch(
        "markinote_api.modules.agent.provider.requests.post", return_value=response
    ):
        events = list(
            stream_chat_completion(
                [],
                [],
                "secret",
                "deepseek",
                "deepseek-v4-flash",
                max_events=1,
            )
        )

    assert events == [
        {"type": "content", "content": "kept"},
        {
            "type": "error",
            "code": "provider_event_limit_exceeded",
            "message": "AI provider stream exceeded the event safety limit.",
        },
    ]
