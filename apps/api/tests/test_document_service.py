from __future__ import annotations

import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

from markinote_api.modules.documents.errors import (
    DocumentAlreadyExists,
    DocumentCapacityExceeded,
    DocumentConflict,
    DocumentPathError,
)
from markinote_api.modules.documents.service import DocumentService
from markinote_api.modules.documents.storage import LocalDocumentStorage


class DocumentServiceTestCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.service = self._build_service()

    def _build_service(self, *, max_library_bytes: int = 16 * 1024 * 1024) -> DocumentService:
        storage = LocalDocumentStorage(
            self.root / "library",
            self.root / "trash",
            allowed_extensions={"md", "markdown", "txt"},
            max_document_bytes=2 * 1024 * 1024,
            max_library_bytes=max_library_bytes,
            trash_max_items=20,
            trash_max_bytes=16 * 1024 * 1024,
        )
        return DocumentService(storage)

    def tearDown(self):
        self.temp.cleanup()

    def test_optimistic_save_conflict_preserves_the_newer_content(self):
        self.service.create_file("", "note.md", "v1")
        original = self.service.read("note.md")
        first = self.service.save(
            "note.md", "v2", expected_version=original["version"]
        )
        self.assertNotEqual(first["version"], original["version"])

        with self.assertRaises(DocumentConflict):
            self.service.save(
                "note.md", "lost update", expected_version=original["version"]
            )
        self.assertEqual(self.service.read("note.md")["content"], "v2")

    def test_concurrent_saves_are_atomic_and_never_mix_buffers(self):
        self.service.create_file("", "note.md", "seed")
        barrier = threading.Barrier(8)
        buffers = [f"writer-{index}:" + chr(65 + index) * 200_000 for index in range(8)]

        def save(buffer: str) -> None:
            barrier.wait()
            self.service.save("note.md", buffer)

        with ThreadPoolExecutor(max_workers=8) as executor:
            list(executor.map(save, buffers))

        persisted = self.service.read("note.md")["content"]
        self.assertIn(persisted, buffers)

    def test_concurrent_create_has_exactly_one_winner(self):
        barrier = threading.Barrier(6)

        def create(index: int) -> str:
            barrier.wait()
            try:
                self.service.create_file("", "single.md", f"winner-{index}")
                return "created"
            except DocumentAlreadyExists:
                return "exists"

        with ThreadPoolExecutor(max_workers=6) as executor:
            results = list(executor.map(create, range(6)))
        self.assertEqual(results.count("created"), 1)
        self.assertEqual(results.count("exists"), 5)

    def test_every_service_path_entry_uses_the_canonical_policy(self):
        self.service.create_file("", "note.md", "text")
        attacks = ["../outside.md", "/etc/passwd", "C:\\Windows\\win.ini"]
        operations = (
            lambda path: self.service.list(path),
            lambda path: self.service.read(path),
            lambda path: self.service.save(path, "changed"),
            lambda path: self.service.create_folder(path, "folder"),
            lambda path: self.service.create_file(path, "new.md"),
            lambda path: self.service.upload(path, "upload.md", b"text"),
            lambda path: self.service.move(path, ""),
            lambda path: self.service.move("note.md", path),
            lambda path: self.service.rename(path, "renamed.md"),
            lambda path: self.service.delete(path),
            lambda path: self.service.check_updates(path, ""),
            lambda path: self.service.check_updates("", path),
        )
        for attack in attacks:
            for operation in operations:
                with self.subTest(path=attack, operation=operation), self.assertRaises(
                    DocumentPathError
                ):
                    operation(attack)

    def test_delete_is_recoverable_and_retains_metadata(self):
        self.service.create_folder("", "notes")
        self.service.create_file("notes", "recover.md", "recover me")
        deleted = self.service.delete("notes/recover.md")
        self.assertFalse((self.root / "library" / "notes" / "recover.md").exists())
        self.assertEqual(deleted["original_path"], "notes/recover.md")
        self.assertTrue(self.service.list_trash()["items"])

        restored = self.service.restore(deleted["id"])
        self.assertEqual(restored["path"], "notes/recover.md")
        self.assertEqual(self.service.read(restored["path"])["content"], "recover me")
        self.assertEqual(self.service.list_trash()["items"], [])

    def test_restore_respects_the_library_capacity_limit(self):
        service = self._build_service(max_library_bytes=8)
        service.create_file("", "first.md", "12345678")
        deleted = service.delete("first.md")
        service.create_file("", "second.md", "abcdefgh")

        with self.assertRaises(DocumentCapacityExceeded):
            service.restore(deleted["id"])

        self.assertEqual(service.read("second.md")["content"], "abcdefgh")
        self.assertEqual(len(service.list_trash()["items"]), 1)

    def test_restore_reports_committed_when_only_trash_metadata_cleanup_fails(self):
        self.service.create_file("", "committed.md", "durable content")
        deleted = self.service.delete("committed.md")
        metadata_path = (self.root / "trash" / deleted["id"] / "metadata.json").resolve()
        original_unlink = Path.unlink

        def fail_metadata_cleanup(path: Path, *args, **kwargs):
            if path.resolve() == metadata_path:
                raise PermissionError("simulated post-commit cleanup failure")
            return original_unlink(path, *args, **kwargs)

        with mock.patch.object(Path, "unlink", autospec=True, side_effect=fail_metadata_cleanup):
            restored = self.service.restore(deleted["id"])

        self.assertEqual(restored["path"], "committed.md")
        self.assertEqual(self.service.read("committed.md")["content"], "durable content")
        self.assertEqual(self.service.list_trash()["items"], [])
        self.assertTrue(metadata_path.is_file())

    def test_failed_delete_does_not_prune_existing_trash(self):
        self.service.create_file("", "old.md", "old")
        old = self.service.delete("old.md")
        self.service.create_file("", "new.md", "new")

        with (
            mock.patch(
                "markinote_api.modules.documents.storage.atomic_write_json",
                side_effect=OSError("metadata write failed"),
            ),
            self.assertRaises(OSError),
        ):
            self.service.delete("new.md")

        self.assertEqual(self.service.read("new.md")["content"], "new")
        self.assertEqual(
            [item["id"] for item in self.service.list_trash()["items"]],
            [old["id"]],
        )

if __name__ == "__main__":
    unittest.main()
