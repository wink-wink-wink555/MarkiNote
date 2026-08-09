"""Document use cases shared by API and agent workflows."""

from __future__ import annotations

from typing import Any

from .errors import DocumentValidationError
from .storage import LocalDocumentStorage


class DocumentService:
    """Application facade with JSON-friendly transport-neutral results."""

    def __init__(self, storage: LocalDocumentStorage):
        self.storage = storage

    @staticmethod
    def _text(value: Any, field: str, *, allow_empty: bool = True) -> str:
        if not isinstance(value, str):
            raise DocumentValidationError(f"{field} 必须为字符串")
        if not allow_empty and not value:
            raise DocumentValidationError(f"{field} 不能为空")
        return value

    def list(self, path: str = "") -> dict[str, Any]:
        items, normalized = self.storage.list_directory(self._text(path, "path"))
        return {"items": items, "current_path": normalized}

    def search(self, query: str, *, limit: int = 80) -> dict[str, Any]:
        clean_query = self._text(query, "query", allow_empty=False).strip()
        if not clean_query:
            raise DocumentValidationError("搜索关键词不能为空")
        return self.storage.search(clean_query, limit=max(1, min(int(limit), 200)))

    def read(self, path: str) -> dict[str, Any]:
        return self.storage.read(self._text(path, "path", allow_empty=False))

    def save(
        self,
        path: str,
        content: str,
        *,
        expected_version: str | None = None,
    ) -> dict[str, Any]:
        clean_path = self._text(path, "path", allow_empty=False)
        clean_content = self._text(content, "content")
        if expected_version is not None:
            expected_version = self._text(expected_version, "expected_version", allow_empty=False)
        return self.storage.save(
            clean_path,
            clean_content.encode("utf-8"),
            expected_version=expected_version,
        )

    def create_folder(self, path: str, name: str) -> dict[str, Any]:
        return self.storage.create_folder(
            self._text(path, "path"),
            self._text(name, "name", allow_empty=False),
        )

    def create_file(self, path: str, name: str, content: str | None = None) -> dict[str, Any]:
        clean_name = self._text(name, "name", allow_empty=False)
        if content is None:
            content = f"# {clean_name.rsplit('.', 1)[0]}\n\n"
        clean_content = self._text(content, "content")
        return self.storage.create_file(
            self._text(path, "path"), clean_name, clean_content.encode("utf-8")
        )

    def upload(self, path: str, filename: str, content: bytes) -> dict[str, Any]:
        if not isinstance(content, bytes):
            raise DocumentValidationError("上传内容必须为字节数据")
        return self.storage.upload(
            self._text(path, "path"),
            self._text(filename, "filename", allow_empty=False),
            content,
        )

    def move(self, source: str, target: str) -> dict[str, Any]:
        return self.storage.move(
            self._text(source, "source", allow_empty=False),
            self._text(target, "target"),
        )

    def rename(self, old_path: str, new_name: str) -> dict[str, Any]:
        return self.storage.rename(
            self._text(old_path, "old_path", allow_empty=False),
            self._text(new_name, "new_name", allow_empty=False),
        )

    def relocate(self, source: str, destination: str) -> dict[str, Any]:
        return self.storage.relocate(
            self._text(source, "source", allow_empty=False),
            self._text(destination, "destination", allow_empty=False),
        )

    def delete(self, path: str) -> dict[str, Any]:
        return self.storage.delete(self._text(path, "path", allow_empty=False))

    def delete_with_external_snapshot(self, path: str) -> dict[str, Any]:
        return self.storage.delete_with_external_snapshot(
            self._text(path, "path", allow_empty=False)
        )

    def check_updates(self, path: str = "", file: str = "") -> dict[str, Any]:
        return self.storage.check_updates(self._text(path, "path"), self._text(file, "file"))

    def folders(self) -> dict[str, Any]:
        return {"folders": self.storage.folders()}

    def list_trash(self) -> dict[str, Any]:
        return {"items": self.storage.list_trash()}

    def restore(self, trash_id: str) -> dict[str, Any]:
        return self.storage.restore(self._text(trash_id, "trash_id", allow_empty=False))
