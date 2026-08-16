from __future__ import annotations

import asyncio
import json
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import mock

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from starlette.requests import ClientDisconnect

from markinote_api.modules.agent.router import _ClosingStreamingResponse
from markinote_api.modules.agent.run_journal import JsonAgentRunJournal, SqlAgentRunJournal
from markinote_api.modules.agent.schemas import ChatRequest
from markinote_api.modules.conversations.repository import (
    EXPECTED_SCHEMA_REVISION,
    AgentRunRecord,
    Database,
)

from .test_platform_api import build_client


class MutableClock:
    def __init__(self) -> None:
        self.value = datetime(2026, 7, 18, 8, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **values: float) -> None:
        self.value += timedelta(**values)


def simple_reply(*_args, **_kwargs):
    yield {"type": "content", "content": "answer"}
    yield {"type": "done"}


def failed_reply(*_args, **_kwargs):
    yield {"type": "content", "content": "partial"}
    yield {"type": "error", "message": "provider unavailable"}


def cancelled_reply(*_args, **_kwargs):
    yield from ()
    raise asyncio.CancelledError


def test_agent_stream_close_before_first_pull_cancels_run_and_removes_ghost_conversation() -> None:
    client, temp = build_client()
    try:
        service = client.app.state.agent_service
        with mock.patch(
            "markinote_api.modules.agent.service.stream_chat_completion",
        ) as provider:
            events = service.stream(
                ChatRequest(
                    message="never pulled",
                    run_id="run-never-pulled",
                    api_key="transient-secret",
                ),
                request_id="req-never-pulled",
            )
            assert len(service._active_conversations) == 1
            assert client.app.state.agent_run_journal.inspect(
                "run-never-pulled", "req-never-pulled"
            )["state"] == "running"

            events.close()
            events.close()

        provider.assert_not_called()
        cancelled = client.app.state.agent_run_journal.inspect(
            "run-never-pulled", "req-never-pulled"
        )
        assert cancelled["state"] == "cancelled"
        assert cancelled["error_code"] == "client_cancelled_before_stream"
        assert service._active_conversations == set()
        assert not any(client.app.state.settings.conversations_folder.glob("*.json"))
    finally:
        client.close()
        temp.cleanup()


def test_agent_streaming_response_closes_managed_stream_before_body_on_disconnect() -> None:
    close_calls = []
    response = _ClosingStreamingResponse(
        iter(["not-sent"]),
        close_callback=lambda: close_calls.append("closed"),
        media_type="text/event-stream",
        headers={},
    )

    async def exercise() -> None:
        async def receive() -> dict[str, str]:
            return {"type": "http.disconnect"}

        async def send(_message: dict[str, object]) -> None:
            raise OSError("client disconnected before response start")

        with pytest.raises(ClientDisconnect):
            await response(
                {"type": "http", "asgi": {"spec_version": "2.4"}},
                receive,
                send,
            )

    asyncio.run(exercise())
    assert close_calls == ["closed"]


def _exercise_lifecycle(journal: JsonAgentRunJournal | SqlAgentRunJournal) -> None:
    assert journal.start(
        run_id="stable-run",
        request_id="req-1",
        provider="deepseek",
        model="deepseek-v4-flash",
    )
    assert not journal.start(
        run_id="stable-run",
        request_id="req-1",
        provider="deepseek",
        model="deepseek-v4-flash",
    )
    # A stable logical run may be retried by a distinct HTTP request without
    # overwriting the first attempt's audit record.
    assert journal.start(
        run_id="stable-run",
        request_id="req-2",
        provider="deepseek",
        model="deepseek-v4-flash",
    )
    assert journal.attach_conversation("stable-run", "req-1", "conversation-1")
    assert journal.mark_first_content("stable-run", "req-1")
    assert journal.finish("stable-run", "req-1", "completed")
    assert not journal.finish("stable-run", "req-1", "failed", error_code="late_failure")

    record = journal.inspect("stable-run", "req-1")
    assert record is not None
    assert record["state"] == "completed"
    assert record["conversation_id"] == "conversation-1"
    assert record["conversation_attached_at"]
    assert record["first_content_at"]
    assert record["finished_at"]
    assert record["error_code"] is None
    assert journal.inspect("stable-run", "req-2")["state"] == "running"


def test_json_agent_run_journal_is_durable_and_contains_metadata_only(tmp_path: Path) -> None:
    clock = MutableClock()
    journal = JsonAgentRunJournal(tmp_path, now=clock)
    _exercise_lifecycle(journal)

    restarted = JsonAgentRunJournal(tmp_path, now=clock)
    assert restarted.inspect("stable-run", "req-2")["state"] == "running"
    serialized = journal.path.read_text(encoding="utf-8")
    assert "api_key" not in serialized
    assert "message" not in serialized
    assert "answer" not in serialized
    assert set(next(iter(json.loads(serialized).values()))) == {
        "run_id",
        "request_id",
        "conversation_id",
        "provider",
        "model",
        "state",
        "started_at",
        "conversation_attached_at",
        "first_content_at",
        "finished_at",
        "updated_at",
        "error_code",
    }


def test_sqlite_agent_run_journal_has_the_same_fenced_lifecycle(tmp_path: Path) -> None:
    database = Database(f"sqlite:///{(tmp_path / 'runs.db').as_posix()}", create_schema=True)
    try:
        _exercise_lifecycle(SqlAgentRunJournal(database, now=MutableClock()))
    finally:
        database.close()


def test_json_retention_prunes_only_terminal_runs_by_ttl_and_capacity(tmp_path: Path) -> None:
    clock = MutableClock()
    journal = JsonAgentRunJournal(
        tmp_path,
        now=clock,
        retention_ttl=timedelta(seconds=10),
        max_records=2,
    )
    assert journal.start(
        run_id="expired", request_id="req-expired", provider="deepseek", model="model"
    )
    assert journal.finish("expired", "req-expired", "completed")
    assert journal.start(
        run_id="crashed", request_id="req-crashed", provider="deepseek", model="model"
    )

    clock.advance(seconds=11)
    assert journal.start(
        run_id="recent", request_id="req-recent", provider="deepseek", model="model"
    )
    assert journal.inspect("expired", "req-expired") is None
    assert journal.inspect("crashed", "req-crashed")["state"] == "running"

    assert journal.finish("recent", "req-recent", "failed", error_code="provider_error")
    assert journal.start(
        run_id="new-running",
        request_id="req-new-running",
        provider="deepseek",
        model="model",
    )
    # The cap evicts the oldest terminal record but never either running row.
    assert journal.inspect("recent", "req-recent") is None
    assert journal.inspect("crashed", "req-crashed")["state"] == "running"
    assert journal.inspect("new-running", "req-new-running")["state"] == "running"


def test_sql_prune_terminal_is_batched_and_preserves_running_runs(tmp_path: Path) -> None:
    clock = MutableClock()
    database = Database(f"sqlite:///{(tmp_path / 'prune.db').as_posix()}", create_schema=True)
    journal = SqlAgentRunJournal(database, now=clock)
    try:
        assert journal.start(
            run_id="terminal", request_id="req-terminal", provider="deepseek", model="model"
        )
        assert journal.finish("terminal", "req-terminal", "completed")
        assert journal.start(
            run_id="running", request_id="req-running", provider="deepseek", model="model"
        )
        clock.advance(seconds=1)
        assert journal.prune_terminal(before=clock(), limit=1) == 1
        assert journal.inspect("terminal", "req-terminal") is None
        assert journal.inspect("running", "req-running")["state"] == "running"
        assert journal.prune_terminal(before=clock(), limit=1) == 0
    finally:
        database.close()


def test_agent_run_migration_upgrades_0001_through_0003_and_readiness_requires_head() -> None:
    with tempfile.TemporaryDirectory() as directory:
        database_path = Path(directory) / "migration.db"
        url = f"sqlite:///{database_path.as_posix()}"
        config = Config("alembic.ini")
        config.set_main_option("sqlalchemy.url", url)
        command.upgrade(config, "20260718_0001")
        pre_upgrade = Database(url)
        try:
            assert "agent_runs" not in inspect(pre_upgrade.engine).get_table_names()
            assert not pre_upgrade.ready()
        finally:
            pre_upgrade.close()

        command.upgrade(config, "head")
        database = Database(url)
        try:
            inspector = inspect(database.engine)
            assert {"lease_until", "attempt"}.issubset(
                {column["name"] for column in inspector.get_columns("tool_commands")}
            )
            assert {
                "run_id",
                "request_id",
                "conversation_id",
                "provider",
                "model",
                "state",
                "started_at",
                "conversation_attached_at",
                "first_content_at",
                "finished_at",
                "updated_at",
                "error_code",
                "user_id",
            } == {column["name"] for column in inspector.get_columns("agent_runs")}
            assert inspector.get_pk_constraint("agent_runs")["constrained_columns"] == [
                "run_id",
                "request_id",
            ]
            indexes = {
                index["name"]: index["column_names"]
                for index in inspector.get_indexes("agent_runs")
            }
            model_indexes = {
                index.name: [column.name for column in index.columns]
                for index in AgentRunRecord.__table__.indexes
            }
            assert indexes == model_indexes
            with database.engine.connect() as connection:
                assert (
                    connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one()
                    == EXPECTED_SCHEMA_REVISION
                )
            assert database.ready()
        finally:
            database.close()


def test_agent_service_persists_completed_and_provider_failed_lifecycles() -> None:
    client, temp = build_client()
    try:
        with mock.patch(
            "markinote_api.modules.agent.service.stream_chat_completion",
            side_effect=simple_reply,
        ):
            completed = client.post(
                "/api/v1/agent/chat",
                headers={"X-Request-ID": "req-completed"},
                json={
                    "message": "not persisted in run audit",
                    "run_id": "run-completed",
                    "api_key": "transient-secret",
                },
            )
        assert completed.status_code == 200
        completed_record = client.app.state.agent_run_journal.inspect(
            "run-completed", "req-completed"
        )
        assert completed_record["state"] == "completed"
        assert completed_record["first_content_at"]
        assert completed_record["error_code"] is None

        with mock.patch(
            "markinote_api.modules.agent.service.stream_chat_completion",
            side_effect=failed_reply,
        ):
            failed = client.post(
                "/api/v1/agent/chat",
                headers={"X-Request-ID": "req-failed"},
                json={
                    "message": "also excluded",
                    "run_id": "run-failed",
                    "api_key": "another-transient-secret",
                },
            )
        assert failed.status_code == 200
        failed_record = client.app.state.agent_run_journal.inspect("run-failed", "req-failed")
        assert failed_record["state"] == "failed"
        assert failed_record["error_code"] == "provider_error"

        audit = (
            client.app.state.settings.backups_folder / "journal" / "agent_runs.json"
        ).read_text(encoding="utf-8")
        assert "transient-secret" not in audit
        assert "not persisted in run audit" not in audit
        assert "answer" not in audit
        assert client.app.state.agent_service._active_conversations == set()
    finally:
        client.close()
        temp.cleanup()


def test_agent_generator_close_is_cancelled_and_terminal_write_failure_leaves_running_audit() -> None:
    client, temp = build_client()
    try:
        service = client.app.state.agent_service
        events = service.stream(
            ChatRequest(
                message="cancel me",
                run_id="run-cancelled",
                api_key="transient-secret",
            ),
            request_id="req-cancelled",
        )
        assert next(events)[0] == "conversation_id"
        events.close()
        cancelled = client.app.state.agent_run_journal.inspect(
            "run-cancelled", "req-cancelled"
        )
        assert cancelled["state"] == "cancelled"
        assert cancelled["error_code"] == "client_cancelled"
        assert service._active_conversations == set()

        with mock.patch(
            "markinote_api.modules.agent.service.stream_chat_completion",
            side_effect=cancelled_reply,
        ):
            cancelled_events = service.stream(
                ChatRequest(
                    message="cancel at provider boundary",
                    run_id="run-task-cancelled",
                    api_key="transient-secret",
                ),
                request_id="req-task-cancelled",
            )
            assert next(cancelled_events)[0] == "conversation_id"
            with pytest.raises(asyncio.CancelledError):
                next(cancelled_events)
        task_cancelled = client.app.state.agent_run_journal.inspect(
            "run-task-cancelled", "req-task-cancelled"
        )
        assert task_cancelled["state"] == "cancelled"
        assert task_cancelled["error_code"] == "client_cancelled"
        assert service._active_conversations == set()

        journal = client.app.state.agent_run_journal
        with (
            mock.patch(
                "markinote_api.modules.agent.service.stream_chat_completion",
                side_effect=simple_reply,
            ),
            mock.patch.object(journal, "finish", side_effect=OSError("audit unavailable")),
        ):
            response = client.post(
                "/api/v1/agent/chat",
                headers={"X-Request-ID": "req-finalizer-down"},
                json={
                    "message": "still release active state",
                    "run_id": "run-finalizer-down",
                    "api_key": "transient-secret",
                },
            )
        assert response.status_code == 200
        assert "event: done" in response.text
        assert service._active_conversations == set()
        # The durable running row is an explicit reconciliation signal; the
        # service never fabricates completion after a failed terminal write.
        stranded = journal.inspect("run-finalizer-down", "req-finalizer-down")
        assert stranded["state"] == "running"
    finally:
        client.close()
        temp.cleanup()
