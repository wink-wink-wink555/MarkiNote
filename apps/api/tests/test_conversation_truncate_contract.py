from __future__ import annotations

from unittest import mock

from .test_platform_api import build_client


def test_truncate_failure_is_a_conflict_and_never_claims_success() -> None:
    client, temporary = build_client()
    try:
        conversation = client.app.state.conversation_service.create("title", "system")
        with mock.patch.object(
            client.app.state.conversation_service,
            "truncate",
            return_value={
                "committed": False,
                "message": "not committed",
                "rollback_results": [
                    {
                        "group_id": "group",
                        "success": False,
                        "message": "rollback refused: a document changed after the AI operation",
                    }
                ],
            },
        ):
            response = client.post(
                f"/api/v1/conversations/{conversation['id']}/truncate",
                json={"user_message_number": 0, "include_user_message": True},
            )

        assert response.status_code == 409
        payload = response.json()
        assert payload["code"] == "conversation_truncate_not_committed"
        assert payload["status"] == 409
        assert payload["rollbackResults"][0]["success"] is False
        assert "related document changed after the AI operation" in payload["detail"]
        assert "newer edits" in payload["detail"]
        assert "success" not in payload
        assert "committed" not in payload
    finally:
        client.close()
        temporary.cleanup()


def test_truncate_success_contract_explicitly_confirms_commit() -> None:
    client, temporary = build_client()
    try:
        conversation = client.app.state.conversation_service.create("title", "system")
        with mock.patch.object(
            client.app.state.conversation_service,
            "truncate",
            return_value={
                "committed": True,
                "message": "Conversation truncated",
                "rollback_results": [],
            },
        ):
            response = client.post(
                f"/api/v1/conversations/{conversation['id']}/truncate",
                json={"user_message_number": 0, "include_user_message": True},
            )

        assert response.status_code == 200
        assert response.json() == {
            "success": True,
            "committed": True,
            "message": "Conversation truncated",
            "rollback_results": [],
        }
    finally:
        client.close()
        temporary.cleanup()
