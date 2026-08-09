from __future__ import annotations

import pytest

from .test_platform_api import build_client


@pytest.mark.parametrize(
    ("method", "path_suffix", "body"),
    [
        ("PATCH", "", {"title": "renamed"}),
        ("DELETE", "", None),
        ("POST", "/partial", {"content": "partial", "reasoning": ""}),
        (
            "POST",
            "/truncate",
            {"user_message_number": 0, "include_user_message": True},
        ),
    ],
)
def test_conversation_mutations_cannot_race_active_stream(method, path_suffix, body):
    client, temp = build_client()
    try:
        conversation = client.app.state.conversation_service.create("hello", "system")
        conversation_id = conversation["id"]
        agent = client.app.state.agent_service
        with agent.exclusive_conversation(conversation_id):
            response = client.request(
                method,
                f"/api/v1/conversations/{conversation_id}{path_suffix}",
                json=body,
            )
        assert response.status_code == 409
        assert response.json()["code"] == "conversation_busy"

        released = client.patch(
            f"/api/v1/conversations/{conversation_id}", json={"title": "released"}
        )
        assert released.status_code == 200
    finally:
        client.close()
        temp.cleanup()
