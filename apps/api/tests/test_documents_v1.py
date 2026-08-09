from __future__ import annotations

from prometheus_client import REGISTRY

from .test_platform_api import build_client


def test_document_crud_and_version_conflict():
    client, temp = build_client()
    try:
        conflicts_before = float(
            REGISTRY.get_sample_value(
                "markinote_document_conflicts_total", {"adapter": "v1"}
            )
            or 0.0
        )
        created = client.post("/api/v1/documents/files", json={"path": "", "name": "note.md", "content": "v1"})
        assert created.status_code == 200

        read = client.get("/api/v1/documents/content", params={"path": "note.md"})
        assert read.status_code == 200
        version = read.json()["version"]
        assert read.headers["etag"] == f'"{version}"'

        saved = client.put(
            "/api/v1/documents/content",
            params={"path": "note.md"},
            headers={"If-Match": f'"{version}"'},
            json={"content": "v2"},
        )
        assert saved.status_code == 200
        assert saved.json()["version"] != version

        conflict = client.put(
            "/api/v1/documents/content",
            params={"path": "note.md"},
            headers={"If-Match": f'"{version}"'},
            json={"content": "lost update"},
        )
        assert conflict.status_code == 409
        assert conflict.json()["code"] == "document_version_conflict"
        assert REGISTRY.get_sample_value(
            "markinote_document_conflicts_total", {"adapter": "v1"}
        ) == conflicts_before + 1

        deleted = client.delete("/api/v1/documents", params={"path": "note.md"})
        assert deleted.status_code == 200
        trash = client.get("/api/v1/documents/trash")
        assert trash.status_code == 200
        assert trash.json()["items"]
    finally:
        client.close()
        temp.cleanup()


def test_document_path_traversal_is_rejected():
    client, temp = build_client()
    try:
        response = client.get("/api/v1/documents/content", params={"path": "../outside.md"})
        assert response.status_code == 403
        assert response.json()["code"] == "invalid_path"
    finally:
        client.close()
        temp.cleanup()


def test_upload_stops_reading_at_document_limit():
    client, temp = build_client(settings_overrides={"max_document_bytes": 4})
    try:
        response = client.post(
            "/api/v1/documents/upload",
            data={"path": ""},
            files={"file": ("large.md", b"12345", "text/markdown")},
        )
        assert response.status_code == 413
        assert response.json()["code"] == "document_capacity_exceeded"
        assert not (client.app.state.settings.library_folder / "large.md").exists()
    finally:
        client.close()
        temp.cleanup()


def test_document_search_returns_nested_files_and_bounded_metadata():
    client, temp = build_client()
    try:
        assert client.post("/api/v1/documents/folders", json={"path": "", "name": "Nested"}).status_code == 200
        assert client.post(
            "/api/v1/documents/files",
            json={"path": "Nested", "name": "Architecture.md", "content": "search target"},
        ).status_code == 200

        response = client.get("/api/v1/documents/search", params={"q": "architecture", "limit": 20})

        assert response.status_code == 200
        assert response.json() == {
            "items": [
                {
                    "name": "Architecture.md",
                    "type": "file",
                    "path": "Nested/Architecture.md",
                    "size": 13,
                    "modified": response.json()["items"][0]["modified"],
                }
            ],
            "query": "architecture",
            "total": 1,
            "truncated": False,
        }
        assert client.get("/api/v1/documents/search", params={"q": "x", "limit": 201}).status_code == 422
        assert client.get("/api/v1/documents/search", params={"q": "   "}).status_code == 400
    finally:
        client.close()
        temp.cleanup()
