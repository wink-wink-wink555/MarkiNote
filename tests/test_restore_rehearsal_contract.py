from __future__ import annotations

import ast
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
REHEARSALS = (
    ("infra/ci/local-volume-restore-rehearsal.py", "local_volume_restore_rehearsal_failed"),
    ("infra/ci/backup-restore-rehearsal.py", "postgres_restore_rehearsal_failed"),
)


def test_restore_rehearsals_do_not_reflect_failure_exceptions_to_ci() -> None:
    for relative_path, stable_code in REHEARSALS:
        source = (REPOSITORY_ROOT / relative_path).read_text(encoding="utf-8")
        tree = ast.parse(source)
        broad_handlers = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.ExceptHandler)
            and isinstance(node.type, ast.Name)
            and node.type.id == "Exception"
        ]

        assert broad_handlers, f"{relative_path} must clean up unexpected failures"
        assert stable_code in source
        assert "str(error)" not in source
        for handler in broad_handlers:
            assert not any(isinstance(node, ast.Raise) for node in ast.walk(handler))
            assert any(
                isinstance(node, ast.Return)
                and isinstance(node.value, ast.Constant)
                and node.value.value == 1
                for node in ast.walk(handler)
            )


def test_local_restore_compares_conversation_api_counts_at_the_same_boundary() -> None:
    source = (
        REPOSITORY_ROOT / "infra/ci/local-volume-restore-rehearsal.py"
    ).read_text(encoding="utf-8")

    assert "source_display_message_count = len(source_messages)" in source
    assert "len(messages) != source_display_message_count" in source
    assert "len(messages) != expected_raw_message_count" not in source
    assert '"displayMessageCount": source_display_message_count' in source
