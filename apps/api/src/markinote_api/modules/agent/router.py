"""Typed AI HTTP and SSE adapter."""
from __future__ import annotations

import json
from collections.abc import Callable, Iterator

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool
from starlette.types import Receive, Scope, Send

from markinote_api.modules.agent.provider import get_providers_info, validate_api_key
from markinote_api.modules.agent.schemas import (
    AgentEvent,
    ChatRequest,
    ProvidersResponse,
    ValidateKeyRequest,
    ValidateKeyResponse,
)
from markinote_api.modules.agent.service import AgentService

router = APIRouter(prefix="/api/v1/agent", tags=["agent"])


class _ClosingStreamingResponse(StreamingResponse):
    """Always close the managed synchronous stream on ASGI disconnects."""

    def __init__(
        self,
        content: Iterator[str],
        *,
        close_callback: Callable[[], None],
        media_type: str,
        headers: dict[str, str],
    ) -> None:
        super().__init__(content, media_type=media_type, headers=headers)
        self._close_callback = close_callback

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            await run_in_threadpool(self._close_callback)


def get_service(request: Request) -> AgentService:
    return request.app.state.agent_service


@router.get("/providers", response_model=ProvidersResponse)
def providers(request: Request) -> dict[str, object]:
    return {
        "providers": get_providers_info(),
        "limits": {"max_attachment_files": request.app.state.settings.max_attachment_files},
        "serverKeyConfigured": bool(
            request.app.state.settings.ai_api_key
            and request.app.state.settings.ai_api_key.get_secret_value()
        ),
    }


@router.post("/validate-key", response_model=ValidateKeyResponse)
def validate_key(body: ValidateKeyRequest) -> dict[str, object]:
    ok, message = validate_api_key(body.provider, body.api_key.get_secret_value())
    return {"success": ok, "message": message}


@router.post(
    "/chat",
    responses={
        200: {
            "model": AgentEvent,
            "content": {
                "text/event-stream": {
                    "schema": {"type": "string"},
                    "example": "id: 1\nevent: token\ndata: {\"schemaVersion\":1,...}\n\n",
                }
            },
            "description": "Versioned SSE stream with a typed data envelope.",
            "x-sse-event-schema": {"$ref": "#/components/schemas/AgentEvent"},
        }
    },
)
def chat(
    body: ChatRequest,
    request: Request,
    service: AgentService = Depends(get_service),
) -> StreamingResponse:
    events = service.stream(body, request_id=request.state.request_id)

    def encode():
        for event_type, payload in events:
            sequence = payload.get("sequence", "")
            yield (
                f"id: {sequence}\n"
                f"event: {event_type}\n"
                f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
            )

    return _ClosingStreamingResponse(
        encode(),
        close_callback=events.close,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
