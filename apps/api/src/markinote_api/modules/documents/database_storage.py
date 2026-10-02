"""Transactional, tenant-scoped document and trash persistence."""
from __future__ import annotations

import os
import unicodedata
import uuid
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any

from sqlalchemy import Boolean, DateTime, Integer, LargeBinary, String, UniqueConstraint, delete, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from markinote_api.modules.conversations.repository import Base, Database
from markinote_api.platform.files import safe_filename
from markinote_api.platform.paths import PathValidationError, normalize_relative_path

from .errors import (
    DocumentAlreadyExists,
    DocumentCapacityExceeded,
    DocumentConflict,
    DocumentNotFound,
    DocumentPathError,
    DocumentValidationError,
)
from .storage import allowed_file, content_version


class DocumentRecord(Base):
    __tablename__ = "documents"
    __table_args__ = (UniqueConstraint("user_id", "path_key", name="uq_documents_user_path"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    path: Mapped[str] = mapped_column(String(1024), nullable=False)
    path_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    is_folder: Mapped[bool] = mapped_column(Boolean, nullable=False)
    content: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    modified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    trash_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    original_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


def _utc_iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.isoformat()


class DatabaseDocumentStorage:
    """Database is the sole source of truth; no document JSON or file cache is used."""

    def __init__(
        self,
        database: Database,
        user_id: str,
        *,
        allowed_extensions: set[str] | frozenset[str] | tuple[str, ...],
        max_document_bytes: int,
        max_library_bytes: int,
        trash_max_items: int,
        trash_max_bytes: int,
    ) -> None:
        self.database = database
        self.user_id = user_id
        self.allowed_extensions = frozenset(ext.lower().lstrip(".") for ext in allowed_extensions)
        self.max_document_bytes = max(1, int(max_document_bytes))
        self.max_library_bytes = max(0, int(max_library_bytes))
        self.trash_max_items = max(0, int(trash_max_items))
        self.trash_max_bytes = max(0, int(trash_max_bytes))

    @staticmethod
    def _key(path: str) -> str:
        return unicodedata.normalize("NFC", path).casefold()

    @classmethod
    def _path(cls, value: str, *, allow_root: bool) -> str:
        try:
            normalized = normalize_relative_path(value, allow_empty=allow_root)
            for component in normalized.split("/") if normalized else ():
                safe_filename(component)
            return normalized
        except (PathValidationError, TypeError, ValueError) as error:
            raise DocumentPathError("Invalid document path") from error

    @staticmethod
    def _name(value: str) -> str:
        try:
            return safe_filename(value)
        except (TypeError, ValueError) as error:
            raise DocumentValidationError("Invalid document name") from error

    def _extension(self, filename: str) -> None:
        if not allowed_file(filename, self.allowed_extensions):
            raise DocumentValidationError("Unsupported document format")

    def _payload(self, content: bytes) -> None:
        if len(content) > self.max_document_bytes:
            raise DocumentCapacityExceeded(
                "Document content is too large",
                details={"max_bytes": self.max_document_bytes},
            )
        try:
            content.decode("utf-8")
        except UnicodeDecodeError as error:
            raise DocumentValidationError("Document must contain valid UTF-8 text") from error

    def _record(self, session: Session, path: str, *, include_trash: bool = False) -> DocumentRecord | None:
        query = select(DocumentRecord).where(
            DocumentRecord.user_id == self.user_id,
            DocumentRecord.path_key == self._key(path),
        )
        if not include_trash:
            query = query.where(DocumentRecord.trash_id.is_(None))
        return session.scalar(query)

    def _require_parent(self, session: Session, path: str) -> None:
        parent = str(PurePosixPath(path).parent)
        if parent == ".":
            return
        record = self._record(session, parent)
        if record is None:
            raise DocumentNotFound("Parent folder does not exist")
        if not record.is_folder:
            raise DocumentValidationError("Parent path is not a folder")

    def _library_bytes(self, session: Session) -> int:
        return int(
            session.scalar(
                select(func.coalesce(func.sum(func.length(DocumentRecord.content)), 0)).where(
                    DocumentRecord.user_id == self.user_id,
                    DocumentRecord.trash_id.is_(None),
                    DocumentRecord.is_folder.is_(False),
                )
            )
            or 0
        )

    def _capacity(self, session: Session, incoming: int, replaced: int = 0) -> None:
        projected = self._library_bytes(session) - replaced + incoming
        if self.max_library_bytes and projected > self.max_library_bytes:
            raise DocumentCapacityExceeded(
                "Document library capacity exceeded",
                details={"max_bytes": self.max_library_bytes, "projected_bytes": projected},
            )

    @staticmethod
    def _entry(record: DocumentRecord) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": PurePosixPath(record.path).name,
            "type": "folder" if record.is_folder else "file",
            "path": record.path,
            "modified": _utc_iso(record.modified_at),
        }
        if not record.is_folder:
            payload["size"] = len(record.content or b"")
        return payload

    def list_directory(self, relative_path: str = "") -> tuple[list[dict[str, Any]], str]:
        normalized = self._path(relative_path, allow_root=True)
        with self.database.session() as session:
            if normalized:
                directory = self._record(session, normalized)
                if directory is None:
                    raise DocumentNotFound("Folder does not exist")
                if not directory.is_folder:
                    raise DocumentValidationError("Path is not a folder")
            prefix = f"{normalized}/" if normalized else ""
            rows = session.scalars(
                select(DocumentRecord).where(
                    DocumentRecord.user_id == self.user_id,
                    DocumentRecord.trash_id.is_(None),
                    DocumentRecord.path.like(f"{prefix}%"),
                )
            ).all()
        items = [self._entry(row) for row in rows if "/" not in row.path[len(prefix):]]
        items.sort(key=lambda item: (item["type"] != "folder", str(item["name"]).casefold()))
        return items, normalized

    def search(self, query: str, *, limit: int) -> dict[str, Any]:
        cleaned = unicodedata.normalize("NFC", query.strip())
        if not cleaned:
            raise DocumentValidationError("Search query cannot be empty")
        needle = cleaned.casefold()
        with self.database.session() as session:
            rows = list(session.scalars(
                select(DocumentRecord)
                .where(
                    DocumentRecord.user_id == self.user_id,
                    DocumentRecord.trash_id.is_(None),
                    func.lower(DocumentRecord.path).contains(needle),
                )
                .order_by(DocumentRecord.path)
            ).all())
        rows.sort(
            key=lambda row: (
                0 if PurePosixPath(row.path).name.casefold() == needle else 1,
                row.path.count("/"),
                row.path.casefold(),
            )
        )
        result_limit = max(1, int(limit))
        return {
            "items": [self._entry(row) for row in rows[:result_limit]],
            "query": cleaned,
            "total": len(rows),
            "truncated": len(rows) > result_limit,
        }

    def read(self, relative_path: str) -> dict[str, Any]:
        normalized = self._path(relative_path, allow_root=False)
        with self.database.session() as session:
            record = self._record(session, normalized)
            if record is None:
                raise DocumentNotFound("Document does not exist")
            if record.is_folder:
                raise DocumentValidationError("Path is not a document")
            raw = record.content or b""
            modified = record.modified_at
        return {
            "path": normalized,
            "filename": PurePosixPath(normalized).name,
            "content": raw.decode("utf-8"),
            "size": len(raw),
            "modified": _utc_iso(modified),
            "version": content_version(raw),
        }

    @staticmethod
    def _normalize_version(value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if normalized.startswith("W/"):
            normalized = normalized[2:].strip()
        if len(normalized) >= 2 and normalized[0] == normalized[-1] == '"':
            normalized = normalized[1:-1]
        return normalized

    def save(self, relative_path: str, content: bytes, *, expected_version: str | None = None) -> dict[str, Any]:
        self._payload(content)
        normalized = self._path(relative_path, allow_root=False)
        with self.database.session() as session, session.begin():
            record = self._record(session, normalized)
            if record is None:
                raise DocumentNotFound("Document does not exist")
            if record.is_folder:
                raise DocumentValidationError("Path is not a document")
            current = record.content or b""
            expected = self._normalize_version(expected_version)
            if expected is not None and expected != content_version(current):
                raise DocumentConflict(
                    "Document was modified by another operation",
                    details={"current_version": content_version(current)},
                )
            self._capacity(session, len(content), len(current))
            record.content = content
            record.modified_at = datetime.now(UTC)
        return {
            "path": normalized,
            "filename": PurePosixPath(normalized).name,
            "size": len(content),
            "version": content_version(content),
        }

    def create_folder(self, parent_path: str, name: str) -> dict[str, Any]:
        parent = self._path(parent_path, allow_root=True)
        clean_name = self._name(name)
        path = f"{parent}/{clean_name}" if parent else clean_name
        with self.database.session() as session, session.begin():
            self._require_parent(session, path)
            if self._record(session, path) is not None:
                raise DocumentAlreadyExists("Folder already exists")
            session.add(
                DocumentRecord(
                    user_id=self.user_id,
                    path=path,
                    path_key=self._key(path),
                    is_folder=True,
                    content=None,
                    modified_at=datetime.now(UTC),
                    trash_id=None,
                    original_path=None,
                    deleted_at=None,
                )
            )
        return {"folder_name": clean_name, "path": path}

    def create_file(self, parent_path: str, name: str, content: bytes) -> dict[str, Any]:
        parent = self._path(parent_path, allow_root=True)
        clean_name = self._name(name)
        self._extension(clean_name)
        self._payload(content)
        path = f"{parent}/{clean_name}" if parent else clean_name
        with self.database.session() as session, session.begin():
            self._require_parent(session, path)
            if self._record(session, path) is not None:
                raise DocumentAlreadyExists("Document already exists")
            self._capacity(session, len(content))
            session.add(
                DocumentRecord(
                    user_id=self.user_id,
                    path=path,
                    path_key=self._key(path),
                    is_folder=False,
                    content=content,
                    modified_at=datetime.now(UTC),
                    trash_id=None,
                    original_path=None,
                    deleted_at=None,
                )
            )
        return {"file_name": clean_name, "path": path, "size": len(content), "version": content_version(content)}

    def _ensure_folders(self, session: Session, path: str) -> None:
        current = ""
        for component in path.split("/") if path else ():
            current = f"{current}/{component}" if current else component
            existing = self._record(session, current)
            if existing is not None:
                if not existing.is_folder:
                    raise DocumentValidationError("Upload path contains a document")
                continue
            session.add(
                DocumentRecord(
                    user_id=self.user_id,
                    path=current,
                    path_key=self._key(current),
                    is_folder=True,
                    content=None,
                    modified_at=datetime.now(UTC),
                    trash_id=None,
                    original_path=None,
                    deleted_at=None,
                )
            )
            session.flush()

    def _unique_path(self, session: Session, directory: str, filename: str) -> str:
        candidate = f"{directory}/{filename}" if directory else filename
        if self._record(session, candidate) is None:
            return candidate
        stem, suffix = os.path.splitext(filename)
        stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        number = 1
        while True:
            tail = f"{stem}_{stamp}{suffix}" if number == 1 else f"{stem}_{stamp}_{number}{suffix}"
            candidate = f"{directory}/{tail}" if directory else tail
            if self._record(session, candidate) is None:
                return candidate
            number += 1

    def upload(self, target_path: str, filename: str, content: bytes) -> dict[str, Any]:
        target = self._path(target_path, allow_root=True)
        clean_name = self._name(filename)
        self._extension(clean_name)
        self._payload(content)
        with self.database.session() as session, session.begin():
            self._ensure_folders(session, target)
            path = self._unique_path(session, target, clean_name)
            self._capacity(session, len(content))
            session.add(
                DocumentRecord(
                    user_id=self.user_id,
                    path=path,
                    path_key=self._key(path),
                    is_folder=False,
                    content=content,
                    modified_at=datetime.now(UTC),
                    trash_id=None,
                    original_path=None,
                    deleted_at=None,
                )
            )
        return {"filename": PurePosixPath(path).name, "path": path, "size": len(content), "version": content_version(content)}

    def _move_exact(self, session: Session, source: str, destination: str) -> None:
        source_record = self._record(session, source)
        if source_record is None:
            raise DocumentNotFound("Source does not exist")
        if destination == source or destination.startswith(f"{source}/"):
            raise DocumentValidationError("Cannot move a folder into itself")
        self._require_parent(session, destination)
        if self._record(session, destination) is not None:
            raise DocumentAlreadyExists("Destination already exists")
        if not source_record.is_folder:
            self._extension(PurePosixPath(destination).name)
        rows = session.scalars(
            select(DocumentRecord).where(
                DocumentRecord.user_id == self.user_id,
                DocumentRecord.trash_id.is_(None),
                (DocumentRecord.path == source) | DocumentRecord.path.startswith(f"{source}/"),
            )
        ).all()
        now = datetime.now(UTC)
        for row in rows:
            suffix = row.path[len(source):]
            row.path = f"{destination}{suffix}"
            row.path_key = self._key(row.path)
            row.modified_at = now

    def move(self, source_path: str, target_path: str) -> dict[str, Any]:
        source = self._path(source_path, allow_root=False)
        target = self._path(target_path, allow_root=True)
        with self.database.session() as session, session.begin():
            if target:
                target_record = self._record(session, target)
                if target_record is None or not target_record.is_folder:
                    raise DocumentValidationError("Target must be a folder")
            destination = self._unique_path(session, target, PurePosixPath(source).name)
            self._move_exact(session, source, destination)
        return {"source_path": source, "new_path": destination, "filename": PurePosixPath(destination).name}

    def rename(self, old_path: str, new_name: str) -> dict[str, Any]:
        source = self._path(old_path, allow_root=False)
        clean_name = self._name(new_name)
        parent = str(PurePosixPath(source).parent)
        destination = clean_name if parent == "." else f"{parent}/{clean_name}"
        with self.database.session() as session, session.begin():
            self._move_exact(session, source, destination)
        return {"old_path": source, "new_path": destination, "new_name": clean_name}

    def relocate(self, source_path: str, destination_path: str) -> dict[str, Any]:
        source = self._path(source_path, allow_root=False)
        destination = self._path(destination_path, allow_root=False)
        with self.database.session() as session, session.begin():
            self._move_exact(session, source, destination)
        return {"source_path": source, "new_path": destination, "filename": PurePosixPath(destination).name}

    def _trash_usage(self, session: Session) -> tuple[int, int]:
        count = int(
            session.scalar(
                select(func.count(func.distinct(DocumentRecord.trash_id))).where(
                    DocumentRecord.user_id == self.user_id,
                    DocumentRecord.trash_id.is_not(None),
                )
            )
            or 0
        )
        size = int(
            session.scalar(
                select(func.coalesce(func.sum(func.length(DocumentRecord.content)), 0)).where(
                    DocumentRecord.user_id == self.user_id,
                    DocumentRecord.trash_id.is_not(None),
                )
            )
            or 0
        )
        return count, size

    def _prune_trash(self, session: Session) -> None:
        while True:
            count, size = self._trash_usage(session)
            if not ((self.trash_max_items and count > self.trash_max_items) or (self.trash_max_bytes and size > self.trash_max_bytes)):
                return
            oldest = session.execute(
                select(DocumentRecord.trash_id, func.min(DocumentRecord.deleted_at))
                .where(DocumentRecord.user_id == self.user_id, DocumentRecord.trash_id.is_not(None))
                .group_by(DocumentRecord.trash_id)
                .order_by(func.min(DocumentRecord.deleted_at))
                .limit(1)
            ).first()
            if oldest is None:
                return
            session.execute(
                delete(DocumentRecord).where(
                    DocumentRecord.user_id == self.user_id,
                    DocumentRecord.trash_id == oldest[0],
                )
            )
            session.flush()

    def delete(self, relative_path: str) -> dict[str, Any]:
        normalized = self._path(relative_path, allow_root=False)
        with self.database.session() as session, session.begin():
            root = self._record(session, normalized)
            if root is None:
                raise DocumentNotFound("Document or folder does not exist")
            rows = session.scalars(
                select(DocumentRecord).where(
                    DocumentRecord.user_id == self.user_id,
                    DocumentRecord.trash_id.is_(None),
                    (DocumentRecord.path == normalized) | DocumentRecord.path.startswith(f"{normalized}/"),
                )
            ).all()
            size = sum(len(row.content or b"") for row in rows)
            if self.trash_max_bytes and size > self.trash_max_bytes:
                raise DocumentCapacityExceeded("Item exceeds trash capacity", details={"max_bytes": self.trash_max_bytes})
            trash_id = f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')}_{uuid.uuid4().hex[:16]}"
            deleted_at = datetime.now(UTC)
            for row in rows:
                original = row.path
                row.original_path = original
                row.path = f"__trash__/{trash_id}/{original}"
                row.path_key = self._key(row.path)
                row.trash_id = trash_id
                row.deleted_at = deleted_at
                row.modified_at = deleted_at
            session.flush()
            self._prune_trash(session)
        return {
            "id": trash_id,
            "original_path": normalized,
            "item_type": "folder" if root.is_folder else "file",
            "size": size,
            "deleted_at": deleted_at.isoformat(),
        }

    def delete_with_external_snapshot(self, relative_path: str) -> dict[str, Any]:
        normalized = self._path(relative_path, allow_root=False)
        with self.database.session() as session, session.begin():
            root = self._record(session, normalized)
            if root is None:
                raise DocumentNotFound("Document or folder does not exist")
            item_type = "folder" if root.is_folder else "file"
            session.execute(
                delete(DocumentRecord).where(
                    DocumentRecord.user_id == self.user_id,
                    DocumentRecord.trash_id.is_(None),
                    (DocumentRecord.path == normalized) | DocumentRecord.path.startswith(f"{normalized}/"),
                )
            )
        return {"path": normalized, "item_type": item_type}

    def list_trash(self) -> list[dict[str, Any]]:
        with self.database.session() as session:
            rows = session.scalars(
                select(DocumentRecord)
                .where(DocumentRecord.user_id == self.user_id, DocumentRecord.trash_id.is_not(None))
                .order_by(DocumentRecord.deleted_at.desc())
            ).all()
        groups: dict[str, list[DocumentRecord]] = {}
        for row in rows:
            groups.setdefault(str(row.trash_id), []).append(row)
        items = []
        for trash_id, records in groups.items():
            root = min(records, key=lambda row: len(row.original_path or ""))
            items.append(
                {
                    "id": trash_id,
                    "original_path": root.original_path,
                    "item_type": "folder" if root.is_folder else "file",
                    "size": sum(len(row.content or b"") for row in records),
                    "deleted_at": _utc_iso(root.deleted_at or root.modified_at),
                }
            )
        return items

    def restore(self, trash_id: str) -> dict[str, Any]:
        try:
            clean_id = safe_filename(trash_id)
        except (TypeError, ValueError) as error:
            raise DocumentNotFound("Trash item does not exist") from error
        with self.database.session() as session, session.begin():
            rows = session.scalars(
                select(DocumentRecord).where(
                    DocumentRecord.user_id == self.user_id,
                    DocumentRecord.trash_id == clean_id,
                )
            ).all()
            if not rows:
                raise DocumentNotFound("Trash item does not exist")
            root = min(rows, key=lambda row: len(row.original_path or ""))
            for row in rows:
                if not row.original_path or self._record(session, row.original_path) is not None:
                    raise DocumentAlreadyExists("Original path already contains an item")
            for row in rows:
                row.path = str(row.original_path)
                row.path_key = self._key(row.path)
                row.trash_id = None
                row.original_path = None
                row.deleted_at = None
                row.modified_at = datetime.now(UTC)
            path = str(root.path)
            item_type = "folder" if root.is_folder else "file"
        return {"id": clean_id, "path": path, "item_type": item_type}

    def folders(self) -> list[dict[str, Any]]:
        with self.database.session() as session:
            rows = session.scalars(
                select(DocumentRecord).where(
                    DocumentRecord.user_id == self.user_id,
                    DocumentRecord.trash_id.is_(None),
                    DocumentRecord.is_folder.is_(True),
                ).order_by(DocumentRecord.path)
            ).all()
        return [
            {"path": "", "name": "Root", "level": 0},
            *[
                {"path": row.path, "name": PurePosixPath(row.path).name, "level": row.path.count("/") + 1}
                for row in rows
            ],
        ]

    def check_updates(self, directory_path: str = "", file_path: str = "") -> dict[str, Any]:
        directory = self._path(directory_path, allow_root=True)
        file = self._path(file_path, allow_root=True)
        with self.database.session() as session:
            prefix = f"{directory}/" if directory else ""
            dir_modified = session.scalar(
                select(func.max(DocumentRecord.modified_at)).where(
                    DocumentRecord.user_id == self.user_id,
                    DocumentRecord.trash_id.is_(None),
                    DocumentRecord.path.like(f"{prefix}%"),
                )
            )
            record = self._record(session, file) if file else None
        result: dict[str, Any] = {
            "dir_mtime": dir_modified.timestamp() if dir_modified else 0.0,
            "file_mtime": record.modified_at.timestamp() if record else 0.0,
        }
        if record is not None and not record.is_folder:
            result["version"] = content_version(record.content or b"")
        return result

    def snapshot(self, path: str) -> list[dict[str, Any]]:
        """Return a complete in-database snapshot used by database rollback records."""
        normalized = self._path(path, allow_root=False)
        with self.database.session() as session:
            rows = session.scalars(
                select(DocumentRecord).where(
                    DocumentRecord.user_id == self.user_id,
                    DocumentRecord.trash_id.is_(None),
                    (DocumentRecord.path == normalized) | DocumentRecord.path.startswith(f"{normalized}/"),
                )
            ).all()
        return [
            {"path": row.path, "is_folder": row.is_folder, "content": row.content}
            for row in rows
        ]

    def replace_snapshot(self, path: str, snapshot: list[dict[str, Any]]) -> None:
        normalized = self._path(path, allow_root=False)
        with self.database.session() as session, session.begin():
            session.execute(
                delete(DocumentRecord).where(
                    DocumentRecord.user_id == self.user_id,
                    DocumentRecord.trash_id.is_(None),
                    (DocumentRecord.path == normalized) | DocumentRecord.path.startswith(f"{normalized}/"),
                )
            )
            now = datetime.now(UTC)
            for item in snapshot:
                item_path = self._path(str(item["path"]), allow_root=False)
                session.add(
                    DocumentRecord(
                        user_id=self.user_id,
                        path=item_path,
                        path_key=self._key(item_path),
                        is_folder=bool(item["is_folder"]),
                        content=item.get("content"),
                        modified_at=now,
                        trash_id=None,
                        original_path=None,
                        deleted_at=None,
                    )
                )
