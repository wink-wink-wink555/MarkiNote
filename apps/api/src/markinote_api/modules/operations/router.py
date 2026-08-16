"""Audited backup inspection and rollback use cases."""
from __future__ import annotations

from contextlib import nullcontext
from enum import StrEnum
from typing import Any, Literal

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from markinote_api.platform.errors import Problem
from markinote_api.platform.metrics import OPERATION_ROLLBACK_ATTEMPTS
from markinote_api.platform.paths import PathValidationError
from markinote_api.platform.tenancy import services_for_request

router = APIRouter(prefix="/api/v1/operations", tags=["operations"])


class RollbackRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    backup_group_id: str = Field(min_length=1, max_length=128, alias="backupGroupId")
    # Whole-group rollback is intentionally not exposed: it can span multiple
    # files and cannot promise atomic compensation. Callers must select the
    # exact operation they intend to restore.
    operation_index: int = Field(ge=0, alias="operationIndex")


class BackupState(StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    ABANDONED = "abandoned"
    QUARANTINED = "quarantined"


class BackupManifest(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    timestamp: str | None = None
    conversation_id: str | None = None
    state: BackupState | None = None
    completed_at: str | None = None
    operations: list[dict[str, Any]] = Field(default_factory=list)


class BackupListResponse(BaseModel):
    items: list[BackupManifest]


class RollbackResponse(BaseModel):
    success: Literal[True] = True
    message: str


@router.get("/backups", response_model=BackupListResponse)
def list_backups(request: Request, limit: int = Query(default=50, ge=1, le=200)) -> dict[str, Any]:
    return {"items": services_for_request(request).backup_manager.list_backups(limit=limit)}


@router.post("/rollback", response_model=RollbackResponse)
def rollback_operation(body: RollbackRequest, request: Request) -> dict[str, Any]:
    services = services_for_request(request)
    manager = services.backup_manager
    try:
        manifest = manager.get_group_manifest(body.backup_group_id)
    except PathValidationError as error:
        raise Problem(
            400,
            "invalid_backup_id",
            "Invalid backup identifier",
            "The backup identifier does not match the accepted format.",
        ) from error
    if manifest is None:
        raise Problem(404, "backup_not_found", "Backup not found", "The requested backup group does not exist.")

    conversation_id = manifest.get("conversation_id")
    guard = (
        services.agent_service.exclusive_conversation(str(conversation_id))
        if conversation_id
        else nullcontext()
    )
    with guard:
        try:
            ok, message = manager.rollback_operation(body.backup_group_id, body.operation_index)
        except Exception:
            OPERATION_ROLLBACK_ATTEMPTS.labels("v1_api", "failure").inc()
            raise
        OPERATION_ROLLBACK_ATTEMPTS.labels(
            "v1_api", "success" if ok else "failure"
        ).inc()
        services.command_journal.audit(
            request_id=request.state.request_id,
            conversation_id=str(conversation_id) if conversation_id else None,
            action="rollback",
            target=body.backup_group_id,
            outcome="completed" if ok else "failed",
            details={"operation_index": body.operation_index},
        )
    if not ok:
        raise Problem(409, "rollback_failed", "Rollback failed", message)
    return {"success": True, "message": message}
