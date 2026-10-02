"""Versioned document API backed by the shared DocumentService."""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, Header, Query, Request, Response, UploadFile
from pydantic import BaseModel, ConfigDict, Field

from markinote_api.modules.documents.errors import DocumentCapacityExceeded, DocumentConflict
from markinote_api.modules.documents.service import DocumentService
from markinote_api.platform.metrics import DOCUMENT_CONFLICTS
from markinote_api.platform.tenancy import services_for_request

router = APIRouter(prefix="/api/v1/documents", tags=["documents"])


def get_service(request: Request) -> DocumentService:
    return services_for_request(request).document_service


class DocumentItem(BaseModel):
    model_config = ConfigDict(extra="allow")
    name: str
    type: str
    path: str
    size: int | None = None
    modified: str | None = None


class DocumentList(BaseModel):
    items: list[DocumentItem]
    current_path: str


class DocumentSearchResponse(BaseModel):
    items: list[DocumentItem]
    query: str
    total: int = Field(ge=0)
    truncated: bool


class DocumentContent(BaseModel):
    model_config = ConfigDict(extra="allow")
    path: str
    filename: str
    content: str
    size: int
    modified: str | None = None
    version: str


class SaveDocument(BaseModel):
    content: str
    expected_version: str | None = Field(default=None, alias="expectedVersion")


class CreateFolder(BaseModel):
    path: str = ""
    name: str = Field(min_length=1, max_length=232)


class CreateFile(BaseModel):
    path: str = ""
    name: str = Field(min_length=1, max_length=232)
    content: str | None = None


class MoveDocument(BaseModel):
    source: str = Field(min_length=1)
    target: str = ""


class RenameDocument(BaseModel):
    old_path: str = Field(min_length=1, alias="oldPath")
    new_name: str = Field(min_length=1, max_length=232, alias="newName")


class RestoreTrash(BaseModel):
    trash_id: str = Field(min_length=1, alias="trashId")


class SuccessResponse(BaseModel):
    success: Literal[True] = True


class StoredDocumentResponse(SuccessResponse):
    path: str
    filename: str
    size: int
    version: str


class CreatedFileResponse(SuccessResponse):
    file_name: str
    path: str
    size: int
    version: str


class CreatedFolderResponse(SuccessResponse):
    folder_name: str
    path: str


class MovedDocumentResponse(SuccessResponse):
    source_path: str
    new_path: str
    filename: str


class RenamedDocumentResponse(SuccessResponse):
    old_path: str
    new_path: str
    new_name: str


class TrashItem(BaseModel):
    id: str
    original_path: str
    item_type: Literal["file", "folder"]
    size: int
    deleted_at: str


class DeletedDocumentResponse(SuccessResponse, TrashItem):
    pass


class TrashListResponse(BaseModel):
    items: list[TrashItem]


class RestoredDocumentResponse(SuccessResponse):
    id: str
    path: str
    item_type: Literal["file", "folder"]


class FolderItem(BaseModel):
    path: str
    name: str
    level: int


class FolderListResponse(BaseModel):
    folders: list[FolderItem]


class DocumentChangesResponse(BaseModel):
    dir_mtime: float
    file_mtime: float
    version: str | None = None


@router.get("", response_model=DocumentList)
def list_documents(path: str = "", service: DocumentService = Depends(get_service)) -> DocumentList:
    result = service.list(path)
    return DocumentList(
        items=[DocumentItem.model_validate(item) for item in result["items"]],
        current_path=result["current_path"],
    )


@router.get("/search", response_model=DocumentSearchResponse)
def search_documents(
    q: str = Query(min_length=1, max_length=120),
    limit: int = Query(default=80, ge=1, le=200),
    service: DocumentService = Depends(get_service),
) -> DocumentSearchResponse:
    result = service.search(q, limit=limit)
    return DocumentSearchResponse(
        items=[DocumentItem.model_validate(item) for item in result["items"]],
        query=result["query"],
        total=result["total"],
        truncated=result["truncated"],
    )


@router.get("/content", response_model=DocumentContent)
def read_document(
    path: str,
    response: Response,
    service: DocumentService = Depends(get_service),
) -> DocumentContent:
    result = service.read(path)
    response.headers["ETag"] = f'"{result["version"]}"'
    return DocumentContent.model_validate(result)


@router.put("/content", response_model=StoredDocumentResponse)
def save_document(
    path: str,
    body: SaveDocument,
    response: Response,
    if_match: str | None = Header(default=None),
    service: DocumentService = Depends(get_service),
) -> dict[str, Any]:
    expected = if_match or body.expected_version
    try:
        result = service.save(path, body.content, expected_version=expected)
    except DocumentConflict:
        DOCUMENT_CONFLICTS.labels("v1").inc()
        raise
    response.headers["ETag"] = f'"{result["version"]}"'
    return {"success": True, **result}


@router.post("/folders", response_model=CreatedFolderResponse)
def create_folder(
    body: CreateFolder,
    service: DocumentService = Depends(get_service),
) -> dict[str, Any]:
    return {"success": True, **service.create_folder(body.path, body.name)}


@router.post("/files", response_model=CreatedFileResponse)
def create_file(
    body: CreateFile,
    service: DocumentService = Depends(get_service),
) -> dict[str, Any]:
    return {"success": True, **service.create_file(body.path, body.name, body.content)}


@router.post("/upload", response_model=StoredDocumentResponse)
async def upload_document(
    request: Request,
    path: str = Form(default=""),
    file: UploadFile = File(...),
    service: DocumentService = Depends(get_service),
) -> dict[str, Any]:
    limit = request.app.state.settings.max_document_bytes
    content = await file.read(limit + 1)
    if len(content) > limit:
        raise DocumentCapacityExceeded("The uploaded document exceeds the configured size limit.")
    return {"success": True, **service.upload(path, file.filename or "", content)}


@router.post("/move", response_model=MovedDocumentResponse)
def move_document(
    body: MoveDocument,
    service: DocumentService = Depends(get_service),
) -> dict[str, Any]:
    return {"success": True, **service.move(body.source, body.target)}


@router.post("/rename", response_model=RenamedDocumentResponse)
def rename_document(
    body: RenameDocument,
    service: DocumentService = Depends(get_service),
) -> dict[str, Any]:
    return {"success": True, **service.rename(body.old_path, body.new_name)}


@router.delete("", response_model=DeletedDocumentResponse)
def delete_document(
    path: str,
    service: DocumentService = Depends(get_service),
) -> dict[str, Any]:
    return {"success": True, **service.delete(path)}


@router.get("/folders", response_model=FolderListResponse)
def list_folders(service: DocumentService = Depends(get_service)) -> dict[str, Any]:
    return service.folders()


@router.get("/changes", response_model=DocumentChangesResponse)
def check_changes(
    path: str = "",
    file: str = "",
    service: DocumentService = Depends(get_service),
) -> dict[str, Any]:
    return service.check_updates(path, file)


@router.get("/trash", response_model=TrashListResponse)
def list_trash(service: DocumentService = Depends(get_service)) -> dict[str, Any]:
    return service.list_trash()


@router.post("/trash/restore", response_model=RestoredDocumentResponse)
def restore_trash(
    body: RestoreTrash,
    service: DocumentService = Depends(get_service),
) -> dict[str, Any]:
    return {"success": True, **service.restore(body.trash_id)}
