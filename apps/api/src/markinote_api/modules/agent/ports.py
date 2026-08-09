"""Narrow application ports used by the framework-independent agent service."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from typing import Any, Literal, Protocol

AgentRunState = Literal["running", "completed", "failed", "cancelled"]
TerminalAgentRunState = Literal["completed", "failed", "cancelled"]
AgentRunData = dict[str, Any]


class AgentRunJournal(Protocol):
    """Metadata-only run audit; content and credentials are excluded by API."""

    def start(
        self,
        *,
        run_id: str,
        request_id: str,
        provider: str,
        model: str,
    ) -> bool: ...

    def attach_conversation(self, run_id: str, request_id: str, conversation_id: str) -> bool: ...

    def mark_first_content(self, run_id: str, request_id: str) -> bool: ...

    def finish(
        self,
        run_id: str,
        request_id: str,
        state: TerminalAgentRunState,
        *,
        error_code: str | None = None,
    ) -> bool: ...

    def inspect(self, run_id: str, request_id: str) -> AgentRunData | None: ...

    def reconcile_running(self, *, limit: int = 1000, apply: bool = False) -> int:
        """Count or terminalize one bounded batch left by a stopped sole writer."""
        ...

    def prune_terminal(self, *, before: datetime, limit: int = 1000) -> int: ...


class ProviderStreamPort(Protocol):
    def __call__(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        api_key: str,
        provider_id: str,
        model_id: str,
    ) -> Iterator[dict[str, Any]]: ...


class ToolExecutorPort(Protocol):
    def __call__(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        library_dir: str,
        backup_manager: AgentBackupPort,
        backup_group_id: str | None = None,
        **extra: Any,
    ) -> tuple[str, dict[str, Any] | None]: ...


class AgentBackupPort(Protocol):
    def create_operation_group(self, conversation_id: str | None = None) -> str: ...

    def complete_operation_group(self, group_id: str) -> None: ...

    def heartbeat_operation_group(self, group_id: str) -> None: ...

    def find_command(self, command_id: str) -> dict[str, Any] | None: ...

    def record_command_result(
        self,
        group_id: str,
        operation_index: int,
        command_id: str,
        result: str,
        backup_info: dict[str, Any],
    ) -> None: ...

    def mark_command_committed(
        self,
        group_id: str,
        operation_index: int,
        command_id: str,
    ) -> None: ...

    def compensate_active_operation(
        self,
        group_id: str,
        operation_index: int,
        *,
        observed_path: str = "",
        require_after_match: bool = False,
    ) -> tuple[bool, str]: ...

    def cleanup(
        self,
        max_count: int | None = None,
        max_bytes: int | None = None,
    ) -> None: ...


class CommandJournalPort(Protocol):
    def claim(
        self,
        command_id: str,
        *,
        run_id: str,
        conversation_id: str | None,
        tool_name: str,
    ) -> tuple[bool, dict[str, Any] | None]: ...

    def complete(self, command_id: str, result: dict[str, Any]) -> bool: ...

    def fail(self, command_id: str, result: dict[str, Any]) -> bool: ...

    def inspect(self, command_id: str) -> dict[str, Any] | None: ...

    def audit(
        self,
        *,
        request_id: str,
        action: str,
        outcome: str,
        conversation_id: str | None = None,
        command_id: str | None = None,
        target: str | None = None,
        content_hash: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None: ...
