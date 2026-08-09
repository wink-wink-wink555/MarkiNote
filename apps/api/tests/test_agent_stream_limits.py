from __future__ import annotations

import json
from unittest import mock

from .test_platform_api import build_client


def _post_chat(
    client,
    *,
    run_id: str,
    request_id: str = "req-stream-limit",
    allow_write_tools: bool = False,
):
    return client.post(
        "/api/v1/agent/chat",
        headers={"X-Request-ID": request_id},
        json={
            "message": "bounded stream",
            "run_id": run_id,
            "provider": "deepseek",
            "model": "deepseek-v4-flash",
            "api_key": "memory-only-key",
            "allow_write_tools": allow_write_tools,
        },
    )


def test_content_round_limit_keeps_prior_partial_and_never_emits_done() -> None:
    sentinel = "provider-secret-sentinel"

    def oversized_content(*_args, **_kwargs):
        yield {"type": "content", "content": "kept-" + ("a" * 600)}
        yield {"type": "content", "content": sentinel + ("b" * 600)}
        yield {"type": "done"}

    client, temp = build_client(
        settings_overrides={"ai_max_content_bytes_per_round": 1_024}
    )
    try:
        with mock.patch(
            "markinote_api.modules.agent.service.stream_chat_completion",
            side_effect=oversized_content,
        ):
            response = _post_chat(client, run_id="run-content-limit")

        assert response.status_code == 200
        assert "kept-" in response.text
        assert "AI provider content exceeded the per-round safety limit." in response.text
        assert '"code": "provider_content_round_limit_exceeded"' in response.text
        assert sentinel not in response.text
        assert "event: done" not in response.text
        conversation = client.app.state.conversation_repository.list()[0]
        assert conversation["messages"][-1]["content"].startswith("kept-")
        audit = client.app.state.agent_run_journal.inspect(
            "run-content-limit", "req-stream-limit"
        )
        assert audit is not None
        assert audit["state"] == "failed"
        assert audit["error_code"] == "provider_content_round_limit_exceeded"
    finally:
        client.close()
        temp.cleanup()


def test_custom_provider_event_limit_is_terminal_and_preserves_partial() -> None:
    def excessive_events(*_args, **_kwargs):
        yield {"type": "content", "content": "a"}
        yield {"type": "content", "content": "b"}
        yield {"type": "done"}

    client, temp = build_client(
        settings_overrides={
            "ai_max_provider_events": 2,
            "ai_max_provider_bytes": 4_096,
            "ai_max_content_bytes_total": 1_024,
            "ai_max_content_bytes_per_round": 1_024,
        }
    )
    client.app.state.agent_service.provider_stream = excessive_events
    try:
        response = _post_chat(client, run_id="run-event-limit")

        assert response.status_code == 200
        assert "AI provider stream exceeded the event safety limit." in response.text
        assert "event: done" not in response.text
        assert client.app.state.conversation_repository.list()[0]["messages"][-1]["content"] == "ab"
        audit = client.app.state.agent_run_journal.inspect(
            "run-event-limit", "req-stream-limit"
        )
        assert audit is not None
        assert audit["error_code"] == "provider_event_limit_exceeded"
    finally:
        client.close()
        temp.cleanup()


def test_custom_provider_boundary_event_keeps_only_the_reviewed_code_and_message() -> None:
    def boundary_error(*_args, **_kwargs):
        yield {
            "type": "error",
            "code": "provider_frame_limit_exceeded",
            "message": "untrusted-provider-secret-sentinel",
        }

    client, temp = build_client()
    client.app.state.agent_service.provider_stream = boundary_error
    try:
        response = _post_chat(client, run_id="run-custom-boundary")

        assert "AI provider sent an oversized stream frame." in response.text
        assert '"code": "provider_frame_limit_exceeded"' in response.text
        assert "untrusted-provider-secret-sentinel" not in response.text
        assert "event: done" not in response.text
        audit = client.app.state.agent_run_journal.inspect(
            "run-custom-boundary", "req-stream-limit"
        )
        assert audit is not None
        assert audit["error_code"] == "provider_frame_limit_exceeded"
    finally:
        client.close()
        temp.cleanup()


def test_tool_argument_and_browser_sse_frames_are_independently_bounded() -> None:
    def oversized_tool_arguments(*_args, **_kwargs):
        yield {"type": "tool_call_start", "index": 0, "id": "call-1", "name": "read_file"}
        yield {"type": "tool_call_args", "index": 0, "arguments": "x" * 257}
        yield {"type": "tool_calls_complete"}

    client, temp = build_client(
        settings_overrides={"ai_max_tool_arguments_bytes": 256}
    )
    client.app.state.agent_service.provider_stream = oversized_tool_arguments
    try:
        response = _post_chat(client, run_id="run-tool-argument-limit")
        assert "AI tool arguments exceeded the safety limit." in response.text
        assert "event: done" not in response.text
        audit = client.app.state.agent_run_journal.inspect(
            "run-tool-argument-limit", "req-stream-limit"
        )
        assert audit is not None
        assert audit["error_code"] == "tool_arguments_limit_exceeded"
    finally:
        client.close()
        temp.cleanup()


def test_minimum_valid_tool_result_budget_emits_rollback_handle_after_mutation() -> None:
    call = 0

    def mutate_then_reply(*_args, **_kwargs):
        nonlocal call
        current = call
        call += 1
        if current == 0:
            yield {
                "type": "tool_call_start",
                "index": 0,
                "id": "bounded-mutation",
                "name": "create_file",
            }
            yield {
                "type": "tool_call_args",
                "index": 0,
                "arguments": json.dumps(
                    {"path": "bounded.md", "content": "x" * 3_000},
                    separators=(",", ":"),
                ),
            }
            yield {"type": "tool_calls_complete"}
        else:
            yield {"type": "content", "content": "created"}
            yield {"type": "done"}

    tool_arguments = 4_096
    client, temp = build_client(
        settings_overrides={
            "ai_max_tool_arguments_bytes": tool_arguments,
            "ai_max_sse_event_bytes": 2 * tool_arguments + 64 * 1_024,
        }
    )
    client.app.state.agent_service.provider_stream = mutate_then_reply
    try:
        response = _post_chat(
            client,
            run_id="run-tight-tool-result-envelope",
            allow_write_tools=True,
        )

        assert response.status_code == 200
        assert "event: tool_result" in response.text
        assert "event: done" in response.text
        assert "event: error" not in response.text
        assert (
            client.app.state.settings.library_folder / "bounded.md"
        ).read_text(encoding="utf-8") == "x" * 3_000
        conversation = client.app.state.conversation_repository.list()[0]
        persisted_tool = next(
            message for message in conversation["messages"] if message.get("role") == "tool"
        )
        assert persisted_tool["_tool_meta"]["backup_group_id"]
        assert persisted_tool["_tool_meta"]["backup_info"]["operation_index"] >= 0
    finally:
        client.close()
        temp.cleanup()


def test_canonical_tool_argument_expansion_is_rejected_before_claim_or_mutation() -> None:
    raw_arguments = (
        '{"path":"numeric-bomb.md","content":"ok","pad":['
        + ",".join(["1e15"] * 5_990)
        + "]}"
    )
    assert len(raw_arguments.encode("utf-8")) == 29_999
    assert (
        len(
            json.dumps(
                json.loads(raw_arguments),
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        > 30_000
    )

    def numeric_expansion(*_args, **_kwargs):
        yield {
            "type": "tool_call_start",
            "index": 0,
            "id": "numeric-expansion",
            "name": "create_file",
        }
        yield {"type": "tool_call_args", "index": 0, "arguments": raw_arguments}
        yield {"type": "tool_calls_complete"}

    argument_limit = 30_000
    client, temp = build_client(
        settings_overrides={
            "ai_max_tool_arguments_bytes": argument_limit,
            "ai_max_sse_event_bytes": 2 * argument_limit + 64 * 1_024,
        }
    )
    client.app.state.agent_service.provider_stream = numeric_expansion
    try:
        with mock.patch.object(
            client.app.state.command_journal,
            "claim",
            wraps=client.app.state.command_journal.claim,
        ) as claim:
            response = _post_chat(
                client,
                run_id="run-canonical-argument-limit",
                allow_write_tools=True,
            )

        assert "AI tool arguments exceeded the safety limit." in response.text
        assert "event: tool_result" not in response.text
        assert "event: done" not in response.text
        assert not (client.app.state.settings.library_folder / "numeric-bomb.md").exists()
        claim.assert_not_called()
    finally:
        client.close()
        temp.cleanup()


def test_tool_result_envelope_is_admitted_before_mutation() -> None:
    call_id = "c" * 42_000
    raw_arguments = '{"path":"long-id-fail.md","content":"ok"}'

    def long_identifier(*_args, **_kwargs):
        yield {
            "type": "tool_call_start",
            "index": 0,
            "id": call_id,
            "name": "create_file",
        }
        yield {"type": "tool_call_args", "index": 0, "arguments": raw_arguments}
        yield {"type": "tool_calls_complete"}

    argument_limit = 256
    client, temp = build_client(
        settings_overrides={
            "ai_max_tool_arguments_bytes": argument_limit,
            "ai_max_sse_event_bytes": argument_limit + 64 * 1_024,
        }
    )
    client.app.state.agent_service.provider_stream = long_identifier
    try:
        with mock.patch.object(
            client.app.state.command_journal,
            "claim",
            wraps=client.app.state.command_journal.claim,
        ) as claim:
            response = _post_chat(
                client,
                run_id="run-combined-tool-envelope",
                allow_write_tools=True,
            )

        assert "event: tool_call" in response.text
        assert "An agent stream event exceeded the response safety limit." in response.text
        assert "event: tool_result" not in response.text
        assert "event: done" not in response.text
        assert not (client.app.state.settings.library_folder / "long-id-fail.md").exists()
        claim.assert_not_called()
    finally:
        client.close()
        temp.cleanup()


def test_browser_sse_frame_is_independently_bounded() -> None:
    def oversized_sse_event(*_args, **_kwargs):
        yield {"type": "content", "content": "c" * 65_950}
        yield {"type": "done"}

    client, temp = build_client(
        settings_overrides={
            "ai_max_tool_arguments_bytes": 256,
            "ai_max_sse_event_bytes": 66_048,
        }
    )
    client.app.state.agent_service.provider_stream = oversized_sse_event
    try:
        response = _post_chat(client, run_id="run-sse-event-limit")
        assert "An agent stream event exceeded the response safety limit." in response.text
        assert "event: done" not in response.text
        audit = client.app.state.agent_run_journal.inspect(
            "run-sse-event-limit", "req-stream-limit"
        )
        assert audit is not None
        assert audit["error_code"] == "agent_sse_event_limit_exceeded"
    finally:
        client.close()
        temp.cleanup()


def test_title_generation_time_is_part_of_the_total_stream_deadline() -> None:
    clock = [0.0]

    def completed_reply(*_args, **_kwargs):
        yield {"type": "content", "content": "answer"}
        yield {"type": "done"}

    def slow_title(*_args, **_kwargs):
        clock[0] = 2.0
        return "Late title"

    client, temp = build_client(
        settings_overrides={"ai_generate_titles": True, "ai_max_stream_seconds": 1}
    )
    try:
        with (
            mock.patch(
                "markinote_api.modules.agent.service.stream_chat_completion",
                side_effect=completed_reply,
            ),
            mock.patch(
                "markinote_api.modules.agent.service.generate_conversation_title",
                side_effect=slow_title,
            ),
            mock.patch(
                "markinote_api.modules.agent.service.time.monotonic",
                side_effect=lambda: clock[0],
            ),
        ):
            response = _post_chat(client, run_id="run-title-timeout")

        assert "AI processing exceeded the elapsed-time safety limit." in response.text
        assert "event: title_generated" not in response.text
        assert "event: done" not in response.text
        audit = client.app.state.agent_run_journal.inspect(
            "run-title-timeout", "req-stream-limit"
        )
        assert audit is not None
        assert audit["error_code"] == "agent_stream_timeout"
    finally:
        client.close()
        temp.cleanup()
