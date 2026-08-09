"""Non-mocked PostgreSQL repository and HTTP adapter smoke for CI."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient

from markinote_api.application import create_application
from markinote_api.config import Settings
from markinote_api.modules.agent.run_journal import SqlAgentRunJournal
from markinote_api.modules.conversations.repository import ToolCommandRecord
from markinote_api.modules.operations.journal import SqlCommandJournal


def main() -> None:
    settings = Settings()
    if settings.conversation_backend != "database":
        raise RuntimeError("PostgreSQL smoke requires MARKINOTE_CONVERSATION_BACKEND=database")
    if settings.auto_create_database:
        raise RuntimeError("PostgreSQL smoke must exercise an Alembic-managed schema")

    application = create_application(settings)
    with TestClient(application) as client:
        ready = client.get("/health/ready")
        assert ready.status_code == 200, ready.text
        assert ready.json()["checks"]["database"] is True

        service = application.state.conversation_service
        conversation = service.create("PostgreSQL CI smoke", "system")
        conversation["messages"].extend(
            [
                {"role": "user", "content": "persist me"},
                {"role": "assistant", "content": "persisted"},
            ]
        )
        service.repository.save(conversation)
        conversation_id = conversation["id"]

        listed = client.get("/api/v1/conversations")
        assert listed.status_code == 200, listed.text
        summary = next(item for item in listed.json()["items"] if item["id"] == conversation_id)
        assert summary["message_count"] == 2

        detail = client.get(f"/api/v1/conversations/{conversation_id}")
        assert detail.status_code == 200, detail.text
        assert [item["content"] for item in detail.json()["conversation"]["messages"]] == [
            "persist me",
            "persisted",
        ]

        renamed = client.patch(
            f"/api/v1/conversations/{conversation_id}",
            json={"title": "PostgreSQL repository verified"},
        )
        assert renamed.status_code == 200, renamed.text
        assert renamed.json()["title"] == "PostgreSQL repository verified"

        deleted = client.delete(f"/api/v1/conversations/{conversation_id}")
        assert deleted.status_code == 200, deleted.text
        assert all(
            item["id"] != conversation_id
            for item in client.get("/api/v1/conversations").json()["items"]
        )

        # Exercise the PostgreSQL-specific atomic lease takeover and fencing
        # behavior used to prevent duplicate tool execution after a worker dies.
        database = application.state.database
        assert database is not None
        clock = [datetime.now(UTC)]

        def now() -> datetime:
            return clock[0]

        first_owner = SqlCommandJournal(
            database,
            lease_duration=timedelta(seconds=1),
            now=now,
        )
        recovery_owner = SqlCommandJournal(
            database,
            lease_duration=timedelta(seconds=1),
            now=now,
        )
        command_id = f"postgres-smoke-{uuid4().hex}"
        claim = {
            "run_id": "postgres-smoke-run",
            "conversation_id": None,
            "tool_name": "write_file",
        }
        assert first_owner.claim(command_id, **claim) == (True, None)
        assert recovery_owner.claim(command_id, **claim) == (False, None)

        clock[0] += timedelta(seconds=2)
        assert recovery_owner.claim(command_id, **claim) == (True, None)
        assert first_owner.complete(command_id, {"result": "stale-owner"}) is False
        with database.session() as session:
            record = session.get(ToolCommandRecord, command_id)
            assert record is not None
            assert record.state == "running"
            assert record.attempt == 2

        assert recovery_owner.complete(command_id, {"result": "recovered"}) is True
        assert first_owner.claim(command_id, **claim) == (
            False,
            {"result": "recovered"},
        )

        # Verify the same metadata-only lifecycle adapter against the actual
        # PostgreSQL driver/schema, including terminal fencing and inspection.
        agent_runs = SqlAgentRunJournal(database, now=now)
        agent_run_id = f"postgres-agent-run-{uuid4().hex}"
        agent_request_id = f"req-{uuid4().hex}"
        assert agent_runs.start(
            run_id=agent_run_id,
            request_id=agent_request_id,
            provider="deepseek",
            model="deepseek-v4-flash",
        )
        assert agent_runs.attach_conversation(
            agent_run_id,
            agent_request_id,
            conversation_id,
        )
        assert agent_runs.mark_first_content(agent_run_id, agent_request_id)
        running_agent = agent_runs.inspect(agent_run_id, agent_request_id)
        assert running_agent is not None
        assert running_agent["state"] == "running"
        assert running_agent["conversation_id"] == conversation_id
        assert running_agent["first_content_at"]
        assert agent_runs.finish(agent_run_id, agent_request_id, "completed")
        assert not agent_runs.finish(
            agent_run_id,
            agent_request_id,
            "failed",
            error_code="late_failure",
        )
        completed_agent = agent_runs.inspect(agent_run_id, agent_request_id)
        assert completed_agent is not None
        assert completed_agent["state"] == "completed"
        assert completed_agent["finished_at"]
        assert completed_agent["error_code"] is None
        clock[0] += timedelta(seconds=1)
        assert agent_runs.prune_terminal(before=clock[0], limit=1) == 1
        assert agent_runs.inspect(agent_run_id, agent_request_id) is None

    print(
        json.dumps(
            {
                "status": "ok",
                "flow": "postgres-alembic-repository-http-command-lease-agent-run",
                "conversationId": conversation_id,
                "commandId": command_id,
                "agentRunId": agent_run_id,
                "agentRequestId": agent_request_id,
            },
            separators=(",", ":"),
        )
    )


if __name__ == "__main__":
    main()
