from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

from markinote_api.modules.agent import tools
from markinote_api.modules.documents.errors import DocumentNotFound
from markinote_api.modules.operations.backup import BackupManager


@pytest.fixture
def tool_context(tmp_path: Path) -> tuple[Path, BackupManager]:
    library = tmp_path / "library"
    library.mkdir()
    return library, BackupManager(tmp_path / "backups", library)


def test_execute_tool_rejects_invalid_dispatch_inputs(
    tool_context: tuple[Path, BackupManager],
) -> None:
    library, manager = tool_context

    for arguments in ('{"unterminated"', "[]", None):
        result, backup = tools.execute_tool("read_file", arguments, library, manager)
        assert result
        assert backup is None

    result, backup = tools.execute_tool("not_registered", {}, library, manager)
    assert result
    assert backup is None


@pytest.mark.parametrize(
    ("error", "expected_backup"),
    (
        (DocumentNotFound("missing"), None),
        (ValueError("safe validation"), None),
        (KeyError("missing"), None),
        (TypeError("wrong type"), None),
        (RuntimeError("private detail"), None),
    ),
)
def test_execute_tool_maps_internal_error_categories_to_safe_results(
    tool_context: tuple[Path, BackupManager],
    error: Exception,
    expected_backup: None,
) -> None:
    library, manager = tool_context
    with mock.patch.object(tools, "_read_file", side_effect=error):
        result, backup = tools.execute_tool("read_file", {}, library, manager)

    assert result
    assert backup is expected_backup
    if isinstance(error, RuntimeError):
        assert "private detail" not in result


def test_read_file_supports_ranges_and_validates_line_numbers(
    tool_context: tuple[Path, BackupManager],
) -> None:
    library, manager = tool_context
    (library / "note.md").write_text("one\ntwo\nthree\n", encoding="utf-8")

    result, backup = tools.execute_tool("read_file", {"path": "note.md"}, library, manager)
    assert backup is None
    assert all(value in result for value in ("one", "two", "three"))

    result, _ = tools.execute_tool(
        "read_file",
        {"path": "note.md", "start_line": 2, "end_line": 2},
        library,
        manager,
    )
    assert "two" in result
    assert "one" not in result
    assert "three" not in result

    for line_arguments in (
        {"start_line": True},
        {"start_line": 0},
        {"end_line": False},
        {"end_line": 0},
        {"start_line": 3, "end_line": 2},
    ):
        result, backup = tools.execute_tool(
            "read_file",
            {"path": "note.md", **line_arguments},
            library,
            manager,
        )
        assert result
        assert backup is None

    result, _ = tools.execute_tool("read_file", {"path": "missing.md"}, library, manager)
    assert "missing.md" in result


def test_read_file_truncates_oversized_content(
    tool_context: tuple[Path, BackupManager],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    library, manager = tool_context
    (library / "large.md").write_text("abcdef", encoding="utf-8")
    monkeypatch.setattr(tools, "MAX_TOOL_FILE_BYTES", 4)

    result, backup = tools.execute_tool("read_file", {"path": "large.md"}, library, manager)

    assert backup is None
    assert "abcd" in result
    assert "abcdef" not in result


def test_write_and_edit_tools_enforce_content_contracts(
    tool_context: tuple[Path, BackupManager],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    library, manager = tool_context
    note = library / "note.md"
    note.write_text("first first", encoding="utf-8")

    result, backup = tools.execute_tool(
        "write_file",
        {"path": "note.md", "content": "replaced"},
        library,
        manager,
    )
    assert result
    assert backup == {"type": "write_file", "path": "note.md", "operation_index": None}
    assert note.read_text(encoding="utf-8") == "replaced"

    result, backup = tools.execute_tool(
        "edit_file",
        {"path": "note.md", "old_text": "replaced", "new_text": "first first"},
        library,
        manager,
    )
    assert result
    assert backup == {"type": "edit_file", "path": "note.md", "operation_index": None}
    assert note.read_text(encoding="utf-8") == "first first"

    result, _ = tools.execute_tool(
        "edit_file",
        {"path": "note.md", "old_text": "first", "new_text": "changed"},
        library,
        manager,
    )
    assert result
    assert note.read_text(encoding="utf-8") == "changed first"

    invalid_calls = (
        ("write_file", {"path": "note.md", "content": b"bytes"}),
        ("write_file", {"path": "missing.md", "content": "text"}),
        ("edit_file", {"path": "note.md", "old_text": "", "new_text": "x"}),
        ("edit_file", {"path": "note.md", "old_text": "x", "new_text": b"bytes"}),
        ("edit_file", {"path": "missing.md", "old_text": "x", "new_text": "y"}),
        ("edit_file", {"path": "note.md", "old_text": "absent", "new_text": "y"}),
    )
    for name, arguments in invalid_calls:
        before = note.read_text(encoding="utf-8")
        result, backup = tools.execute_tool(name, arguments, library, manager)
        assert result
        assert backup is None
        assert note.read_text(encoding="utf-8") == before

    monkeypatch.setattr(tools, "MAX_TOOL_FILE_BYTES", 3)
    for name, arguments in (
        ("write_file", {"path": "note.md", "content": "1234"}),
        ("edit_file", {"path": "note.md", "old_text": "changed", "new_text": "123456"}),
    ):
        result, backup = tools.execute_tool(name, arguments, library, manager)
        assert result
        assert backup is None


def test_create_file_and_folder_cover_success_and_collision_paths(
    tool_context: tuple[Path, BackupManager],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    library, manager = tool_context

    result, backup = tools.execute_tool(
        "create_folder",
        {"path": "notes"},
        library,
        manager,
    )
    assert result
    assert backup == {"type": "create_folder", "path": "notes", "operation_index": None}
    assert (library / "notes").is_dir()

    result, backup = tools.execute_tool(
        "create_file",
        {"path": "notes/new.md", "content": "hello"},
        library,
        manager,
    )
    assert result
    assert backup == {"type": "create_file", "path": "notes/new.md", "operation_index": None}
    assert (library / "notes" / "new.md").read_text(encoding="utf-8") == "hello"

    invalid_calls = (
        ("create_folder", {"path": "notes"}),
        ("create_folder", {"path": "missing/child"}),
        ("create_folder", {}),
        ("create_file", {"path": "notes/new.md", "content": "duplicate"}),
        ("create_file", {"path": "missing/new.md", "content": "missing parent"}),
        ("create_file", {"path": "notes/type.md", "content": b"bytes"}),
    )
    for name, arguments in invalid_calls:
        result, backup = tools.execute_tool(name, arguments, library, manager)
        assert result
        assert backup is None

    monkeypatch.setattr(tools, "MAX_TOOL_FILE_BYTES", 3)
    result, backup = tools.execute_tool(
        "create_file",
        {"path": "notes/large.md", "content": "1234"},
        library,
        manager,
    )
    assert result
    assert backup is None
    assert not (library / "notes" / "large.md").exists()


def test_delete_requires_durable_recovery_and_handles_files_and_folders(
    tool_context: tuple[Path, BackupManager],
) -> None:
    library, manager = tool_context
    note = library / "note.md"
    note.write_text("recoverable", encoding="utf-8")

    result, backup = tools.execute_tool("delete_item", {"path": "note.md"}, library, manager)
    assert result == "Deletion refused because no durable backup group is available."
    assert backup is None
    assert note.exists()

    group_id = manager.create_operation_group("conversation")
    result, backup = tools.execute_tool(
        "delete_item",
        {"path": "missing.md"},
        library,
        manager,
        group_id,
    )
    assert result
    assert backup is None

    folder = library / "folder"
    folder.mkdir()
    (folder / "nested.md").write_text("text", encoding="utf-8")
    result, backup = tools.execute_tool(
        "delete_item",
        {"path": "folder"},
        library,
        manager,
        group_id,
    )
    assert result
    assert backup and backup["type"] == "delete_item"
    assert not folder.exists()


def test_move_tool_validates_destinations_and_moves_exactly_once(
    tool_context: tuple[Path, BackupManager],
) -> None:
    library, manager = tool_context
    (library / "source.md").write_text("text", encoding="utf-8")
    (library / "target").mkdir()
    (library / "taken.md").write_text("occupied", encoding="utf-8")
    (library / "tree").mkdir()

    invalid_arguments = (
        {"source": "source.md", "target": None},
        {"source": "missing.md", "target": "target"},
        {"source": "source.md", "target": "taken.md"},
        {"source": "source.md", "target": "missing/new.md"},
        {"source": "tree", "target": "tree/child"},
    )
    for arguments in invalid_arguments:
        result, backup = tools.execute_tool("move_item", arguments, library, manager)
        assert result
        assert backup is None

    result, backup = tools.execute_tool(
        "move_item",
        {"source": "source.md", "target": "target"},
        library,
        manager,
    )
    assert result
    assert backup and backup["target"] == "target/source.md"
    assert not (library / "source.md").exists()
    assert (library / "target" / "source.md").read_text(encoding="utf-8") == "text"

    result, backup = tools.execute_tool(
        "move_item",
        {"source": "target/source.md", "target": ""},
        library,
        manager,
    )
    assert result
    assert backup and backup["target"] == "source.md"
    assert (library / "source.md").exists()


def test_list_directory_filters_hidden_entries_and_handles_read_failures(
    tool_context: tuple[Path, BackupManager],
) -> None:
    library, manager = tool_context
    (library / "folder").mkdir()
    (library / "note.md").write_text("hello", encoding="utf-8")
    (library / ".hidden.md").write_text("secret", encoding="utf-8")

    result, backup = tools.execute_tool("list_directory", {}, library, manager)
    assert backup is None
    assert "folder" in result
    assert "note.md" in result
    assert ".hidden.md" not in result

    result, backup = tools.execute_tool(
        "list_directory",
        {"path": "missing"},
        library,
        manager,
    )
    assert result
    assert backup is None

    with mock.patch.object(tools.os, "scandir", side_effect=PermissionError("private")):
        result, backup = tools.execute_tool("list_directory", {}, library, manager)
    assert result
    assert "private" not in result
    assert backup is None


def test_search_files_limits_scope_and_reports_matching_lines(
    tool_context: tuple[Path, BackupManager],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    library, manager = tool_context
    notes = library / "notes"
    notes.mkdir()
    (notes / "first.md").write_text("alpha\nneedle here\nneedle again\n", encoding="utf-8")
    (notes / "ignored.bin").write_text("needle", encoding="utf-8")
    (notes / ".hidden.md").write_text("needle", encoding="utf-8")

    result, backup = tools.execute_tool(
        "search_files",
        {"query": "NEEDLE", "path": "notes"},
        library,
        manager,
    )
    assert backup is None
    assert "notes/first.md" in result
    assert "needle here" in result
    assert "ignored.bin" not in result
    assert ".hidden.md" not in result

    for arguments in (
        {"query": ""},
        {"query": "x" * 201},
        {"query": "needle", "path": "missing"},
        {"query": "absent", "path": "notes"},
    ):
        result, backup = tools.execute_tool("search_files", arguments, library, manager)
        assert result
        assert backup is None

    monkeypatch.setattr(tools, "MAX_TOOL_FILE_BYTES", 2)
    result, backup = tools.execute_tool(
        "search_files",
        {"query": "needle", "path": "notes"},
        library,
        manager,
    )
    assert result
    assert backup is None
    assert "first.md" not in result


def test_html_extraction_and_language_prompt_are_deterministic() -> None:
    rendered = tools._extract_text_from_html(
        "<html><head><title>Title</title><style>hidden</style></head>"
        "<body><nav>menu</nav><main><p>First</p><p>Second</p></main>"
        "<script>secret</script></body></html>"
    )
    assert "Title" in rendered
    assert "First" in rendered
    assert "Second" in rendered
    assert "hidden" not in rendered
    assert "secret" not in rendered
    assert tools.get_system_prompt("en") != tools.get_system_prompt("zh-CN")
    assert tools.get_system_prompt("unknown") == tools.get_system_prompt("zh-CN")


def test_web_search_uses_fallbacks_and_configured_proxy(
    tool_context: tuple[Path, BackupManager],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    library, manager = tool_context
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.example:8080")

    with (
        mock.patch.object(tools, "_web_search_bing", return_value=None) as bing,
        mock.patch.object(tools, "_web_search_ddg", return_value="fallback") as ddg,
    ):
        result, backup = tools.execute_tool(
            "web_search",
            {"query": "docs"},
            library,
            manager,
        )
    assert "外部不可信内容" in result
    assert result.endswith("fallback")
    assert backup is None
    bing.assert_called_once_with("docs", "http://proxy.example:8080")
    ddg.assert_called_once_with("docs", "http://proxy.example:8080")

    with (
        mock.patch.object(tools, "_web_search_bing", return_value="primary"),
        mock.patch.object(tools, "_web_search_ddg") as ddg,
    ):
        result, _ = tools.execute_tool("web_search", {"query": "docs"}, library, manager)
    assert "外部不可信内容" in result
    assert result.endswith("primary")
    ddg.assert_not_called()

    result, backup = tools.execute_tool("web_search", {"query": ""}, library, manager)
    assert result
    assert backup is None


def test_redaction_and_persistence_sanitizers_fail_closed() -> None:
    assert tools._redacted_public_url(None) == "[invalid URL]"
    assert tools._redacted_public_url("https://") == "[invalid URL]"
    assert tools._redacted_public_url("https://[invalid") == "[invalid URL]"
    assert tools._redacted_public_url("http://example.test:bad") == "[invalid URL]"
    assert tools._redacted_public_url("example.test/path") == "https://example.test/path"
    assert tools._redacted_public_url("https://[2001:db8::1]/") == "https://[2001:db8::1]/"

    assert tools.sanitize_tool_arguments_for_persistence("read_file", {"path": "note.md"}) == {
        "path": "note.md"
    }
    assert tools.sanitize_tool_arguments_for_persistence("fetch_url", "invalid") == {}
    assert tools.sanitize_tool_call_arguments_for_persistence("read_file", "{raw}") == "{raw}"
    assert tools.sanitize_tool_call_arguments_for_persistence("fetch_url", "{invalid") == (
        '{"url":"[invalid URL]"}'
    )
