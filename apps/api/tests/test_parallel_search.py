from __future__ import annotations

import hashlib
import json
from unittest import mock

import anyio
import httpx2
import pytest
from pydantic import ValidationError

from markinote_api.config import Settings
from markinote_api.modules.agent import parallel_search
from markinote_api.modules.agent.tools import UNTRUSTED_WEB_CONTENT_NOTICE, execute_tool

from .test_platform_api import build_client


class MCPServer:
    def __init__(self):
        self.requests = []
        self.clients = []
        self.result = {
            "content": [],
            "structuredContent": {"results": [{
                "url": "https://docs.python.org/3/library/asyncio-task.html?token=secret#anchor",
                "title": "TaskGroup documentation",
                "excerpts": ["Task groups provide structured concurrency."],
            }]},
        }
        self.failure = None
        self.sse = False
        self.tools = [{"name": "web_search", "inputSchema": {"type": "object"}}]

    async def handle(self, request):
        self.requests.append(request)
        assert str(request.url) == parallel_search.ENDPOINT
        assert request.headers["user-agent"] == parallel_search.USER_AGENT
        assert "authorization" not in request.headers
        assert "x-api-key" not in request.headers
        if request.method == "GET":
            return httpx2.Response(405)
        if request.method == "DELETE":
            return httpx2.Response(200)
        body = json.loads(request.content)
        method = body["method"]
        if "id" not in body:
            return httpx2.Response(202)
        if method == "initialize":
            value = {
                "protocolVersion": "2025-03-26",
                "serverInfo": {"name": "test-search", "version": "1"},
                "capabilities": {"tools": {}},
            }
        elif method == "tools/list":
            value = {"tools": self.tools}
        elif method == "tools/call":
            if self.failure == "timeout":
                await anyio.sleep_forever()
            if self.failure == "http":
                return httpx2.Response(503, text="private-server-error")
            value = self.result
        else:
            raise AssertionError(method)
        response = {"jsonrpc": "2.0", "id": body["id"], "result": value}
        headers = {"mcp-session-id": "test-session"}
        if self.sse:
            headers["content-type"] = "text/event-stream"
            return httpx2.Response(200, headers=headers, content=f"event: message\ndata: {json.dumps(response)}\n\n")
        return httpx2.Response(200, headers=headers, json=response)

    def install(self, monkeypatch):
        original = httpx2.AsyncClient

        def factory(**kwargs):
            client = original(**kwargs, transport=httpx2.MockTransport(self.handle), trust_env=False)
            self.clients.append(client)
            return client

        monkeypatch.setattr(parallel_search.httpx2, "AsyncClient", factory)

    def calls(self):
        return [json.loads(r.content) for r in self.requests if r.method == "POST"]


@pytest.mark.parametrize("sse", [False, True])
def test_dispatch_uses_sdk_discovery_and_search_without_credentials(monkeypatch, sse):
    server = MCPServer()
    server.sse = sse
    server.install(monkeypatch)
    monkeypatch.setenv("PARALLEL_API_KEY", "ambient-secret")
    monkeypatch.setenv("MARKINOTE_AI_API_KEY", "ambient-model-secret")
    result, backup = execute_tool(
        "web_search", '{"query":"Python TaskGroup"}', "/tmp", None, None,
        web_search_provider="parallel", search_session_id="conversation-one", model_id="deepseek-v4-flash",
        api_key="transient-model-secret",
    )
    assert backup is None
    assert "structured concurrency" in result
    assert UNTRUSTED_WEB_CONTENT_NOTICE in result
    assert "https://docs.python.org/3/library/asyncio-task.html" in result
    assert "token=secret" not in result and "#anchor" not in result
    calls = server.calls()
    assert [c["method"] for c in calls] == ["initialize", "notifications/initialized", "tools/list", "tools/call"]
    assert calls[-1]["params"] == {"name": "web_search", "arguments": {
        "objective": "Python TaskGroup", "search_queries": ["Python TaskGroup"],
        "session_id": hashlib.sha256(b"conversation-one").hexdigest(), "model_name": "deepseek-v4-flash",
    }}
    assert all(client.is_closed for client in server.clients)
    assert "secret" not in "".join(r.content.decode() for r in server.requests)


def test_default_selection_disable_and_configuration(monkeypatch):
    monkeypatch.setenv("MARKINOTE_WEB_SEARCH_PROVIDER", "parallel")
    assert Settings(_env_file=None).web_search_provider == "parallel"
    assert Settings(_env_file=None, web_search_provider="bing").web_search_provider == "bing"
    with pytest.raises(ValidationError):
        Settings(_env_file=None, web_search_provider="unknown")
    monkeypatch.delenv("MARKINOTE_WEB_SEARCH_PROVIDER")
    assert Settings(_env_file=None).web_search_provider == "bing"
    with (
        mock.patch("markinote_api.modules.agent.tools._web_search_bing", return_value="existing result") as bing,
        mock.patch("markinote_api.modules.agent.tools._web_search_ddg") as ddg,
        mock.patch.object(parallel_search, "search") as parallel,
    ):
        result, _ = execute_tool("web_search", '{"query":"test"}', "/tmp", None, None)
        assert "existing result" in result
        bing.assert_called_once()
        ddg.assert_not_called()
        result, _ = execute_tool("web_search", '{"query":"test"}', "/tmp", None, None, web_search_provider="disabled")
        assert "已禁用" in result
        parallel.assert_not_called()
        assert bing.call_count == 1


@pytest.mark.parametrize("failure", ["http", "tool", "invalid", "missing", "timeout"])
def test_errors_are_bounded_private_and_never_fall_back(monkeypatch, failure):
    server = MCPServer()
    server.install(monkeypatch)
    server.failure = failure
    if failure == "tool":
        server.result = {"isError": True, "content": [{"type": "text", "text": "private-server-error"}]}
    if failure == "invalid":
        server.result = {"content": [], "structuredContent": {"unexpected": "private-server-error"}}
    if failure == "missing":
        server.tools = []
    monkeypatch.setattr(parallel_search, "SEARCH_TIMEOUT_SECONDS", 0.1)
    with mock.patch("markinote_api.modules.agent.tools._web_search_bing") as bing:
        result, _ = execute_tool("web_search", '{"query":"test"}', "/tmp", None, None, web_search_provider="parallel")
    assert "超时" in result if failure == "timeout" else "失败" in result
    assert "private-server-error" not in result
    bing.assert_not_called()
    assert all(client.is_closed for client in server.clients)


def test_cancellation_propagates_and_closes_transport(monkeypatch):
    server = MCPServer()
    server.failure = "timeout"
    server.install(monkeypatch)

    async def cancel():
        with anyio.move_on_after(0.1) as scope:
            await parallel_search._search("test", "session", "deepseek-v4-flash")
            pytest.fail("cancellation was swallowed")
        assert scope.cancel_called

    anyio.run(cancel)
    assert all(client.is_closed for client in server.clients)


@pytest.mark.parametrize("url", ["javascript:alert(1)", "https://user:pass@example.com/", "https://example.com/\nsecret"])
def test_unusable_result_urls_are_not_returned(monkeypatch, url):
    server = MCPServer()
    server.install(monkeypatch)
    server.result["structuredContent"]["results"][0]["url"] = url
    result = parallel_search.search("test")
    assert "未找到" in result
    assert url not in result


def test_agent_loop_consumes_parallel_results_and_preserves_write_approval(monkeypatch):
    server = MCPServer()
    server.install(monkeypatch)
    consumed = []

    def scripted_model(messages, *_args, **_kwargs):
        round_number = len(consumed)
        consumed.append(list(messages))
        if round_number == 0:
            name, arguments = "web_search", {"query": "Python TaskGroup"}
        elif round_number == 1:
            assert any(m.get("role") == "tool" and "structured concurrency" in m["content"] for m in messages)
            name, arguments = "write_file", {"path": "note.md", "content": "unapproved change"}
        else:
            yield {"type": "content", "content": "done"}
            yield {"type": "done"}
            return
        yield {"type": "tool_call_start", "index": 0, "id": f"call-{round_number}", "name": name}
        yield {"type": "tool_call_args", "index": 0, "arguments": json.dumps(arguments)}
        yield {"type": "tool_calls_complete"}

    client, temp = build_client(settings_overrides={"web_search_provider": "parallel"})
    try:
        note = client.app.state.settings.library_folder / "note.md"
        note.write_text("original")
        with mock.patch("markinote_api.modules.agent.service.stream_chat_completion", side_effect=scripted_model):
            response = client.post("/api/v1/agent/chat", json={
                "message": "search and update the current note", "api_key": "transient-model-key",
                "context_file": "note.md", "allow_write_tools": True,
            })
        assert response.status_code == 200
        assert "structured concurrency" in response.text
        assert '"external_content"' in response.text
        assert note.read_text() == "original"
        assert len(consumed) == 2
        persisted = "".join(p.read_text() for p in client.app.state.settings.conversations_folder.glob("*.json"))
        assert "structured concurrency" in persisted
        assert "transient-model-key" not in persisted
    finally:
        client.close()
        temp.cleanup()
