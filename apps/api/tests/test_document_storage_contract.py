from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from markinote_api.modules.documents import storage as storage_module
from markinote_api.modules.documents.errors import (
    DocumentAlreadyExists,
    DocumentCapacityExceeded,
    DocumentNotFound,
    DocumentValidationError,
)
from markinote_api.modules.documents.service import DocumentService
from markinote_api.modules.documents.storage import LocalDocumentStorage


def build_storage(
    tmp_path: Path,
    *,
    max_document_bytes: int = 1024,
    max_library_bytes: int = 16 * 1024,
    trash_max_items: int = 10,
    trash_max_bytes: int = 16 * 1024,
) -> LocalDocumentStorage:
    return LocalDocumentStorage(
        tmp_path / "library",
        tmp_path / "trash",
        allowed_extensions={"md", "markdown", "txt"},
        max_document_bytes=max_document_bytes,
        max_library_bytes=max_library_bytes,
        trash_max_items=trash_max_items,
        trash_max_bytes=trash_max_bytes,
    )


def test_storage_crud_listing_upload_and_update_contract(tmp_path: Path) -> None:
    storage = build_storage(tmp_path)
    service = DocumentService(storage)

    service.create_folder("", "Notes")
    service.create_folder("Notes", "Nested")
    service.create_file("", "root.md", "root")
    service.create_file("Notes", "note.txt", "alpha")
    (storage.root / ".hidden.md").write_text("hidden", encoding="utf-8")
    (storage.root / "unsupported.bin").write_bytes(b"binary")

    listing = service.list()
    assert listing["current_path"] == ""
    assert [(item["type"], item["name"]) for item in listing["items"]] == [
        ("folder", "Notes"),
        ("file", "root.md"),
    ]

    read = service.read("Notes/note.txt")
    assert read["content"] == "alpha"
    assert read["filename"] == "note.txt"
    assert read["size"] == 5
    assert read["version"]

    uploaded = service.upload("Uploads/Folder", "same.md", b"first")
    duplicate = service.upload("Uploads/Folder", "same.md", b"second")
    assert uploaded["path"] == "Uploads/Folder/same.md"
    assert duplicate["path"] != uploaded["path"]
    assert service.read(duplicate["path"])["content"] == "second"

    service.create_folder("", "Target")
    service.create_file("Target", "root.md", "collision")
    moved = service.move("root.md", "Target")
    assert moved["new_path"].startswith("Target/root_")
    renamed = service.rename(moved["new_path"], "renamed.md")
    assert renamed["new_path"] == "Target/renamed.md"

    relocated = service.relocate("Notes/note.txt", "Notes/Nested/moved.txt")
    assert relocated["new_path"] == "Notes/Nested/moved.txt"
    assert service.read("Notes/Nested/moved.txt")["content"] == "alpha"

    folders = service.folders()["folders"]
    assert folders[0]["path"] == ""
    assert {(item["path"], item["level"]) for item in folders[1:]} >= {
        ("Notes", 1),
        ("Notes/Nested", 2),
        ("Target", 1),
        ("Uploads/Folder", 2),
    }

    updates = service.check_updates("Notes/Nested", "Notes/Nested/moved.txt")
    assert updates["dir_mtime"] > 0
    assert updates["file_mtime"] > 0
    assert updates["version"] == service.read("Notes/Nested/moved.txt")["version"]


def test_search_covers_the_full_library_with_bounded_ranked_results(tmp_path: Path) -> None:
    storage = build_storage(tmp_path)
    service = DocumentService(storage)
    service.create_folder("", "项目")
    service.create_folder("", "归档")
    service.create_file("项目", "初步架构设计.md", "current")
    service.create_file("归档", "架构复盘.txt", "archived")
    service.create_file("", "unrelated.md", "other")
    (storage.root / ".架构草稿.md").write_text("hidden", encoding="utf-8")
    (storage.root / "架构数据.bin").write_bytes(b"unsupported")

    result = service.search("架构", limit=10)

    assert result["query"] == "架构"
    assert result["total"] == 2
    assert result["truncated"] is False
    assert {item["path"] for item in result["items"]} == {
        "项目/初步架构设计.md",
        "归档/架构复盘.txt",
    }

    limited = service.search("架构", limit=1)
    assert limited["total"] == 2
    assert limited["truncated"] is True
    assert len(limited["items"]) == 1

    path_match = service.search("项目", limit=10)
    assert {item["path"] for item in path_match["items"]} == {
        "项目",
        "项目/初步架构设计.md",
    }

    with pytest.raises(DocumentValidationError):
        service.search("   ")


def test_storage_rejects_invalid_content_and_parent_shapes(tmp_path: Path) -> None:
    storage = build_storage(tmp_path, max_document_bytes=5)
    service = DocumentService(storage)
    service.create_file("", "note.md", "12345")
    (storage.root / "invalid.md").write_bytes(b"\xff")
    (storage.root / "folder").mkdir()

    with pytest.raises(DocumentValidationError):
        service.read("invalid.md")
    with pytest.raises(DocumentValidationError):
        service.read("folder")
    with pytest.raises(DocumentCapacityExceeded):
        service.save("note.md", "123456")
    with pytest.raises(DocumentCapacityExceeded):
        service.create_file("", "large.md", "123456")
    with pytest.raises(DocumentCapacityExceeded):
        service.upload("", "large.md", b"123456")

    with pytest.raises(DocumentNotFound):
        service.create_folder("missing", "child")
    with pytest.raises(DocumentValidationError):
        service.create_folder("note.md", "child")
    with pytest.raises(DocumentAlreadyExists):
        service.create_folder("", "folder")

    with pytest.raises(DocumentNotFound):
        service.create_file("missing", "child.md", "")
    with pytest.raises(DocumentValidationError):
        service.create_file("note.md", "child.md", "")
    with pytest.raises(DocumentAlreadyExists):
        service.create_file("", "note.md", "")
    with pytest.raises(DocumentValidationError):
        service.create_file("", "script.exe", "")
    with pytest.raises(DocumentValidationError):
        service.create_file("", "bad/name.md", "")


def test_move_rename_and_relocate_fail_without_partial_mutation(tmp_path: Path) -> None:
    storage = build_storage(tmp_path)
    service = DocumentService(storage)
    service.create_folder("", "tree")
    service.create_folder("tree", "child")
    service.create_file("", "source.md", "source")
    service.create_file("", "taken.md", "taken")

    with pytest.raises(DocumentNotFound):
        service.move("missing.md", "")
    with pytest.raises(DocumentValidationError):
        service.move("source.md", "")
    with pytest.raises(DocumentValidationError):
        service.move("tree", "tree/child")
    with pytest.raises(FileExistsError):
        service.move("source.md", "taken.md")

    with pytest.raises(DocumentNotFound):
        service.rename("missing.md", "renamed.md")
    with pytest.raises(DocumentAlreadyExists):
        service.rename("source.md", "taken.md")
    with pytest.raises(DocumentValidationError):
        service.rename("source.md", "renamed.exe")

    with pytest.raises(DocumentNotFound):
        service.relocate("missing.md", "new.md")
    with pytest.raises(DocumentAlreadyExists):
        service.relocate("source.md", "taken.md")
    with pytest.raises(DocumentNotFound):
        service.relocate("source.md", "missing/new.md")
    with pytest.raises(DocumentValidationError):
        service.relocate("tree", "tree/child/deeper")
    with pytest.raises(DocumentValidationError):
        service.relocate("source.md", "renamed.exe")

    assert service.read("source.md")["content"] == "source"
    assert service.read("taken.md")["content"] == "taken"
    assert not any(path.name.startswith("source_") for path in storage.root.iterdir())
    assert (storage.root / "tree" / "child").is_dir()


def test_trash_capacity_pruning_and_corrupt_records_are_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        storage_module,
        "_utc_now",
        lambda: datetime(2026, 8, 9, 12, 0, tzinfo=UTC),
    )
    storage = build_storage(tmp_path, trash_max_items=1, trash_max_bytes=5)
    service = DocumentService(storage)

    service.create_file("", "first.md", "1")
    first = service.delete("first.md")
    service.create_file("", "second.md", "22")
    second = service.delete("second.md")
    assert [item["id"] for item in service.list_trash()["items"]] == [second["id"]]
    assert not (storage.trash_root / first["id"]).exists()

    service.create_file("", "large.md", "12345")
    with pytest.raises(DocumentCapacityExceeded):
        storage._validate_trash_item_capacity(6)
    deleted = service.delete("large.md")

    corrupt = storage.trash_root / "corrupt"
    corrupt.mkdir()
    (corrupt / "payload").write_text("payload", encoding="utf-8")
    (corrupt / "metadata.json").write_text("{invalid", encoding="utf-8")
    assert all(item["id"] != "corrupt" for item in service.list_trash()["items"])

    with pytest.raises(DocumentNotFound):
        service.restore("not-present")

    record = storage.trash_root / deleted["id"]
    metadata = json.loads((record / "metadata.json").read_text(encoding="utf-8"))
    (record / "metadata.json").write_text(
        json.dumps({"id": deleted["id"], "original_path": 123}),
        encoding="utf-8",
    )
    with pytest.raises(DocumentValidationError):
        service.restore(deleted["id"])

    (record / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    (storage.root / "large.md").write_text("occupied", encoding="utf-8")
    with pytest.raises(DocumentAlreadyExists):
        service.restore(deleted["id"])


def test_storage_configuration_keeps_trash_outside_the_library(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="TRASH_FOLDER"):
        LocalDocumentStorage(
            tmp_path / "library",
            tmp_path / "library" / "trash",
            allowed_extensions={"md"},
            max_document_bytes=1,
            max_library_bytes=1,
            trash_max_items=1,
            trash_max_bytes=1,
        )
