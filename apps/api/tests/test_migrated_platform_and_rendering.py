from __future__ import annotations

import hashlib
import os
import unicodedata
from pathlib import Path
from unittest import mock

import pytest

from markinote_api.modules.rendering.service import (
    _allow_attribute,
    _prefix_document_ids,
    _render_cached,
    _replace_wrapped_placeholder,
    process_markdown,
)
from markinote_api.platform.files import allowed_file, safe_filename
from markinote_api.platform.io import (
    atomic_write_bytes,
    atomic_write_json,
    atomic_write_text,
    content_version,
    file_version,
    read_utf8_text,
    resource_lock,
)
from markinote_api.platform.paths import (
    PathValidationError,
    normalize_relative_path,
    relative_to_root,
    resolve_under_root,
    validate_storage_id,
)


@pytest.mark.parametrize(
    ("tag", "name", "value", "expected"),
    (
        ("p", "onclick", "alert(1)", False),
        ("h1", "id", "md-heading_1", True),
        ("h1", "id", "heading", False),
        ("div", "class", "toc footnote", True),
        ("code", "class", "language-python", True),
        ("code", "class", "language-python<script>", False),
        ("span", "class", "k n123", True),
        ("div", "class", "unknown", False),
        ("img", "width", "640", True),
        ("img", "height", "0", False),
        ("img", "height", "10001", False),
        ("a", "target", "_blank", True),
        ("a", "target", "_parent", False),
        ("img", "loading", "lazy", True),
        ("img", "loading", "auto", False),
        ("a", "href", "https://example.test", True),
    ),
)
def test_render_allowlist_handles_each_attribute_policy(
    tag: str,
    name: str,
    value: str,
    expected: bool,
) -> None:
    assert _allow_attribute(tag, name, value) is expected


def test_render_helpers_replace_placeholders_and_make_ids_dom_safe() -> None:
    assert _replace_wrapped_placeholder("<p>TOKEN</p>", "TOKEN", "<del>x</del>") == "<del>x</del>"
    assert _replace_wrapped_placeholder("<div>TOKEN</div>", "TOKEN", "<b>x</b>") == "<div><b>x</b></div>"

    rendered = _prefix_document_ids(
        '<h1 id="same">One</h1><h2 id="same">Two</h2>'
        '<div id="!!!">empty</div><a href="#same" target="_blank">jump</a>'
    )
    assert 'id="md-same"' in rendered
    assert 'id="md-same-2"' in rendered
    assert 'id="!!!"' not in rendered
    assert 'href="#md-same"' in rendered
    assert 'rel="noopener noreferrer"' in rendered


def test_markdown_rendering_preserves_supported_syntax_and_sanitizes_html() -> None:
    markdown_source = r"""
# Heading

*emphasized* and ~~removed~~ and `~~literal~~` and $x + y$ and \(z\).

$$
a^2
$$

\[
b^2
\]

```mermaid
graph TD
  A --> B
```

```python
print("<safe>")
```

<script>alert(1)</script>
<img src="javascript:alert(1)" onerror="alert(2)" width="32" loading="lazy">
<a href="#heading" target="_blank">jump</a>
"""
    rendered = process_markdown(markdown_source)

    assert "<em>emphasized</em>" in rendered
    assert "<del>removed</del>" in rendered
    assert "~~literal~~" in rendered
    assert rendered.count('class="math-inline"') == 2
    assert rendered.count('class="math-block"') == 2
    assert 'class="language-mermaid"' in rendered
    assert "graph TD" in rendered
    assert 'class="highlight"' in rendered
    assert 'class="nb"' in rendered
    assert '"&lt;safe&gt;"' in rendered
    assert "script" not in rendered
    assert "javascript:" not in rendered
    assert "onerror" not in rendered
    assert 'width="32"' in rendered
    assert 'loading="lazy"' in rendered
    assert 'href="#md-heading"' in rendered
    assert 'rel="noopener noreferrer"' in rendered


@pytest.mark.parametrize(
    ("newline", "fence"),
    (
        ("\n", "```"),
        ("\r\n", "```"),
        ("\r", "```"),
        ("\r\n", "~~~~"),
    ),
)
def test_mermaid_fences_render_consistently_across_line_endings_and_fence_styles(
    newline: str,
    fence: str,
) -> None:
    source = newline.join(
        (
            "# Diagram",
            "",
            f"{fence}mermaid",
            "graph TD",
            "  A[开始] --> B[完成]",
            fence,
            "",
        )
    )

    rendered = process_markdown(source)

    assert rendered.count('class="language-mermaid"') == 1
    assert "graph TD" in rendered
    assert "开始" in rendered
    assert 'class="highlight"' not in rendered


def test_long_non_mermaid_fence_is_restored_without_shortening_its_delimiter() -> None:
    fence = "`" * 4
    source = "\n".join(
        (
            f"{fence}text",
            "```",
            "content inside the longer fence",
            "```",
            fence,
        )
    )

    rendered = process_markdown(source)

    assert rendered.count("<pre>") == 1
    assert "content inside the longer fence" in rendered


def test_markdown_rendering_is_cached_and_rejects_non_text() -> None:
    _render_cached.cache_clear()
    first = process_markdown("plain")
    second = process_markdown("plain")
    assert first == second
    assert _render_cached.cache_info().hits == 1
    with pytest.raises(TypeError):
        process_markdown(b"plain")


@pytest.mark.parametrize(
    ("filename", "extensions", "expected"),
    (
        ("note.md", {"md"}, True),
        ("NOTE.MD", {"md"}, True),
        ("note", {"md"}, False),
        ("note.txt", {"md"}, False),
    ),
)
def test_allowed_file_is_case_insensitive(
    filename: str,
    extensions: set[str],
    expected: bool,
) -> None:
    assert allowed_file(filename, extensions) is expected


def test_safe_filename_preserves_unicode_and_normalizes_to_nfc() -> None:
    decomposed = "Cafe\u0301.md"
    assert safe_filename(decomposed) == unicodedata.normalize("NFC", decomposed)
    assert safe_filename("archive.tar.md") == "archive.tar.md"


@pytest.mark.parametrize(
    "filename",
    (
        None,
        "",
        ".",
        "..",
        " leading.md",
        "trailing.md ",
        "trailing.",
        "bad/name.md",
        "bad\x00name.md",
        "CON.md",
        f"{'x' * 233}.md",
        f"note.{'x' * 33}",
    ),
)
def test_safe_filename_rejects_nonportable_names(filename: object) -> None:
    with pytest.raises(ValueError):
        safe_filename(filename)


def test_normalize_relative_path_accepts_canonical_paths_only() -> None:
    assert normalize_relative_path("") == ""
    assert normalize_relative_path(r"notes\.\today.md") == "notes/today.md"
    assert normalize_relative_path("notes//today.md") == "notes/today.md"
    assert normalize_relative_path(".") == ""

    invalid_values: tuple[object, ...] = (
        None,
        "bad\x00path",
        "x" * 1025,
        "/absolute",
        r"C:\absolute",
        "../escape",
        "notes/../../escape",
    )
    for value in invalid_values:
        with pytest.raises(PathValidationError):
            normalize_relative_path(value)

    with pytest.raises(PathValidationError):
        normalize_relative_path("", allow_empty=False)
    with pytest.raises(PathValidationError):
        normalize_relative_path(".", allow_empty=False)


def test_resolve_and_relative_paths_enforce_the_library_boundary(tmp_path: Path) -> None:
    library = tmp_path / "library"
    note = library / "notes" / "today.md"
    note.parent.mkdir(parents=True)
    note.write_text("hello", encoding="utf-8")

    resolved, normalized = resolve_under_root(library, r"notes\today.md", must_exist=True)
    assert resolved == note
    assert normalized == "notes/today.md"
    assert relative_to_root(library, resolved) == "notes/today.md"
    assert resolve_under_root(library, "") == (library.resolve(), "")

    with pytest.raises(FileNotFoundError):
        resolve_under_root(library, "missing.md", must_exist=True)
    with pytest.raises(PathValidationError):
        resolve_under_root(library, "", allow_root=False)
    with pytest.raises(PathValidationError):
        relative_to_root(library, tmp_path / "outside.md")


def test_resolver_rejects_symlinks_and_cross_drive_candidates(tmp_path: Path) -> None:
    library = tmp_path / "library"
    library.mkdir()

    original_is_symlink = Path.is_symlink

    def fake_is_symlink(path: Path) -> bool:
        return path.name == "link" or original_is_symlink(path)

    with (
        mock.patch.object(Path, "is_symlink", fake_is_symlink),
        pytest.raises(PathValidationError),
    ):
        resolve_under_root(library, "link/note.md")

    with (
        mock.patch("markinote_api.platform.paths.os.path.commonpath", side_effect=ValueError),
        pytest.raises(PathValidationError),
    ):
        resolve_under_root(library, "note.md")


@pytest.mark.parametrize("value", ("a", "note_1", "UPPER-lower-123", "x" * 64))
def test_validate_storage_id_accepts_portable_identifiers(value: str) -> None:
    assert validate_storage_id(value) == value


@pytest.mark.parametrize("value", (None, "", "-starts-with-dash", "contains space", "x" * 65))
def test_validate_storage_id_rejects_unsafe_identifiers(value: object) -> None:
    with pytest.raises(PathValidationError):
        validate_storage_id(value, "trash ID")


def test_atomic_io_round_trip_hashing_and_locking(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "note.txt"
    atomic_write_bytes(target, b"first")
    original_mode = target.stat().st_mode
    atomic_write_text(target, "second")
    assert target.read_text(encoding="utf-8") == "second"
    assert target.stat().st_mode == original_mode

    payload_path = tmp_path / "state.json"
    atomic_write_json(payload_path, {"title": "笔记"})
    assert payload_path.read_bytes().endswith(b"\n")
    assert '"title":' in read_utf8_text(payload_path)

    bom_path = tmp_path / "bom.txt"
    bom_path.write_bytes(b"\xef\xbb\xbfcontent")
    assert read_utf8_text(bom_path) == "content"

    expected = hashlib.sha256(b"second").hexdigest()
    assert content_version("second") == expected
    assert content_version(b"second") == expected
    assert file_version(target) == expected

    with resource_lock(target), resource_lock(os.path.abspath(target)):
        atomic_write_text(target, "locked")
    assert target.read_text(encoding="utf-8") == "locked"


def test_atomic_io_rejects_non_text_and_removes_failed_temporary_file(tmp_path: Path) -> None:
    with pytest.raises(TypeError):
        atomic_write_text(tmp_path / "invalid.txt", b"bytes")

    target = tmp_path / "failed.txt"
    with (
        mock.patch("markinote_api.platform.io.os.replace", side_effect=OSError("replace failed")),
        pytest.raises(OSError, match="replace failed"),
    ):
        atomic_write_bytes(target, b"content")

    assert not target.exists()
    assert list(tmp_path.iterdir()) == []
