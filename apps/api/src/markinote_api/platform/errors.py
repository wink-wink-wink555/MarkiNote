"""Problem Details errors and exception handlers."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from starlette.exceptions import HTTPException as StarletteHTTPException

from markinote_api.modules.documents.errors import DocumentError


class ProblemDetails(BaseModel):
    """RFC 9457-compatible public error contract."""

    model_config = ConfigDict(extra="allow")
    type: str
    title: str
    status: int
    code: str
    detail: str
    requestId: str


@dataclass(slots=True)
class Problem(Exception):
    status: int
    code: str
    title: str
    detail: str
    extra: dict[str, Any] | None = None


def problem_payload(request: Request, problem: Problem) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "type": f"https://markinote.local/problems/{problem.code.replace('_', '-')}",
        "title": problem.title,
        "status": problem.status,
        "code": problem.code,
        "detail": problem.detail,
        "requestId": getattr(request.state, "request_id", ""),
    }
    if problem.extra:
        payload.update(problem.extra)
    return payload


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(DocumentError)
    async def handle_document_error(request: Request, error: DocumentError) -> JSONResponse:
        problem = Problem(
            status=error.status_code,
            code=error.code,
            title="Document operation failed",
            detail=error.message,
            extra={"details": error.details} if error.details else None,
        )
        return JSONResponse(problem_payload(request, problem), status_code=error.status_code)

    @app.exception_handler(Problem)
    async def handle_problem(request: Request, error: Problem) -> JSONResponse:
        return JSONResponse(problem_payload(request, error), status_code=error.status)

    @app.exception_handler(RequestValidationError)
    async def handle_validation(request: Request, error: RequestValidationError) -> JSONResponse:
        errors = []
        for issue in error.errors():
            # Inputs and parser context may contain document content or API keys.
            errors.append({key: value for key, value in issue.items() if key not in {"input", "ctx", "url"}})
        problem = Problem(
            status=422,
            code="validation_error",
            title="Request validation failed",
            detail="The request does not match the API contract.",
            extra={"errors": errors},
        )
        return JSONResponse(problem_payload(request, problem), status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def handle_http(request: Request, error: StarletteHTTPException) -> JSONResponse:
        title = "Not found" if error.status_code == 404 else "HTTP request failed"
        # Starlette permits arbitrary objects in ``HTTPException.detail``.  Do
        # not turn an internal exception, path, or credential-bearing value
        # into a public Problem Details response merely because an adapter
        # wrapped it in HTTPException.
        detail = (
            "The requested resource was not found."
            if error.status_code == 404
            else "The HTTP request was rejected."
        )
        problem = Problem(
            status=error.status_code,
            code="not_found" if error.status_code == 404 else "http_error",
            title=title,
            detail=detail,
        )
        return JSONResponse(problem_payload(request, problem), status_code=error.status_code)

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, error: Exception) -> JSONResponse:
        request.app.state.logger.exception(
            "unhandled request error",
            extra={"request_id": getattr(request.state, "request_id", "")},
        )
        problem = Problem(
            status=500,
            code="internal_error",
            title="Internal server error",
            detail="The request could not be completed.",
        )
        return JSONResponse(problem_payload(request, problem), status_code=500)
