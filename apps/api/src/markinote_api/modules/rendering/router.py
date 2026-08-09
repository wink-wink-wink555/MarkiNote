"""Typed Markdown rendering HTTP adapter."""
from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from markinote_api.modules.rendering.service import process_markdown

router = APIRouter(prefix="/api/v1/rendering", tags=["rendering"])


class RenderMarkdownRequest(BaseModel):
    markdown: str = Field(default="")


class RenderMarkdownResponse(BaseModel):
    html: str


@router.post("/preview", response_model=RenderMarkdownResponse)
def render_markdown(body: RenderMarkdownRequest, request: Request) -> RenderMarkdownResponse:
    size = len(body.markdown.encode("utf-8"))
    if size > request.app.state.settings.max_preview_bytes:
        from markinote_api.platform.errors import Problem

        raise Problem(
            413,
            "document_too_large",
            "Document too large",
            "The Markdown preview exceeds the configured limit.",
        )
    return RenderMarkdownResponse(html=process_markdown(body.markdown))
