from __future__ import annotations

from unittest import mock

import pytest
from prometheus_client import REGISTRY

from .test_platform_api import build_client


def test_audited_operation_rollback_restores_snapshot():
    client, temp = build_client()
    try:
        success_before = float(
            REGISTRY.get_sample_value(
                "markinote_operation_rollback_attempts_total",
                {"source": "v1_api", "outcome": "success"},
            )
            or 0.0
        )
        library = client.app.state.settings.library_folder
        document = library / "rollback.md"
        document.write_text("before", encoding="utf-8")
        manager = client.app.state.backup_manager
        group = manager.create_operation_group("conversation-id")
        operation = manager.backup_before_modify(group, "modify_file", "rollback.md")
        document.write_text("after", encoding="utf-8")
        manager.backup_after_modify(group, operation, "rollback.md")
        manager.complete_operation_group(group)

        response = client.post(
            "/api/v1/operations/rollback",
            json={"backupGroupId": group, "operationIndex": operation},
        )
        assert response.status_code == 200
        assert document.read_text(encoding="utf-8") == "before"
        assert REGISTRY.get_sample_value(
            "markinote_operation_rollback_attempts_total",
            {"source": "v1_api", "outcome": "success"},
        ) == success_before + 1
        audit = client.app.state.command_journal.audit_file.read_text(encoding="utf-8")
        assert '"action": "rollback"' in audit
    finally:
        client.close()
        temp.cleanup()


def test_failed_operation_rollback_is_counted_without_high_cardinality_labels():
    client, temp = build_client()
    try:
        manager = client.app.state.backup_manager
        group = manager.create_operation_group("conversation-id")
        failure_before = float(
            REGISTRY.get_sample_value(
                "markinote_operation_rollback_attempts_total",
                {"source": "v1_api", "outcome": "failure"},
            )
            or 0.0
        )

        with mock.patch.object(
            manager, "rollback_operation", return_value=(False, "injected failure")
        ):
            response = client.post(
                "/api/v1/operations/rollback",
                json={"backupGroupId": group, "operationIndex": 0},
            )

        assert response.status_code == 409
        assert REGISTRY.get_sample_value(
            "markinote_operation_rollback_attempts_total",
            {"source": "v1_api", "outcome": "failure"},
        ) == failure_before + 1
    finally:
        client.close()
        temp.cleanup()


def test_rollback_cannot_race_an_active_conversation():
    client, temp = build_client()
    try:
        conversation_id = "conversation-id"
        manager = client.app.state.backup_manager
        group = manager.create_operation_group(conversation_id)
        document = client.app.state.settings.library_folder / "rollback.md"
        document.write_text("before", encoding="utf-8")
        operation = manager.backup_before_modify(group, "modify_file", "rollback.md")
        document.write_text("after", encoding="utf-8")
        manager.backup_after_modify(group, operation, "rollback.md")
        manager.complete_operation_group(group)

        with client.app.state.agent_service.exclusive_conversation(conversation_id):
            response = client.post(
                "/api/v1/operations/rollback",
                json={"backupGroupId": group, "operationIndex": operation},
            )
        assert response.status_code == 409
        assert response.json()["code"] == "conversation_busy"
        assert document.read_text(encoding="utf-8") == "after"
    finally:
        client.close()
        temp.cleanup()


@pytest.mark.parametrize("recovered_state", ["abandoned", "quarantined"])
def test_backup_list_contract_includes_recovered_orphan_states(recovered_state: str):
    client, temp = build_client()
    try:
        manager = client.app.state.backup_manager
        group = manager.create_operation_group("orphaned-conversation")
        group_dir = manager._group_dir(group)
        manifest = manager._load_manifest(group_dir)
        manifest["state"] = recovered_state
        manifest["owner_id"] = None
        manifest["lease_until"] = None
        manifest["completed_at"] = "2026-07-18T00:00:00+00:00"
        manager._save_manifest(group_dir, manifest)

        response = client.get("/api/v1/operations/backups")

        assert response.status_code == 200
        item = next(value for value in response.json()["items"] if value["id"] == group)
        assert item["state"] == recovered_state
    finally:
        client.close()
        temp.cleanup()
