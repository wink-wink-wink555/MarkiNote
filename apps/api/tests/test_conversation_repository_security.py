from __future__ import annotations

from pathlib import Path

import pytest

from markinote_api.modules.conversations import repository as repository_module
from markinote_api.modules.conversations.repository import JsonConversationRepository
from markinote_api.platform.paths import PathValidationError


@pytest.mark.parametrize(
    "conversation_id",
    (
        "..",
        "../escape",
        "nested/escape",
        r"nested\escape",
        "/absolute/escape",
        r"C:\absolute\escape",
    ),
)
def test_repository_rejects_ids_that_could_escape_its_root(
    tmp_path: Path,
    conversation_id: str,
) -> None:
    repository = JsonConversationRepository(tmp_path / "conversations")
    outside_sentinel = tmp_path / "escape.json"
    outside_sentinel.write_text("sentinel", encoding="utf-8")

    with pytest.raises(PathValidationError):
        repository.get(conversation_id)
    with pytest.raises(PathValidationError):
        repository.delete(conversation_id)
    with pytest.raises(PathValidationError):
        repository.save({"id": conversation_id, "messages": []})

    assert outside_sentinel.read_text(encoding="utf-8") == "sentinel"
    assert list(repository.root.iterdir()) == []


def test_repository_rechecks_resolved_path_containment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = JsonConversationRepository(tmp_path / "conversations")
    outside_path = tmp_path / "outside.json"

    def return_outside_path(*_args, **_kwargs):
        return outside_path, "safe.json"

    monkeypatch.setattr(repository_module, "resolve_under_root", return_outside_path)

    with pytest.raises(PathValidationError):
        repository.get("safe")
