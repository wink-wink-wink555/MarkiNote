from __future__ import annotations

import json
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import event, inspect, select, update
from sqlalchemy.sql.dml import Update

from markinote_api.modules.conversations.repository import Database, ToolCommandRecord
from markinote_api.modules.operations.journal import (
    CommandJournalCorruptionError,
    CommandOwnershipConflictError,
    JsonCommandJournal,
    SqlCommandJournal,
)


class MutableClock:
    def __init__(self) -> None:
        self.value = datetime(2026, 7, 18, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **values: float) -> None:
        self.value += timedelta(**values)


def _claim(journal: JsonCommandJournal | SqlCommandJournal, command_id: str):
    return journal.claim(
        command_id,
        run_id="run",
        conversation_id="conversation",
        tool_name="write_file",
    )


def test_json_claim_has_lease_and_only_one_concurrent_owner() -> None:
    with tempfile.TemporaryDirectory() as directory:
        clock = MutableClock()
        journal = JsonCommandJournal(directory, lease_duration=timedelta(seconds=30), now=clock)
        barrier = threading.Barrier(8)

        def contender(_: int) -> bool:
            barrier.wait()
            return _claim(journal, "concurrent-command")[0]

        with ThreadPoolExecutor(max_workers=8) as executor:
            claimed = list(executor.map(contender, range(8)))

        assert claimed.count(True) == 1
        values = json.loads(journal.commands_file.read_text(encoding="utf-8"))
        command_value = values["concurrent-command"]
        assert command_value["attempt"] == 1
        assert datetime.fromisoformat(command_value["lease_until"]) == clock.value + timedelta(seconds=30)


def test_json_expired_claim_is_atomically_taken_over_but_live_claim_is_not() -> None:
    with tempfile.TemporaryDirectory() as directory:
        clock = MutableClock()
        journal = JsonCommandJournal(directory, lease_duration=timedelta(seconds=10), now=clock)
        assert _claim(journal, "recoverable") == (True, None)
        assert _claim(journal, "recoverable") == (False, None)

        clock.advance(seconds=11)
        barrier = threading.Barrier(6)

        def contender(_: int) -> bool:
            barrier.wait()
            return _claim(journal, "recoverable")[0]

        with ThreadPoolExecutor(max_workers=6) as executor:
            claimed = list(executor.map(contender, range(6)))
        assert claimed.count(True) == 1
        command_value = json.loads(journal.commands_file.read_text(encoding="utf-8"))["recoverable"]
        assert command_value["attempt"] == 2

        # The winning contender owns attempt 2 in its worker context. Simulate
        # that worker crashing too, then verify a new owner can finish attempt 3.
        clock.advance(seconds=11)
        recovery_worker = JsonCommandJournal(
            directory,
            lease_duration=timedelta(seconds=10),
            now=clock,
        )
        assert _claim(recovery_worker, "recoverable") == (True, None)
        recovery_worker.complete("recoverable", {"result": "done"})
        assert _claim(journal, "recoverable") == (False, {"result": "done"})


def test_json_takeover_fences_stale_owner_completion() -> None:
    with tempfile.TemporaryDirectory() as directory:
        clock = MutableClock()
        first = JsonCommandJournal(directory, lease_duration=timedelta(seconds=1), now=clock)
        second = JsonCommandJournal(directory, lease_duration=timedelta(seconds=1), now=clock)
        assert _claim(first, "fenced")[0]
        clock.advance(seconds=2)
        assert _claim(second, "fenced")[0]

        first.complete("fenced", {"result": "stale"})
        value = json.loads(first.commands_file.read_text(encoding="utf-8"))["fenced"]
        assert value["state"] == "running"
        assert value["attempt"] == 2
        second.complete("fenced", {"result": "current"})
        assert _claim(first, "fenced") == (False, {"result": "current"})


@pytest.mark.parametrize(
    ("terminal_method", "expected_state"),
    (("complete", "completed"), ("fail", "failed")),
)
def test_json_terminal_write_is_fenced_by_attempt_and_reports_the_winner(
    terminal_method: str,
    expected_state: str,
) -> None:
    with tempfile.TemporaryDirectory() as directory:
        clock = MutableClock()
        stale_owner = JsonCommandJournal(
            directory,
            lease_duration=timedelta(seconds=5),
            now=clock,
        )
        current_owner = JsonCommandJournal(
            directory,
            lease_duration=timedelta(seconds=5),
            now=clock,
        )
        assert _claim(stale_owner, "json-terminal-fence") == (True, None)
        clock.advance(seconds=6)
        assert _claim(current_owner, "json-terminal-fence") == (True, None)

        assert (
            getattr(stale_owner, terminal_method)(
                "json-terminal-fence", {"owner": "stale"}
            )
            is False
        )
        assert (
            getattr(current_owner, terminal_method)(
                "json-terminal-fence", {"owner": "current"}
            )
            is True
        )

        durable = current_owner.inspect("json-terminal-fence")
        assert durable is not None
        assert durable["attempt"] == 2
        assert durable["state"] == expected_state
        assert durable["result"] == {"owner": "current"}
        # The owner token is consumed by a successful terminal transition, so
        # even that worker cannot rewrite a terminal record afterward.
        opposite = "fail" if terminal_method == "complete" else "complete"
        assert (
            getattr(current_owner, opposite)(
                "json-terminal-fence", {"owner": "late-rewrite"}
            )
            is False
        )


def test_json_terminal_state_cannot_be_rewritten_by_a_copied_owner_context() -> None:
    with tempfile.TemporaryDirectory() as directory:
        journal = JsonCommandJournal(directory)
        assert _claim(journal, "json-copied-context") == (True, None)
        copied_owner_context = copy_context()

        assert journal.complete("json-copied-context", {"owner": "winner"}) is True
        assert (
            copied_owner_context.run(
                journal.fail,
                "json-copied-context",
                {"owner": "copied-context-loser"},
            )
            is False
        )

        durable = journal.inspect("json-copied-context")
        assert durable is not None
        assert durable["state"] == "completed"
        assert durable["result"] == {"owner": "winner"}


def test_json_command_retention_applies_ttl_and_max_without_evicting_running() -> None:
    with tempfile.TemporaryDirectory() as directory:
        clock = MutableClock()
        journal = JsonCommandJournal(
            directory,
            retention_ttl=timedelta(seconds=20),
            max_commands=3,
            now=clock,
        )
        assert _claim(journal, "active")[0]
        for command_id in ("one", "two", "three"):
            assert _claim(journal, command_id)[0]
            journal.complete(command_id, {"result": command_id})
            clock.advance(seconds=1)

        values = json.loads(journal.commands_file.read_text(encoding="utf-8"))
        assert set(values) == {"active", "two", "three"}

        clock.advance(seconds=30)
        assert _claim(journal, "new-active")[0]
        values = json.loads(journal.commands_file.read_text(encoding="utf-8"))
        assert set(values) == {"active", "new-active"}


def test_corrupt_json_journal_fails_closed_instead_of_reexecuting() -> None:
    with tempfile.TemporaryDirectory() as directory:
        journal = JsonCommandJournal(directory)
        journal.commands_file.write_text("{not-json", encoding="utf-8")
        with pytest.raises(CommandJournalCorruptionError, match="duplicate execution"):
            _claim(journal, "must-not-run")


def test_json_command_scope_conflict_never_replays_or_takes_over() -> None:
    with tempfile.TemporaryDirectory() as directory:
        clock = MutableClock()
        journal = JsonCommandJournal(
            directory,
            lease_duration=timedelta(seconds=1),
            now=clock,
        )
        assert _claim(journal, "scoped-json") == (True, None)
        assert journal.complete("scoped-json", {"result": "private-result"}) is True

        with pytest.raises(CommandOwnershipConflictError):
            journal.claim(
                "scoped-json",
                run_id="run",
                conversation_id="different-conversation",
                tool_name="write_file",
            )

        durable = journal.inspect("scoped-json")
        assert durable is not None
        assert durable["result"] == {"result": "private-result"}
        assert durable["conversation_id"] == "conversation"


def test_sql_claim_lease_takeover_and_terminal_replay() -> None:
    with tempfile.TemporaryDirectory() as directory:
        clock = MutableClock()
        database = Database(f"sqlite:///{(Path(directory) / 'commands.db').as_posix()}", create_schema=True)
        journal = SqlCommandJournal(database, lease_duration=timedelta(seconds=10), now=clock)
        try:
            assert _claim(journal, "sql-command") == (True, None)
            assert _claim(journal, "sql-command") == (False, None)
            clock.advance(seconds=11)
            assert _claim(journal, "sql-command") == (True, None)
            with database.session() as session:
                record = session.get(ToolCommandRecord, "sql-command")
                assert record is not None and record.attempt == 2
            journal.complete("sql-command", {"result": "done"})
            assert _claim(journal, "sql-command") == (False, {"result": "done"})
        finally:
            database.close()


def test_sql_failed_takeover_refreshes_a_concurrently_completed_result() -> None:
    """Simulate the original owner committing after duplicate-owner SELECT."""
    with tempfile.TemporaryDirectory() as directory:
        clock = MutableClock()
        database = Database(
            f"sqlite:///{(Path(directory) / 'takeover-refresh.db').as_posix()}",
            create_schema=True,
        )
        original = SqlCommandJournal(
            database,
            lease_duration=timedelta(seconds=1),
            now=clock,
        )
        duplicate = SqlCommandJournal(
            database,
            lease_duration=timedelta(seconds=1),
            now=clock,
        )
        injected = False

        def complete_before_takeover(connection, clause, *_args, **_kwargs):
            nonlocal injected
            if (
                injected
                or not isinstance(clause, Update)
                or clause.table.name != "tool_commands"
                or "attempt" not in str(clause)
            ):
                return
            injected = True
            connection.execute(
                update(ToolCommandRecord)
                .where(ToolCommandRecord.command_id == "refresh-race")
                .values(
                    state="completed",
                    result={"result": "durable-winner"},
                    completed_at=clock(),
                    lease_until=None,
                )
            )

        try:
            assert _claim(original, "refresh-race") == (True, None)
            clock.advance(seconds=2)
            event.listen(database.engine, "before_execute", complete_before_takeover)

            assert _claim(duplicate, "refresh-race") == (
                False,
                {"result": "durable-winner"},
            )
            assert injected
        finally:
            event.remove(database.engine, "before_execute", complete_before_takeover)
            database.close()


def test_sql_command_scope_conflict_never_replays_or_takes_over() -> None:
    with tempfile.TemporaryDirectory() as directory:
        clock = MutableClock()
        database = Database(
            f"sqlite:///{(Path(directory) / 'scope.db').as_posix()}",
            create_schema=True,
        )
        journal = SqlCommandJournal(
            database,
            lease_duration=timedelta(seconds=1),
            now=clock,
        )
        try:
            assert _claim(journal, "scoped-sql") == (True, None)
            assert journal.complete("scoped-sql", {"result": "private-result"}) is True

            with pytest.raises(CommandOwnershipConflictError):
                journal.claim(
                    "scoped-sql",
                    run_id="different-run",
                    conversation_id="conversation",
                    tool_name="write_file",
                )

            durable = journal.inspect("scoped-sql")
            assert durable is not None
            assert durable["result"] == {"result": "private-result"}
            assert durable["run_id"] == "run"
        finally:
            database.close()


def test_sql_takeover_fences_stale_owner_completion() -> None:
    with tempfile.TemporaryDirectory() as directory:
        clock = MutableClock()
        database = Database(f"sqlite:///{(Path(directory) / 'fencing.db').as_posix()}", create_schema=True)
        first = SqlCommandJournal(database, lease_duration=timedelta(seconds=1), now=clock)
        second = SqlCommandJournal(database, lease_duration=timedelta(seconds=1), now=clock)
        try:
            assert _claim(first, "fenced")[0]
            clock.advance(seconds=2)
            assert _claim(second, "fenced")[0]
            first.complete("fenced", {"result": "stale"})
            with database.session() as session:
                record = session.get(ToolCommandRecord, "fenced")
                assert record is not None and record.state == "running" and record.attempt == 2
            second.complete("fenced", {"result": "current"})
            assert _claim(first, "fenced") == (False, {"result": "current"})
        finally:
            database.close()


@pytest.mark.parametrize(
    ("terminal_method", "expected_state"),
    (("complete", "completed"), ("fail", "failed")),
)
def test_sql_terminal_update_is_conditioned_on_running_state_and_owned_attempt(
    terminal_method: str,
    expected_state: str,
) -> None:
    with tempfile.TemporaryDirectory() as directory:
        clock = MutableClock()
        database = Database(
            f"sqlite:///{(Path(directory) / 'terminal-fence.db').as_posix()}",
            create_schema=True,
        )
        stale_owner = SqlCommandJournal(
            database,
            lease_duration=timedelta(seconds=5),
            now=clock,
        )
        current_owner = SqlCommandJournal(
            database,
            lease_duration=timedelta(seconds=5),
            now=clock,
        )
        try:
            assert _claim(stale_owner, "sql-terminal-fence") == (True, None)
            clock.advance(seconds=6)
            assert _claim(current_owner, "sql-terminal-fence") == (True, None)

            # This exercises the conditional UPDATE after a real SQLite
            # interleaving: attempt 1 must not terminate attempt 2.
            assert (
                getattr(stale_owner, terminal_method)(
                    "sql-terminal-fence", {"owner": "stale"}
                )
                is False
            )
            assert (
                getattr(current_owner, terminal_method)(
                    "sql-terminal-fence", {"owner": "current"}
                )
                is True
            )

            opposite = "fail" if terminal_method == "complete" else "complete"
            assert (
                getattr(current_owner, opposite)(
                    "sql-terminal-fence", {"owner": "late-rewrite"}
                )
                is False
            )
            with database.session() as session:
                record = session.get(ToolCommandRecord, "sql-terminal-fence")
                assert record is not None
                assert record.attempt == 2
                assert record.state == expected_state
                assert record.result == {"owner": "current"}
        finally:
            database.close()


def test_sql_expired_takeover_has_one_concurrent_winner() -> None:
    with tempfile.TemporaryDirectory() as directory:
        clock = MutableClock()
        database = Database(f"sqlite:///{(Path(directory) / 'commands.db').as_posix()}", create_schema=True)
        journal = SqlCommandJournal(database, lease_duration=timedelta(seconds=1), now=clock)
        try:
            assert _claim(journal, "sql-race")[0]
            clock.advance(seconds=2)
            barrier = threading.Barrier(4)

            def contender(_: int) -> bool:
                barrier.wait()
                return _claim(journal, "sql-race")[0]

            with ThreadPoolExecutor(max_workers=4) as executor:
                claimed = list(executor.map(contender, range(4)))
            assert claimed.count(True) == 1
            with database.session() as session:
                attempt = session.scalar(
                    select(ToolCommandRecord.attempt).where(
                        ToolCommandRecord.command_id == "sql-race"
                    )
                )
                assert attempt == 2
        finally:
            database.close()


def test_alembic_head_adds_command_lease_columns_without_rewriting_initial_revision() -> None:
    with tempfile.TemporaryDirectory() as directory:
        database_path = Path(directory) / "migration.db"
        config = Config("alembic.ini")
        config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path.as_posix()}")
        command.upgrade(config, "head")

        database = Database(f"sqlite:///{database_path.as_posix()}")
        try:
            columns = {column["name"] for column in inspect(database.engine).get_columns("tool_commands")}
            assert {"lease_until", "attempt"}.issubset(columns)
            assert database.ready()
        finally:
            database.close()
