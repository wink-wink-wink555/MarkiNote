"""Bounded-protocol client for the co-located FinanceMCP streamable HTTP server."""
from __future__ import annotations

import json
import threading
import time
from contextlib import suppress
from typing import Any

import httpx

ALLOWED_FINANCE_TOOLS = frozenset(
    {
        "current_timestamp",
        "finance_news",
        "stock_data",
        "stock_data_minutes",
        "index_data",
        "macro_econ",
        "company_performance",
        "fund_data",
        "fund_manager_by_name",
        "convertible_bond",
        "block_trade",
        "money_flow",
        "margin_trade",
        "company_performance_hk",
        "company_performance_us",
        "csi_index_constituents",
        "dragon_tiger_inst",
        "hot_news_7x24",
        "futures_data",
        "qveris_finance",
    }
)


class FinanceMcpError(RuntimeError):
    pass


class FinanceMcpClient:
    def __init__(self, url: str, timeout_seconds: int = 45):
        self.url = url
        self.timeout = httpx.Timeout(timeout_seconds)
        self._guard = threading.Lock()
        self._definitions: list[dict[str, Any]] = []
        self._expires_at = 0.0

    @staticmethod
    def _request_headers(
        *,
        session_id: str = "",
        tushare_token: str = "",
        qveris_api_key: str = "",
    ) -> dict[str, str]:
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }
        if session_id:
            headers["Mcp-Session-Id"] = session_id
        if tushare_token:
            headers["X-Tushare-Token"] = tushare_token
        if qveris_api_key:
            headers["X-Qveris-Api-Key"] = qveris_api_key
        return headers

    def _post(
        self,
        client: httpx.Client,
        method: str,
        params: dict[str, Any],
        *,
        request_id: int,
        session_id: str = "",
        tushare_token: str = "",
        qveris_api_key: str = "",
    ) -> tuple[dict[str, Any], str]:
        response = client.post(
            self.url,
            headers=self._request_headers(
                session_id=session_id,
                tushare_token=tushare_token,
                qveris_api_key=qveris_api_key,
            ),
            json={"jsonrpc": "2.0", "id": request_id, "method": method, "params": params},
        )
        response.raise_for_status()
        try:
            payload = response.json()
        except ValueError as error:
            raise FinanceMcpError("FinanceMCP returned a non-JSON response") from error
        if not isinstance(payload, dict):
            raise FinanceMcpError("FinanceMCP returned an invalid JSON-RPC envelope")
        if payload.get("error") is not None:
            raise FinanceMcpError(f"FinanceMCP error: {json.dumps(payload['error'], ensure_ascii=False)}")
        session = response.headers.get("mcp-session-id", session_id)
        return payload, session

    def _open(
        self,
        client: httpx.Client,
        *,
        tushare_token: str = "",
        qveris_api_key: str = "",
    ) -> str:
        _, session_id = self._post(
            client,
            "initialize",
            {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "MarkiNote", "version": "4.0.0"},
            },
            request_id=1,
            tushare_token=tushare_token,
            qveris_api_key=qveris_api_key,
        )
        response = client.post(
            self.url,
            headers=self._request_headers(
                session_id=session_id,
                tushare_token=tushare_token,
                qveris_api_key=qveris_api_key,
            ),
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        )
        response.raise_for_status()
        return session_id

    def _close(self, client: httpx.Client, session_id: str) -> None:
        if not session_id:
            return
        with suppress(httpx.HTTPError):
            client.delete(
                self.url,
                headers=self._request_headers(session_id=session_id),
            )

    def tool_definitions(self) -> list[dict[str, Any]]:
        if not self.url:
            return []
        now = time.monotonic()
        with self._guard:
            if self._definitions and now < self._expires_at:
                return list(self._definitions)
            session_id = ""
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    session_id = self._open(client)
                    payload, session_id = self._post(
                        client,
                        "tools/list",
                        {},
                        request_id=2,
                        session_id=session_id,
                    )
                    tools = payload.get("result", {}).get("tools", [])
                    definitions = []
                    for tool in tools if isinstance(tools, list) else []:
                        if not isinstance(tool, dict) or tool.get("name") not in ALLOWED_FINANCE_TOOLS:
                            continue
                        schema = tool.get("inputSchema")
                        definitions.append(
                            {
                                "type": "function",
                                "function": {
                                    "name": tool["name"],
                                    "description": str(tool.get("description", "")),
                                    "parameters": schema if isinstance(schema, dict) else {"type": "object"},
                                },
                            }
                        )
                    self._definitions = definitions
                    self._expires_at = now + 300
                    return list(definitions)
            except httpx.HTTPError as error:
                if self._definitions:
                    return list(self._definitions)
                raise FinanceMcpError("FinanceMCP tool discovery failed") from error
            finally:
                if session_id:
                    try:
                        with httpx.Client(timeout=self.timeout) as client:
                            self._close(client, session_id)
                    except httpx.HTTPError:
                        pass

    def is_tool(self, name: str) -> bool:
        return name in {
            definition["function"]["name"] for definition in self.tool_definitions()
        }

    def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        tushare_token: str = "",
        qveris_api_key: str = "",
    ) -> str:
        if name not in ALLOWED_FINANCE_TOOLS or not self.is_tool(name):
            raise FinanceMcpError("FinanceMCP tool is not available")
        session_id = ""
        try:
            with httpx.Client(timeout=self.timeout) as client:
                session_id = self._open(
                    client,
                    tushare_token=tushare_token,
                    qveris_api_key=qveris_api_key,
                )
                payload, session_id = self._post(
                    client,
                    "tools/call",
                    {"name": name, "arguments": arguments},
                    request_id=2,
                    session_id=session_id,
                    tushare_token=tushare_token,
                    qveris_api_key=qveris_api_key,
                )
                # Deliberately no business-data truncation or item-count cap.
                return json.dumps(payload.get("result"), ensure_ascii=False, separators=(",", ":"))
        except httpx.HTTPError as error:
            raise FinanceMcpError("FinanceMCP request failed") from error
        finally:
            if session_id:
                try:
                    with httpx.Client(timeout=self.timeout) as client:
                        self._close(client, session_id)
                except httpx.HTTPError:
                    pass
