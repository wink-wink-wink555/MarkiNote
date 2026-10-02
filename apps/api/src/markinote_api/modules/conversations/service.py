"""Conversation application use cases."""
from __future__ import annotations

import copy
import uuid
from datetime import UTC, datetime
from typing import Any

from markinote_api.modules.conversations.repository import ConversationData, ConversationRepository
from markinote_api.modules.conversations.saga import ConversationRollbackSaga
from markinote_api.modules.operations.backup import BackupManager
from markinote_api.modules.operations.database_backup import DatabaseBackupManager
from markinote_api.platform.errors import Problem
from markinote_api.platform.paths import PathValidationError, validate_storage_id


class DatabaseConversationRollback:
    """Database-native rollback sequence without filesystem saga records."""

    def __init__(self, backup_manager: DatabaseBackupManager):
        self.backup_manager = backup_manager

    def recover(self, repository: ConversationRepository, conversation_id: str) -> None:
        return None

    def delete_terminal_records(self, conversation_id: str) -> None:
        return None

    def execute(
        self,
        repository: ConversationRepository,
        value: ConversationData,
        target_messages: list[dict[str, Any]],
        rollback_steps: list[dict[str, Any]],
    ) -> tuple[bool, list[dict[str, Any]]]:
        results: list[dict[str, Any]] = []
        for step in rollback_steps:
            ok, message = self.backup_manager.rollback_operation(
                step["group_id"], step["operation_index"]
            )
            results.append({**step, "success": ok, "message": message})
            if not ok:
                return False, results
        value["messages"] = target_messages
        repository.save(value)
        return True, results


class ConversationService:
    def __init__(
        self,
        repository: ConversationRepository,
        backup_manager: BackupManager | DatabaseBackupManager,
    ):
        self.repository = repository
        self.backup_manager = backup_manager
        self.rollback_sagas = (
            DatabaseConversationRollback(backup_manager)
            if isinstance(backup_manager, DatabaseBackupManager)
            else ConversationRollbackSaga(backup_manager)
        )

    def list(self) -> list[dict[str, Any]]:
        values = self.repository.list()
        values.sort(key=lambda value: str(value.get("updated_at", "")), reverse=True)
        return [
            {
                "id": value.get("id"),
                "title": value.get("title", "New conversation"),
                "created_at": value.get("created_at"),
                "updated_at": value.get("updated_at"),
                "message_count": int(
                    value.get(
                        "message_count",
                        sum(
                            1
                            for item in value.get("messages", [])
                            if isinstance(item, dict) and item.get("role") != "system"
                        ),
                    )
                ),
            }
            for value in values
        ]

    def get_raw(self, conversation_id: str) -> ConversationData:
        self._validate_id(conversation_id)
        conversation = self.repository.get(conversation_id)
        if not conversation:
            raise Problem(404, "conversation_not_found", "Conversation not found", "The conversation does not exist.")
        return conversation

    def get_display(self, conversation_id: str) -> dict[str, Any]:
        conversation = self.get_raw(conversation_id)
        messages = []
        for message in conversation.get("messages", []):
            if not isinstance(message, dict) or message.get("role") == "system":
                continue
            item = {
                "role": message.get("role"),
                "content": message.get("_display_content", message.get("content", "")),
            }
            for source, destination in (
                ("tool_calls", "tool_calls"),
                ("tool_call_id", "tool_call_id"),
                ("_tool_meta", "tool_meta"),
                ("_reasoning", "reasoning"),
                ("_attachments", "attachments"),
                ("_context_file", "context_file"),
            ):
                if message.get(source) is not None:
                    item[destination] = message[source]
            messages.append(item)
        return {
            "id": conversation["id"],
            "title": conversation.get("title", "New conversation"),
            "messages": messages,
        }

    def create(self, user_message: str, system_prompt: str) -> ConversationData:
        now = datetime.now(UTC).isoformat()
        value: ConversationData = {
            "id": uuid.uuid4().hex[:12],
            "title": user_message[:30] or "New conversation",
            "created_at": now,
            "updated_at": now,
            "messages": [{"role": "system", "content": system_prompt}],
        }
        self.repository.save(value)
        return value

    def rename(self, conversation_id: str, title: str) -> str:
        value = self.get_raw(conversation_id)
        cleaned = title.strip()
        if not cleaned:
            raise Problem(422, "invalid_title", "Invalid title", "The title cannot be empty.")
        value["title"] = cleaned[:100]
        self.repository.save(value)
        return value["title"]

    def delete(self, conversation_id: str) -> int:
        self._validate_id(conversation_id)
        if self.repository.get(conversation_id) is None:
            raise Problem(
                404,
                "conversation_not_found",
                "Conversation not found",
                "The conversation does not exist.",
            )
        # Resolve interrupted work first. A Saga that still cannot be
        # compensated blocks deletion and retains every recovery payload; a
        # successfully resolved record becomes terminal and can be removed.
        self.rollback_sagas.recover(self.repository, conversation_id)
        # Terminal Saga history is no longer needed for recovery and may refer
        # to conversation content. Remove it before deleting the authoritative
        # conversation so an I/O failure can fail closed.
        self.rollback_sagas.delete_terminal_records(conversation_id)
        if not self.repository.delete(conversation_id):
            raise Problem(
                404,
                "conversation_not_found",
                "Conversation not found",
                "The conversation does not exist.",
            )
        return self.backup_manager.delete_conversation_backups(conversation_id)

    def save_partial(self, conversation_id: str, content: str, reasoning: str = "") -> bool:
        value = self.get_raw(conversation_id)
        changed = append_partial_assistant(value, content, reasoning)
        if changed:
            self.repository.save(value)
        return changed

    def truncate(self, conversation_id: str, user_message_number: int, include_user_message: bool) -> dict[str, Any]:
        self._validate_id(conversation_id)
        self.rollback_sagas.recover(self.repository, conversation_id)
        value = self.get_raw(conversation_id)
        messages = value.get("messages", [])
        count = -1
        truncate_at = len(messages)
        for index, message in enumerate(messages):
            if isinstance(message, dict) and message.get("role") == "user":
                count += 1
                if count == user_message_number:
                    truncate_at = index if include_user_message else index + 1
                    break
        if truncate_at == len(messages):
            return {
                "committed": True,
                "message": "Nothing to truncate",
                "rollback_results": [],
            }

        removed = messages[truncate_at:]
        rollback_steps: list[dict[str, Any]] = []
        seen_steps: set[tuple[str, int | None]] = set()
        for message in removed:
            if not isinstance(message, dict):
                continue
            tool_meta = message.get("_tool_meta") or {}
            if not isinstance(tool_meta, dict):
                continue
            group = tool_meta.get("backup_group_id")
            if not isinstance(group, str):
                continue
            backup_info = tool_meta.get("backup_info") or {}
            operation_index = (
                backup_info.get("operation_index") if isinstance(backup_info, dict) else None
            )
            if isinstance(operation_index, bool) or not isinstance(operation_index, int):
                operation_index = None
            key = (group, operation_index)
            if operation_index is None:
                rollback_steps = [
                    step for step in rollback_steps if step["group_id"] != group
                ]
                seen_steps = {item for item in seen_steps if item[0] != group}
            elif (group, None) in seen_steps:
                continue
            if key not in seen_steps:
                seen_steps.add(key)
                rollback_steps.append(
                    {"group_id": group, "operation_index": operation_index}
                )

        target_messages = copy.deepcopy(messages[:truncate_at])
        if not rollback_steps:
            value["messages"] = target_messages
            self.repository.save(value)
            return {
                "committed": True,
                "message": "Conversation truncated",
                "rollback_results": [],
            }

        committed, rollback_results = self.rollback_sagas.execute(
            self.repository,
            value,
            target_messages,
            list(reversed(rollback_steps)),
        )
        if not committed:
            return {
                "committed": False,
                "message": "Conversation was not truncated because file rollback failed",
                "rollback_results": rollback_results,
            }
        return {
            "committed": True,
            "message": "Conversation truncated",
            "rollback_results": rollback_results,
        }

    @staticmethod
    def _validate_id(value: str) -> None:
        try:
            validate_storage_id(value, "conversation id")
        except PathValidationError as error:
            raise Problem(
                400,
                "invalid_conversation_id",
                "Invalid conversation id",
                "The conversation identifier does not match the accepted format.",
            ) from error


def append_partial_assistant(conversation: ConversationData, content: str, reasoning: str = "") -> bool:
    if not content and not reasoning:
        return False
    messages = conversation.setdefault("messages", [])
    if messages and messages[-1].get("role") == "assistant":
        existing = messages[-1].get("content", "")
        if existing == content:
            if reasoning and not messages[-1].get("_reasoning"):
                messages[-1]["_reasoning"] = reasoning
                return True
            return False
        if existing and content.startswith(existing) and not messages[-1].get("tool_calls"):
            messages[-1]["content"] = content
            if reasoning:
                messages[-1]["_reasoning"] = reasoning
            return True
    message = {"role": "assistant", "content": content or "(interrupted)"}
    if reasoning:
        message["_reasoning"] = reasoning
    messages.append(message)
    return True
