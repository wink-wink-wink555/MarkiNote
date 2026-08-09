"""Local-filesystem adapter for the documents application module.

All user-controlled paths pass through one canonical resolver. Mutations are
serialized per library, writes use same-directory atomic replacement, and
deletes are moved into a quota-managed recoverable trash area.
"""

from __future__ import annotations

import heapq
import json
import logging
import os
import shutil
import time
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from markinote_api.modules.documents.errors import (
    DocumentAlreadyExists,
    DocumentCapacityExceeded,
    DocumentConflict,
    DocumentNotFound,
    DocumentPathError,
    DocumentPermissionDenied,
    DocumentValidationError,
)
from markinote_api.platform.files import allowed_file, safe_filename
from markinote_api.platform.io import (
    atomic_write_bytes,
    atomic_write_json,
    content_version,
    file_version,
    resource_lock,
)
from markinote_api.platform.paths import (
    PathValidationError,
    relative_to_root,
    resolve_under_root,
    validate_storage_id,
)

LOGGER = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(slots=True)
class _SearchCandidate:
    """Reverse-ordered heap item so the least relevant retained result is first."""

    sort_key: tuple[int, int, str, str]
    payload: dict[str, Any]

    def __lt__(self, other: _SearchCandidate) -> bool:
        return self.sort_key > other.sort_key


class LocalDocumentStorage:
    """Safe LocalFS implementation of the document storage port."""

    def __init__(
        self,
        library_root: str | os.PathLike[str],
        trash_root: str | os.PathLike[str],
        *,
        allowed_extensions: set[str] | frozenset[str] | tuple[str, ...],
        max_document_bytes: int,
        max_library_bytes: int,
        trash_max_items: int,
        trash_max_bytes: int,
    ) -> None:
        self.root = Path(library_root).resolve()
        self.trash_root = Path(trash_root).resolve()
        self.allowed_extensions = frozenset(ext.lower().lstrip(".") for ext in allowed_extensions)
        self.max_document_bytes = max(1, int(max_document_bytes))
        self.max_library_bytes = max(0, int(max_library_bytes))
        self.trash_max_items = max(0, int(trash_max_items))
        self.trash_max_bytes = max(0, int(trash_max_bytes))
        self._trash_sequence = time.time_ns()

        if self.root == self.trash_root or self._is_below(self.trash_root, self.root):
            raise ValueError("TRASH_FOLDER must be outside LIBRARY_FOLDER")

        self.root.mkdir(parents=True, exist_ok=True)
        self.trash_root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _is_below(path: Path, parent: Path) -> bool:
        try:
            path.relative_to(parent)
            return path != parent
        except ValueError:
            return False

    def _resolve(
        self,
        relative_path: str,
        *,
        allow_root: bool,
        must_exist: bool = False,
    ) -> tuple[Path, str]:
        try:
            path, normalized = resolve_under_root(
                self.root,
                relative_path,
                allow_root=allow_root,
                must_exist=must_exist,
            )
            # Applying the portable filename policy to every component also
            # blocks Windows ADS syntax when the service runs on POSIX.
            for component in normalized.split("/") if normalized else ():
                safe_filename(component)
            return path, normalized
        except FileNotFoundError as exc:
            raise DocumentNotFound("文件或文件夹不存在") from exc
        except (PathValidationError, ValueError) as exc:
            raise DocumentPathError("非法路径") from exc

    def _require_document(self, path: Path, normalized: str) -> None:
        if not path.exists():
            raise DocumentNotFound("文件不存在")
        if not path.is_file():
            raise DocumentValidationError("路径不是文件")
        if not allowed_file(path.name, self.allowed_extensions):
            raise DocumentValidationError("不支持的文件格式")
        if path.is_symlink():
            raise DocumentPathError("禁止访问符号链接路径")

    def _check_payload_size(self, content: bytes) -> None:
        if len(content) > self.max_document_bytes:
            raise DocumentCapacityExceeded(
                "文件内容过大",
                details={"max_bytes": self.max_document_bytes},
            )

    @staticmethod
    def _path_size(path: Path) -> int:
        if path.is_symlink():
            return 0
        if path.is_file():
            try:
                return path.stat().st_size
            except OSError:
                return 0
        total = 0
        if not path.is_dir():
            return total
        for root, directories, files in os.walk(path, followlinks=False):
            root_path = Path(root)
            directories[:] = [
                name for name in directories if not (root_path / name).is_symlink()
            ]
            for name in files:
                candidate = root_path / name
                if candidate.is_symlink():
                    continue
                try:
                    total += candidate.stat().st_size
                except OSError:
                    continue
        return total

    def _library_size(self) -> int:
        return self._path_size(self.root)

    def _ensure_library_capacity(self, incoming_bytes: int, replaced_bytes: int = 0) -> None:
        if not self.max_library_bytes:
            return
        projected = self._library_size() - replaced_bytes + incoming_bytes
        if projected > self.max_library_bytes:
            raise DocumentCapacityExceeded(
                "文档库容量不足",
                details={
                    "max_bytes": self.max_library_bytes,
                    "projected_bytes": projected,
                },
            )

    @staticmethod
    def _entry_payload(entry: os.DirEntry[str], relative_path: str) -> dict[str, Any] | None:
        try:
            if entry.is_symlink():
                return None
            stat_info = entry.stat(follow_symlinks=False)
            if entry.is_dir(follow_symlinks=False):
                return {
                    "name": entry.name,
                    "type": "folder",
                    "path": relative_path,
                    "modified": datetime.fromtimestamp(stat_info.st_mtime).isoformat(),
                }
            if entry.is_file(follow_symlinks=False):
                return {
                    "name": entry.name,
                    "type": "file",
                    "path": relative_path,
                    "size": stat_info.st_size,
                    "modified": datetime.fromtimestamp(stat_info.st_mtime).isoformat(),
                }
        except (OSError, PermissionError):
            return None
        return None

    def list_directory(self, relative_path: str = "") -> tuple[list[dict[str, Any]], str]:
        directory, normalized = self._resolve(relative_path, allow_root=True)
        with resource_lock(self.root):
            if not directory.exists():
                raise DocumentNotFound("文件夹不存在")
            if not directory.is_dir():
                raise DocumentValidationError("路径不是文件夹")

            items: list[dict[str, Any]] = []
            try:
                with os.scandir(directory) as entries:
                    for entry in entries:
                        if entry.name.startswith("."):
                            continue
                        rel = f"{normalized}/{entry.name}" if normalized else entry.name
                        payload = self._entry_payload(entry, rel.replace("\\", "/"))
                        if payload is None:
                            continue
                        if payload["type"] == "file" and not allowed_file(
                            entry.name, self.allowed_extensions
                        ):
                            continue
                        items.append(payload)
            except PermissionError as exc:
                raise DocumentPermissionDenied("权限不足，无法读取文件夹") from exc

        items.sort(key=lambda item: (item["type"] != "folder", item["name"].casefold()))
        return items, normalized

    def search(self, query: str, *, limit: int) -> dict[str, Any]:
        """Search names and relative paths without loading document contents.

        A bounded heap retains only the best ``limit`` matches. The scan is
        O(N log K) for N visible filesystem entries and K returned results,
        while auxiliary memory remains O(D + K) for the directory stack and
        result heap.
        """
        normalized_query = unicodedata.normalize("NFC", query.strip())
        if not normalized_query:
            raise DocumentValidationError("搜索关键词不能为空")
        needle = normalized_query.casefold()
        result_limit = max(1, int(limit))
        candidates: list[_SearchCandidate] = []
        total = 0

        with resource_lock(self.root):
            stack: list[tuple[Path, str]] = [(self.root, "")]
            while stack:
                directory, prefix = stack.pop()
                try:
                    entries = os.scandir(directory)
                except (OSError, PermissionError):
                    continue

                try:
                    for entry in entries:
                        if entry.name.startswith(".") or entry.is_symlink():
                            continue
                        relative = f"{prefix}/{entry.name}" if prefix else entry.name
                        relative = relative.replace("\\", "/")
                        try:
                            is_directory = entry.is_dir(follow_symlinks=False)
                            is_document = entry.is_file(follow_symlinks=False) and allowed_file(
                                entry.name, self.allowed_extensions
                            )
                        except OSError:
                            continue
                        if is_directory:
                            stack.append((Path(entry.path), relative))
                        elif not is_document:
                            continue

                        normalized_name = unicodedata.normalize("NFC", entry.name).casefold()
                        normalized_path = unicodedata.normalize("NFC", relative).casefold()
                        if needle not in normalized_name and needle not in normalized_path:
                            continue
                        payload = self._entry_payload(entry, relative)
                        if payload is None:
                            continue

                        total += 1
                        stem = Path(entry.name).stem.casefold()
                        relevance = (
                            0 if normalized_name == needle
                            else 1 if stem == needle
                            else 2 if normalized_name.startswith(needle)
                            else 3 if needle in normalized_name
                            else 4
                        )
                        candidate = _SearchCandidate(
                            (relevance, relative.count("/"), normalized_name, normalized_path),
                            payload,
                        )
                        if len(candidates) < result_limit:
                            heapq.heappush(candidates, candidate)
                        elif candidate.sort_key < candidates[0].sort_key:
                            heapq.heapreplace(candidates, candidate)
                except (OSError, PermissionError):
                    continue
                finally:
                    entries.close()

        ordered = [candidate.payload for candidate in sorted(candidates, key=lambda item: item.sort_key)]
        return {
            "items": ordered,
            "query": normalized_query,
            "total": total,
            "truncated": total > result_limit,
        }

    def read(self, relative_path: str) -> dict[str, Any]:
        path, normalized = self._resolve(relative_path, allow_root=False)
        with resource_lock(self.root):
            self._require_document(path, normalized)
            try:
                with open(path, "rb") as stream:
                    raw = stream.read(self.max_document_bytes + 1)
                self._check_payload_size(raw)
                content = raw.decode("utf-8")
                stat_info = path.stat()
            except UnicodeDecodeError as exc:
                raise DocumentValidationError("文件不是有效的 UTF-8 文本") from exc
            except PermissionError as exc:
                raise DocumentPermissionDenied("权限不足，无法读取文件") from exc

        return {
            "path": normalized,
            "filename": path.name,
            "content": content,
            "size": len(raw),
            "modified": datetime.fromtimestamp(stat_info.st_mtime).isoformat(),
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

    def save(
        self,
        relative_path: str,
        content: bytes,
        *,
        expected_version: str | None = None,
    ) -> dict[str, Any]:
        self._check_payload_size(content)
        path, normalized = self._resolve(relative_path, allow_root=False)
        expected = self._normalize_version(expected_version)

        with resource_lock(self.root):
            self._require_document(path, normalized)
            try:
                current_size = path.stat().st_size
                if expected is not None:
                    current_version = file_version(path)
                    if expected != current_version:
                        raise DocumentConflict(
                            "文件已被其他操作修改，请刷新后重试",
                            details={"current_version": current_version},
                        )
                self._ensure_library_capacity(len(content), current_size)
                atomic_write_bytes(path, content)
            except PermissionError as exc:
                raise DocumentPermissionDenied("权限不足，无法保存文件") from exc

        return {
            "path": normalized,
            "filename": path.name,
            "size": len(content),
            "version": content_version(content),
        }

    @staticmethod
    def _validated_name(name: str) -> str:
        try:
            return safe_filename(name)
        except (TypeError, ValueError) as exc:
            raise DocumentValidationError("文件名格式非法") from exc

    def _require_allowed_extension(self, filename: str) -> None:
        if not allowed_file(filename, self.allowed_extensions):
            raise DocumentValidationError("不支持的文件格式")

    def create_folder(self, parent_path: str, name: str) -> dict[str, Any]:
        folder_name = self._validated_name(name)
        parent, parent_normalized = self._resolve(parent_path, allow_root=True)
        destination_rel = f"{parent_normalized}/{folder_name}" if parent_normalized else folder_name
        destination, destination_rel = self._resolve(destination_rel, allow_root=False)

        with resource_lock(self.root):
            if not parent.exists():
                raise DocumentNotFound("父目录不存在")
            if not parent.is_dir():
                raise DocumentValidationError("父路径不是文件夹")
            if destination.exists():
                raise DocumentAlreadyExists("文件夹已存在")
            try:
                destination.mkdir()
            except PermissionError as exc:
                raise DocumentPermissionDenied("权限不足，无法创建文件夹") from exc

        return {"folder_name": folder_name, "path": destination_rel}

    def create_file(self, parent_path: str, name: str, content: bytes) -> dict[str, Any]:
        filename = self._validated_name(name)
        self._require_allowed_extension(filename)
        self._check_payload_size(content)
        parent, parent_normalized = self._resolve(parent_path, allow_root=True)
        destination_rel = f"{parent_normalized}/{filename}" if parent_normalized else filename
        destination, destination_rel = self._resolve(destination_rel, allow_root=False)

        with resource_lock(self.root):
            if not parent.exists():
                raise DocumentNotFound("父目录不存在")
            if not parent.is_dir():
                raise DocumentValidationError("父路径不是文件夹")
            if destination.exists():
                raise DocumentAlreadyExists("文件已存在")
            self._ensure_library_capacity(len(content))
            try:
                atomic_write_bytes(destination, content)
            except PermissionError as exc:
                raise DocumentPermissionDenied("权限不足，无法创建文件") from exc

        return {
            "file_name": filename,
            "path": destination_rel,
            "size": len(content),
            "version": content_version(content),
        }

    @staticmethod
    def _unique_destination(directory: Path, filename: str) -> Path:
        destination = directory / filename
        if not destination.exists():
            return destination
        stem, suffix = os.path.splitext(filename)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        candidate = directory / f"{stem}_{timestamp}{suffix}"
        counter = 2
        while candidate.exists():
            candidate = directory / f"{stem}_{timestamp}_{counter}{suffix}"
            counter += 1
        return candidate

    def upload(self, target_path: str, filename: str, content: bytes) -> dict[str, Any]:
        clean_name = self._validated_name(filename)
        self._require_allowed_extension(clean_name)
        self._check_payload_size(content)
        target, _ = self._resolve(target_path, allow_root=True)

        with resource_lock(self.root):
            try:
                # Folder upload relies on this behavior: safe missing
                # target directories are created as part of the upload.
                target.mkdir(parents=True, exist_ok=True)
                if not target.is_dir():
                    raise DocumentValidationError("目标路径不是文件夹")
                self._ensure_library_capacity(len(content))
                destination = self._unique_destination(target, clean_name)
                atomic_write_bytes(destination, content)
            except PermissionError as exc:
                raise DocumentPermissionDenied("权限不足，无法上传文件") from exc

        normalized = relative_to_root(self.root, destination)
        return {
            "filename": destination.name,
            "path": normalized,
            "size": len(content),
            "version": content_version(content),
        }

    def move(self, source_path: str, target_path: str) -> dict[str, Any]:
        source, source_normalized = self._resolve(source_path, allow_root=False)
        target, _ = self._resolve(target_path, allow_root=True)

        with resource_lock(self.root):
            if not source.exists():
                raise DocumentNotFound("源文件不存在")
            if source.is_symlink():
                raise DocumentPathError("禁止移动符号链接")
            if source == target or self._is_below(target, source):
                raise DocumentValidationError("不能将文件夹移动到自身内部")
            if source.parent == target:
                raise DocumentValidationError("项目已位于目标文件夹中")
            try:
                target.mkdir(parents=True, exist_ok=True)
                if not target.is_dir():
                    raise DocumentValidationError("目标必须是文件夹")
                destination = self._unique_destination(target, source.name)
                shutil.move(os.fspath(source), os.fspath(destination))
            except PermissionError as exc:
                raise DocumentPermissionDenied("权限不足，无法移动文件") from exc

        return {
            "source_path": source_normalized,
            "new_path": relative_to_root(self.root, destination),
            "filename": destination.name,
        }

    def rename(self, old_path: str, new_name: str) -> dict[str, Any]:
        source, old_normalized = self._resolve(old_path, allow_root=False)
        clean_name = self._validated_name(new_name)

        with resource_lock(self.root):
            if not source.exists():
                raise DocumentNotFound("文件或文件夹不存在")
            if source.is_file():
                self._require_allowed_extension(clean_name)
            destination = source.parent / clean_name
            destination_rel = relative_to_root(self.root, destination)
            destination, destination_rel = self._resolve(destination_rel, allow_root=False)
            if destination.exists():
                raise DocumentAlreadyExists(f'名称"{clean_name}"已被使用')
            try:
                os.replace(source, destination)
            except PermissionError as exc:
                raise DocumentPermissionDenied("权限不足，无法重命名") from exc

        return {
            "old_path": old_normalized,
            "new_path": destination_rel,
            "new_name": clean_name,
        }

    def relocate(self, source_path: str, destination_path: str) -> dict[str, Any]:
        """Move or rename to one exact, already-parented destination.

        The public UI's ``move`` use case targets a directory and resolves
        collisions automatically. Agent tools need an exact destination, but
        must still share the same portable path and extension invariants.
        """
        source, source_normalized = self._resolve(source_path, allow_root=False)
        destination, destination_normalized = self._resolve(
            destination_path,
            allow_root=False,
        )

        with resource_lock(self.root):
            if not source.exists():
                raise DocumentNotFound("source does not exist")
            if source.is_symlink():
                raise DocumentPathError("symbolic links cannot be moved")
            if destination.exists():
                raise DocumentAlreadyExists("destination already exists")
            if not destination.parent.is_dir():
                raise DocumentNotFound("destination parent does not exist")
            if source == destination or self._is_below(destination, source):
                raise DocumentValidationError("cannot move a folder into itself")
            if source.is_file():
                self._require_allowed_extension(destination.name)
            try:
                shutil.move(os.fspath(source), os.fspath(destination))
            except PermissionError as exc:
                raise DocumentPermissionDenied("insufficient permission to move item") from exc

        return {
            "source_path": source_normalized,
            "new_path": destination_normalized,
            "filename": destination.name,
        }

    def _trash_records(self) -> list[tuple[Path, int, float]]:
        records: list[tuple[Path, int, float]] = []
        try:
            entries = list(self.trash_root.iterdir())
        except FileNotFoundError:
            return records
        for record in entries:
            if record.is_symlink() or not record.is_dir():
                continue
            try:
                records.append((record, self._path_size(record / "payload"), record.stat().st_mtime))
            except OSError:
                continue
        records.sort(key=lambda item: (item[2], item[0].name))
        return records

    def _remove_trash_record(self, record: Path) -> None:
        try:
            record.resolve(strict=False).relative_to(self.trash_root)
        except ValueError as exc:
            raise RuntimeError("refusing to prune trash outside configured root") from exc
        if record.is_symlink():
            record.unlink(missing_ok=True)
        elif record.is_dir():
            shutil.rmtree(record)

    def _validate_trash_item_capacity(self, incoming_bytes: int) -> None:
        if self.trash_max_bytes and incoming_bytes > self.trash_max_bytes:
            raise DocumentCapacityExceeded(
                "项目超过回收站单项容量，未执行删除",
                details={"max_bytes": self.trash_max_bytes},
            )
    def _prune_trash_capacity(self) -> None:
        records = self._trash_records()
        total_bytes = sum(record[1] for record in records)
        while records and (
            (self.trash_max_items and len(records) > self.trash_max_items)
            or (self.trash_max_bytes and total_bytes > self.trash_max_bytes)
        ):
            oldest, size, _ = records.pop(0)
            self._remove_trash_record(oldest)
            total_bytes -= size

    def delete(self, relative_path: str) -> dict[str, Any]:
        source, normalized = self._resolve(relative_path, allow_root=False)

        with resource_lock(self.root), resource_lock(self.trash_root):
            if not source.exists():
                raise DocumentNotFound("文件或文件夹不存在")
            if source.is_symlink():
                raise DocumentPathError("禁止删除符号链接路径")
            item_type = "file" if source.is_file() else "folder" if source.is_dir() else None
            if item_type is None:
                raise DocumentValidationError("不支持的文件类型")
            size = self._path_size(source)
            # Validate first, but only prune old recoverable records after
            # this delete commits. A failed delete must not destroy unrelated
            # trash entries.
            self._validate_trash_item_capacity(size)

            deleted_at = _utc_now()
            # Some filesystems and Windows clocks expose the same timestamp for
            # consecutive deletes. Keep the lexicographic tie-breaker monotonic
            # so capacity pruning cannot discard the newer record at random.
            self._trash_sequence = max(self._trash_sequence + 1, time.time_ns())
            trash_id = (
                f"{deleted_at.strftime('%Y%m%dT%H%M%S%fZ')}"
                f"_{self._trash_sequence:016x}_{uuid.uuid4().hex[:16]}"
            )
            record = self.trash_root / trash_id
            payload = record / "payload"
            metadata = {
                "id": trash_id,
                "original_path": normalized,
                "item_type": item_type,
                "size": size,
                "deleted_at": deleted_at.isoformat(),
            }

            try:
                record.mkdir()
                shutil.move(os.fspath(source), os.fspath(payload))
                try:
                    atomic_write_json(record / "metadata.json", metadata)
                except Exception:
                    source.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(os.fspath(payload), os.fspath(source))
                    raise
            except PermissionError as exc:
                if record.exists() and not any(record.iterdir()):
                    record.rmdir()
                raise DocumentPermissionDenied("权限不足，无法删除项目") from exc
            except Exception:
                if record.exists() and not any(record.iterdir()):
                    record.rmdir()
                raise

            try:
                self._prune_trash_capacity()
            except OSError:
                # The delete is already committed. Retention can be retried;
                # returning an error would falsely invite a second delete.
                LOGGER.warning("trash retention cleanup failed")

        return metadata

    def delete_with_external_snapshot(self, relative_path: str) -> dict[str, Any]:
        """Delete after a caller has durably captured its own recovery snapshot.

        Agent operations use BackupManager as their recovery journal. Sending
        the same payload to the user trash as well would create a duplicate
        restore record that conflicts after an agent rollback.
        """
        source, normalized = self._resolve(relative_path, allow_root=False)
        with resource_lock(self.root):
            if not source.exists():
                raise DocumentNotFound("document or folder does not exist")
            if source.is_symlink():
                raise DocumentPathError("symbolic links cannot be deleted")
            if source.is_file():
                source.unlink()
                item_type = "file"
            elif source.is_dir():
                shutil.rmtree(source)
                item_type = "folder"
            else:
                raise DocumentValidationError("unsupported document type")
        return {"path": normalized, "item_type": item_type}

    def list_trash(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        with resource_lock(self.trash_root):
            for record, _, _ in reversed(self._trash_records()):
                metadata_path = record / "metadata.json"
                payload = record / "payload"
                if not metadata_path.is_file() or not payload.exists():
                    continue
                try:
                    with open(metadata_path, encoding="utf-8") as stream:
                        value = json.load(stream)
                    if isinstance(value, dict):
                        records.append(value)
                except (OSError, ValueError):
                    continue
        return records

    def restore(self, trash_id: str) -> dict[str, Any]:
        try:
            clean_id = validate_storage_id(trash_id, "trash_id")
            record, _ = resolve_under_root(
                self.trash_root, clean_id, allow_root=False, must_exist=True
            )
        except (PathValidationError, FileNotFoundError) as exc:
            raise DocumentNotFound("回收站项目不存在") from exc

        with resource_lock(self.root), resource_lock(self.trash_root):
            metadata_path = record / "metadata.json"
            payload = record / "payload"
            try:
                with open(metadata_path, encoding="utf-8") as stream:
                    metadata = json.load(stream)
                original = metadata["original_path"]
                if not isinstance(original, str):
                    raise ValueError("invalid original path")
                destination, normalized = self._resolve(original, allow_root=False)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                raise DocumentValidationError("回收站元数据损坏") from exc

            if not payload.exists():
                raise DocumentNotFound("回收站项目不存在")
            if destination.exists():
                raise DocumentAlreadyExists("原位置已有同名项目")
            self._ensure_library_capacity(self._path_size(payload))
            try:
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(os.fspath(payload), os.fspath(destination))
            except PermissionError as exc:
                raise DocumentPermissionDenied("权限不足，无法恢复项目") from exc

            # Moving the payload into the library is the restore commit point.
            # A later metadata cleanup error must not turn a successful restore
            # into a false failure that encourages a conflicting retry.
            try:
                metadata_path.unlink(missing_ok=True)
                record.rmdir()
            except OSError:
                LOGGER.warning(
                    "trash metadata cleanup failed after restore commit",
                    extra={"trash_id": clean_id, "path": normalized},
                    exc_info=True,
                )

        return {
            "id": clean_id,
            "path": normalized,
            "item_type": metadata.get("item_type", "file"),
        }

    def folders(self) -> list[dict[str, Any]]:
        folders: list[dict[str, Any]] = [{"path": "", "name": "📁 根目录", "level": 0}]
        with resource_lock(self.root):
            stack: list[tuple[Path, str]] = [(self.root, "")]
            while stack:
                directory, prefix = stack.pop()
                try:
                    with os.scandir(directory) as scan:
                        entries = sorted(
                            (
                                entry
                                for entry in scan
                                if not entry.name.startswith(".")
                                and entry.is_dir(follow_symlinks=False)
                                and not entry.is_symlink()
                            ),
                            key=lambda entry: entry.name.casefold(),
                            reverse=True,
                        )
                except (OSError, PermissionError):
                    continue
                for entry in entries:
                    relative = f"{prefix}/{entry.name}" if prefix else entry.name
                    folders.append(
                        {
                            "path": relative,
                            "name": entry.name,
                            "level": len(relative.split("/")),
                        }
                    )
                    stack.append((Path(entry.path), relative))

        root = folders[0]
        remainder = sorted(folders[1:], key=lambda item: item["path"].casefold())
        return [root, *remainder]

    def check_updates(self, directory_path: str = "", file_path: str = "") -> dict[str, Any]:
        directory, _ = self._resolve(directory_path, allow_root=True)
        file_candidate: Path | None = None
        if file_path:
            file_candidate, _ = self._resolve(file_path, allow_root=False)

        dir_mtime = 0.0
        file_mtime = 0.0
        version: str | None = None
        with resource_lock(self.root):
            if directory.is_dir():
                try:
                    dir_mtime = directory.stat().st_mtime
                    with os.scandir(directory) as entries:
                        for entry in entries:
                            if entry.is_symlink():
                                continue
                            try:
                                dir_mtime = max(
                                    dir_mtime, entry.stat(follow_symlinks=False).st_mtime
                                )
                            except OSError:
                                continue
                except OSError:
                    pass
            if file_candidate is not None and file_candidate.is_file():
                self._require_document(file_candidate, relative_to_root(self.root, file_candidate))
                try:
                    file_mtime = file_candidate.stat().st_mtime
                    version = file_version(file_candidate)
                except OSError:
                    pass

        result: dict[str, Any] = {"dir_mtime": dir_mtime, "file_mtime": file_mtime}
        if version is not None:
            result["version"] = version
        return result
