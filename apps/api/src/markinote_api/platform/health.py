"""Health and metrics endpoints."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from markinote_api.platform.schemas import LivenessResponse, ReadinessResponse

router = APIRouter(tags=["platform"])


@router.get("/health/live", summary="Process liveness", response_model=LivenessResponse)
def live() -> LivenessResponse:
    return LivenessResponse(status="ok")


def _directory_ready(path: Path) -> bool:
    if not path.is_dir() or not os.access(path, os.R_OK | os.W_OK):
        return False
    try:
        with tempfile.TemporaryFile(dir=path):
            pass
        return True
    except OSError:
        return False


@router.get("/health/ready", summary="Dependency readiness", response_model=ReadinessResponse)
def ready(request: Request) -> JSONResponse:
    settings = request.app.state.settings
    checks = {}
    if settings.auth_mode != "accounts":
        checks.update(
            {
                "library": _directory_ready(settings.library_folder),
                "conversations": _directory_ready(settings.conversations_folder),
                "backups": _directory_ready(settings.backups_folder),
                "trash": _directory_ready(settings.trash_folder),
            }
        )
    database = getattr(request.app.state, "database", None)
    if database is not None:
        checks["database"] = database.ready()
    healthy = all(checks.values())
    return JSONResponse(
        {"status": "ok" if healthy else "degraded", "checks": checks},
        status_code=200 if healthy else 503,
    )


@router.get("/metrics", include_in_schema=False)
def metrics(request: Request) -> Response:
    if not request.app.state.settings.metrics_enabled:
        return Response(status_code=404)
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
