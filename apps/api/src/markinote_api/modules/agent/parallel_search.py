"""Anonymous Parallel Search MCP adapter for the existing web_search tool."""
from __future__ import annotations

import hashlib
from functools import partial
from urllib.parse import urlsplit, urlunsplit

import anyio
import httpx2
from mcp import ClientSession, types
from mcp.client.streamable_http import streamable_http_client
from pydantic import BaseModel, Field

ENDPOINT = "https://search.parallel.ai/mcp"
USER_AGENT = "MarkiNote/4.0.0 (+https://github.com/wink-wink-wink555/MarkiNote)"
SEARCH_TIMEOUT_SECONDS = 20


class SearchResult(BaseModel):
    url: str
    title: str | None = None
    excerpts: list[str] = Field(default_factory=list)


class SearchResponse(BaseModel):
    results: list[SearchResult]


async def _search(query: str, session_id: str, model_id: str) -> str:
    # One deadline includes initialization, discovery, execution and cleanup.
    # No model credentials or cookies are forwarded to the search service.
    with anyio.fail_after(SEARCH_TIMEOUT_SECONDS):
        async with httpx2.AsyncClient(
            headers={"User-Agent": USER_AGENT},
            timeout=httpx2.Timeout(SEARCH_TIMEOUT_SECONDS, connect=5),
            follow_redirects=False,
        ) as http_client, streamable_http_client(ENDPOINT, http_client=http_client) as streams, ClientSession(
            *streams,
            client_info=types.Implementation(name="MarkiNote", version="4.0.0"),
        ) as session:
            await session.initialize()
            tools = await session.list_tools()
            if not any(tool.name == "web_search" for tool in tools.tools):
                raise RuntimeError("Parallel search tool unavailable")
            arguments: dict[str, str | list[str]] = {"objective": query, "search_queries": [query]}
            if session_id:
                # Stable across turns without exposing the local conversation ID.
                arguments["session_id"] = hashlib.sha256(session_id.encode()).hexdigest()
            if model_id:
                arguments["model_name"] = model_id
            result = await session.call_tool("web_search", arguments)
            if not isinstance(result, types.CallToolResult) or result.is_error:
                raise RuntimeError("Parallel search failed")
            payload = SearchResponse.model_validate(result.structured_content)

    sections: list[str] = []
    for item in payload.results[:5]:
        url = urlsplit(item.url)
        if (
            url.scheme not in {"http", "https"}
            or not url.hostname
            or url.username
            or url.password
            or len(item.url) > 1024
            or any(ord(char) < 32 or ord(char) == 127 for char in item.url)
        ):
            continue
        # Match fetch_url's display policy: queries/fragments can carry secrets.
        display_url = urlunsplit((url.scheme, url.netloc, url.path, "", ""))
        section = f"{len(sections) + 1}. {(item.title or 'Untitled')[:150]}\n{display_url}\n{' '.join(item.excerpts)[:500]}"
        if sum(map(len, sections)) + len(section) > 4400:
            break
        sections.append(section)
    return "\n\n".join(sections) if sections else "Parallel 未找到可用的搜索结果。"


def search(query: str, *, session_id: str = "", model_id: str = "") -> str:
    """Run in the synchronous agent worker; cancellation is never swallowed."""
    try:
        return anyio.run(partial(_search, query, session_id, model_id))
    except TimeoutError:
        return "Parallel 搜索超时，请稍后重试。"
    except Exception:
        # Server errors may echo queries. Keep them out of persisted results/logs.
        return "Parallel 搜索失败，请稍后重试；不会自动切换搜索服务。"
