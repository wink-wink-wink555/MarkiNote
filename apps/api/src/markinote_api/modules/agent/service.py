"""Framework-independent synchronous AI orchestration with SSE events."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from prometheus_client import Counter, Gauge

from markinote_api.config import Settings
from markinote_api.modules.agent.finance_mcp import FinanceMcpClient, FinanceMcpError
from markinote_api.modules.agent.ports import (
    AgentBackupPort,
    AgentRunJournal,
    CommandJournalPort,
    ProviderStreamPort,
    TerminalAgentRunState,
    ToolExecutorPort,
)
from markinote_api.modules.agent.provider import (
    PROVIDERS,
    generate_conversation_title,
    stream_chat_completion,
)
from markinote_api.modules.agent.schemas import ChatRequest
from markinote_api.modules.agent.tools import (
    MUTATING_TOOLS,
    TOOL_DEFINITIONS,
    execute_tool,
    get_system_prompt,
    sanitize_tool_arguments_for_persistence,
    sanitize_tool_call_arguments_for_persistence,
)
from markinote_api.modules.conversations.service import ConversationService, append_partial_assistant
from markinote_api.modules.documents.errors import DocumentError
from markinote_api.modules.documents.service import DocumentService
from markinote_api.platform.errors import Problem
from markinote_api.platform.paths import (
    PathValidationError,
    normalize_relative_path,
)

LOGGER = logging.getLogger(__name__)
MAX_TOOL_ITERATIONS = 8
MAX_TOTAL_TOOL_CALLS = 24
TOOL_RESULT_BYTES = 3_000
TOOL_RESULT_BACKUP_TYPE_BYTES = 64
TOOL_RESULT_BACKUP_PATH_BYTES = 1_024
TOOL_RESULT_BACKUP_GROUP_BYTES = 64
TOOL_APPROVAL_ID_BYTES = 64
# JSON/SQL manifests may outlive a run and therefore legitimately contain an
# operation index greater than the per-run tool-call count. Keep it within the
# exact integer range JavaScript clients can represent without widening a
# single-operation rollback into an accidental whole-group rollback.
MAX_ROLLBACK_OPERATION_INDEX = (1 << 53) - 1
AGENT_RUNS = Counter("markinote_agent_runs_total", "AI agent runs", ("provider",))
OPEN_AGENT_STREAMS = Gauge("markinote_agent_open_streams", "Currently open AI streams")
TOOL_COMMANDS = Counter(
    "markinote_agent_tool_commands_total",
    "AI tool command outcomes",
    ("tool", "outcome"),
)
TOOL_METRIC_NAMES = frozenset(
    {
        "create_file",
        "create_folder",
        "delete_item",
        "edit_file",
        "fetch_url",
        "list_directory",
        "move_item",
        "read_file",
        "search_files",
        "web_search",
        "write_file",
    }
)
UNTRUSTED_EXTERNAL_CONTENT_TOOLS = frozenset({"fetch_url", "web_search"})

PROVIDER_BOUNDARY_ERROR_MESSAGES = {
    "provider_frame_limit_exceeded": "AI provider sent an oversized stream frame.",
    "provider_event_limit_exceeded": "AI provider stream exceeded the event safety limit.",
    "provider_byte_limit_exceeded": "AI provider stream exceeded the byte safety limit.",
    "provider_stream_timeout": "AI provider stream exceeded the elapsed-time safety limit.",
}
PROVIDER_BOUNDARY_ERROR_CODES = frozenset(PROVIDER_BOUNDARY_ERROR_MESSAGES)

_DEICTIC_FILE_REFERENCE = re.compile(
    r"(?:这个|这份|该文件|该文档|当前文件|当前文档|所选文件|选中的文件|附件|把它|"
    r"\b(?:this|that|it|the current (?:file|document)|the selected (?:file|document)|"
    r"the attachment)\b|"
    r"\b(?:ce fichier|ce document|le fichier actuel|le document actuel|la pièce jointe)\b|"
    r"(?:これ|このファイル|この文書|現在のファイル|現在の文書|添付ファイル))",
    re.IGNORECASE,
)
_MUTATION_SOURCE_FIELDS = {
    "move_item": "source",
    "delete_item": "path",
    "edit_file": "path",
    "write_file": "path",
}
_MUTATION_DISPLAY_FIELDS = {
    "create_file": "path",
    "create_folder": "path",
    "delete_item": "path",
    "edit_file": "path",
    "move_item": "source",
    "write_file": "path",
}


def _mutation_source_path(tool_name: str, arguments: dict[str, Any]) -> str | None:
    source_field = _MUTATION_SOURCE_FIELDS.get(tool_name)
    if source_field is None:
        return None
    source = arguments.get(source_field)
    if not isinstance(source, str):
        return None
    try:
        return normalize_relative_path(source, allow_empty=False)
    except PathValidationError:
        return None


def _mutation_approval_target(tool_name: str, arguments: dict[str, Any]) -> str:
    field = _MUTATION_DISPLAY_FIELDS.get(tool_name)
    value = arguments.get(field) if field else None
    if isinstance(value, str):
        try:
            return normalize_relative_path(value, allow_empty=False)
        except PathValidationError:
            pass
    return "[document library]"


def _approval_matches(
    approval: dict[str, Any] | None,
    tool_name: str,
    arguments: dict[str, Any],
) -> bool:
    return bool(
        approval
        and approval.get("status") == "pending"
        and approval.get("name") == tool_name
        and approval.get("args") == arguments
    )


def _find_pending_approval(
    conversation: dict[str, Any],
    approval_id: str,
) -> dict[str, Any] | None:
    if not approval_id:
        return None
    for message in reversed(conversation.get("messages", [])):
        if not isinstance(message, dict):
            continue
        meta = message.get("_tool_meta")
        if not isinstance(meta, dict):
            continue
        approval = meta.get("approval")
        if (
            isinstance(approval, dict)
            and approval.get("id") == approval_id
            and approval.get("status") == "pending"
            and isinstance(meta.get("name"), str)
            and isinstance(meta.get("args"), dict)
        ):
            return {
                "id": approval_id,
                "status": "pending",
                "target": approval.get("target"),
                "reason": approval.get("reason", "unselected_resource"),
                "name": meta["name"],
                "args": meta["args"],
            }
    return None


def _set_approval_status(
    conversation: dict[str, Any],
    approval_id: str,
    status: str,
) -> dict[str, Any] | None:
    for message in reversed(conversation.get("messages", [])):
        if not isinstance(message, dict):
            continue
        meta = message.get("_tool_meta")
        if not isinstance(meta, dict):
            continue
        approval = meta.get("approval")
        if isinstance(approval, dict) and approval.get("id") == approval_id:
            approval["status"] = status
            return meta
    return None


def _approval_target_for_mutation(
    tool_name: str,
    arguments: dict[str, Any],
    *,
    documents: DocumentService,
    authorized_files: list[str],
    active_approval: dict[str, Any] | None,
) -> str | None:
    """Return an existing unselected mutation source that needs consent."""

    normalized = _mutation_source_path(tool_name, arguments)
    if normalized is None or _approval_matches(active_approval, tool_name, arguments):
        return None
    authorized = {path.casefold() for path in authorized_files if path}
    if normalized.casefold() in authorized:
        return None
    try:
        try:
            documents.read(normalized)
        except DocumentError:
            documents.list(normalized)
    except DocumentError:
        # Invalid/missing paths must reach the tool executor so callers receive
        # the real typed failure instead of an irrelevant approval prompt.
        return None
    return normalized


def _resource_binding_error(
    tool_name: str,
    arguments: dict[str, Any],
    *,
    user_message: str,
    current_file: str,
    selected_files: list[str],
) -> str | None:
    """Reject an unsafe model guess when the user referred to this turn's file.

    The provider is still free to operate on explicitly named paths.  The
    guard only resolves deictic references such as "这个" or "the current
    file", where silently falling back to a path from an older turn is unsafe.
    """

    source_field = {
        "move_item": "source",
        "delete_item": "path",
        "edit_file": "path",
        "write_file": "path",
    }.get(tool_name)
    if source_field is None or not _DEICTIC_FILE_REFERENCE.search(user_message):
        return None
    source = arguments.get(source_field)
    if not isinstance(source, str):
        return None
    try:
        normalized_source = normalize_relative_path(source, allow_empty=False)
    except PathValidationError:
        return None

    folded_message = user_message.casefold()
    source_names = {normalized_source, normalized_source.rsplit("/", 1)[-1]}
    if any(name.casefold() in folded_message for name in source_names if name):
        return None

    # A manually selected attachment is the strongest reference in this turn.
    # The current editor document is the fallback only when none was selected.
    candidates = list(dict.fromkeys(selected_files or ([current_file] if current_file else [])))
    if not candidates:
        return None
    if len(candidates) == 1 and normalized_source == candidates[0]:
        return None

    if len(candidates) == 1:
        return (
            "未执行：本轮指代的文件是 "
            f"{candidates[0]}，但工具尝试操作 {normalized_source}。"
            "请使用本轮文件路径重试，不要从较早的对话中猜测文件。"
        )
    return (
        "未执行：本轮选择了多个文件，无法安全判断“这个/当前文件”指哪一个："
        f"{', '.join(candidates)}。请先向用户确认具体文件名。"
    )


def _bounded_utf8_text(value: object, maximum_bytes: int) -> str:
    """Return valid UTF-8 text whose encoded form is no larger than the bound."""
    encoded = str(value).encode("utf-8", errors="replace")[:maximum_bytes]
    return encoded.decode("utf-8", errors="ignore")


def _canonical_json_size(value: object) -> int:
    return len(
        json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    )


def _compact_backup_info(value: object) -> dict[str, Any] | None:
    """Keep only the bounded browser rollback metadata, not the recovery record."""
    if not isinstance(value, dict):
        return None
    compact: dict[str, Any] = {}
    operation_type = value.get("type")
    if isinstance(operation_type, str):
        compact["type"] = _bounded_utf8_text(
            operation_type, TOOL_RESULT_BACKUP_TYPE_BYTES
        )
    path = next(
        (
            candidate
            for key in ("path", "target", "source")
            if isinstance((candidate := value.get(key)), str)
        ),
        None,
    )
    if path is not None:
        compact["path"] = _bounded_utf8_text(path, TOOL_RESULT_BACKUP_PATH_BYTES)
    target = value.get("target")
    if isinstance(target, str):
        compact["target"] = _bounded_utf8_text(
            target, TOOL_RESULT_BACKUP_PATH_BYTES
        )
    operation_index = value.get("operation_index")
    if (
        isinstance(operation_index, int)
        and not isinstance(operation_index, bool)
        and 0 <= operation_index <= MAX_ROLLBACK_OPERATION_INDEX
    ):
        compact["operation_index"] = operation_index
    if value.get("recovery_required") is True:
        compact["recovery_required"] = True
    return compact or None


class StreamBoundaryError(RuntimeError):
    """A stable, non-sensitive terminal error for a bounded agent stream."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.public_message = message


class _ManagedAgentStream(Iterator[tuple[str, dict[str, Any]]]):
    """Close a stream reliably, including before its generator is first pulled."""

    def __init__(
        self,
        iterator: Iterator[tuple[str, dict[str, Any]]],
        close_before_start: Callable[[], None],
    ) -> None:
        self._iterator = iterator
        self._close_before_start = close_before_start
        self._condition = threading.Condition()
        self._started = False
        self._in_next = False
        self._closed = False

    def __iter__(self) -> _ManagedAgentStream:
        return self

    def __next__(self) -> tuple[str, dict[str, Any]]:
        with self._condition:
            if self._closed:
                raise StopIteration
            self._started = True
            self._in_next = True
        try:
            return next(self._iterator)
        except BaseException:
            with self._condition:
                self._closed = True
            raise
        finally:
            with self._condition:
                self._in_next = False
                self._condition.notify_all()

    def close(self) -> None:
        with self._condition:
            while self._in_next:
                self._condition.wait()
            if self._closed:
                return
            self._closed = True
            started = self._started
        if started:
            close = getattr(self._iterator, "close", None)
            if callable(close):
                close()
        else:
            self._close_before_start()


def _metric_tool_name(tool_name: str) -> str:
    """Keep provider-controlled tool names out of Prometheus label space."""
    return tool_name if tool_name in TOOL_METRIC_NAMES else "unknown"


class AgentService:
    def __init__(
        self,
        *,
        settings: Settings,
        conversations: ConversationService,
        backup_manager: AgentBackupPort,
        journal: CommandJournalPort,
        run_journal: AgentRunJournal,
        documents: DocumentService,
        provider_stream: ProviderStreamPort | None = None,
        tool_executor: ToolExecutorPort | None = None,
        finance_mcp: FinanceMcpClient | None = None,
        credential_loader: Callable[[str], str] | None = None,
    ):
        self.settings = settings
        self.conversations = conversations
        self.backup_manager = backup_manager
        self.journal = journal
        self.run_journal = run_journal
        self.documents = documents
        self.provider_stream = provider_stream
        self.tool_executor = tool_executor
        self.finance_mcp = finance_mcp
        self.credential_loader = credential_loader
        self._active_guard = threading.Lock()
        self._active_conversations: set[str] = set()

    def stream(self, request: ChatRequest, *, request_id: str) -> _ManagedAgentStream:
        self._validate_request(request)
        api_key = (
            request.api_key.get_secret_value()
            if request.api_key
            else self.credential_loader(f"{request.provider}_api_key")
            if self.credential_loader
            else self.settings.ai_api_key.get_secret_value()
            if self.settings.ai_api_key
            else ""
        )
        if not api_key:
            raise Problem(422, "api_key_required", "AI API key required", "Provide a transient key or configure one.")

        tool_definitions = list(TOOL_DEFINITIONS)
        if self.finance_mcp is not None:
            try:
                tool_definitions.extend(self.finance_mcp.tool_definitions())
            except FinanceMcpError:
                LOGGER.error("FinanceMCP tool discovery failed")

        run_id = request.run_id or f"run_{uuid.uuid4().hex}"
        if not self.run_journal.start(
            run_id=run_id,
            request_id=request_id,
            provider=request.provider,
            model=request.model,
        ):
            raise Problem(
                409,
                "agent_run_exists",
                "Agent run already exists",
                "This run and request identifier pair has already been accepted.",
            )

        conversation: dict[str, Any] | None = None
        conversation_id: str | None = None
        created_new = False
        active_reserved = False
        appended_user_message: dict[str, Any] | None = None
        active_approval: dict[str, Any] | None = None

        def release_active() -> None:
            nonlocal active_reserved
            if not active_reserved or conversation_id is None:
                return
            with self._active_guard:
                was_active = conversation_id in self._active_conversations
                self._active_conversations.discard(conversation_id)
            active_reserved = False
            if was_active:
                OPEN_AGENT_STREAMS.dec()

        try:
            if bool(request.approval_id) != (request.approval_decision is not None):
                raise Problem(
                    422,
                    "invalid_tool_approval",
                    "Invalid tool approval",
                    "An approval identifier and decision must be provided together.",
                )
            (
                actual_content,
                stored_content,
                attachment_paths,
                current_resource,
                selected_resources,
            ) = self._prepare_content(
                request.message,
                request.context_file,
                request.attached_files,
            )
            conversation = (
                self.conversations.repository.get(request.conversation_id)
                if request.conversation_id
                else None
            )
            if request.approval_id:
                if conversation is None:
                    raise Problem(
                        409,
                        "tool_approval_unavailable",
                        "Tool approval unavailable",
                        "The pending file operation no longer exists in this conversation.",
                    )
                active_approval = _find_pending_approval(
                    conversation, request.approval_id
                )
                if active_approval is None:
                    raise Problem(
                        409,
                        "tool_approval_unavailable",
                        "Tool approval unavailable",
                        "This file-operation approval was already resolved or is no longer available.",
                    )
                if request.approval_decision == "approve":
                    approved_instruction = (
                        "\n\n<markinote_tool_approval>\n"
                        "The user approved exactly this pending file operation for this run:\n"
                        f"tool: {json.dumps(active_approval['name'], ensure_ascii=False)}\n"
                        f"arguments: {json.dumps(active_approval['args'], ensure_ascii=False, separators=(',', ':'))}\n"
                        "Retry that exact tool call now. This approval does not authorize any "
                        "different tool, path, or arguments. Do not ask the user to confirm it again.\n"
                        "</markinote_tool_approval>"
                    )
                    actual_content += approved_instruction
            created_new = conversation is None
            if not conversation:
                conversation = self.conversations.create(
                    request.message, get_system_prompt(request.language)
                )
            conversation_id = str(conversation["id"])
            if not self.run_journal.attach_conversation(run_id, request_id, conversation_id):
                raise RuntimeError("agent run could not attach its conversation")

            with self._active_guard:
                if conversation_id in self._active_conversations:
                    raise Problem(
                        409,
                        "conversation_busy",
                        "Conversation is busy",
                        "This conversation is already generating a response.",
                    )
                self._active_conversations.add(conversation_id)
                active_reserved = True
            OPEN_AGENT_STREAMS.inc()

            appended_user_message = {
                "role": "user",
                "content": stored_content,
                "_display_content": request.message,
                "_attachments": attachment_paths,
                "_context_file": current_resource or None,
            }
            conversation.setdefault("messages", []).append(appended_user_message)
            self.conversations.repository.save(conversation)
        except Exception as error:
            release_active()
            if created_new and conversation_id:
                try:
                    self.conversations.repository.delete(conversation_id)
                except Exception:
                    LOGGER.exception(
                        "failed to remove incomplete conversation",
                        extra={"request_id": request_id, "conversation_id": conversation_id},
                    )
            self._finish_run_safely(
                run_id,
                request_id,
                "failed",
                error_code=error.code if isinstance(error, Problem) else "setup_failed",
                conversation_id=conversation_id,
            )
            raise

        if conversation is None or conversation_id is None:
            # Narrow the types after the guarded setup without an unsafe cast.
            self._finish_run_safely(
                run_id,
                request_id,
                "failed",
                error_code="setup_failed",
                conversation_id=conversation_id,
            )
            release_active()
            raise RuntimeError("agent conversation setup did not complete")
        AGENT_RUNS.labels(request.provider).inc()

        def cancel_before_start() -> None:
            """Undo acceptance that never reached the first SSE iterator pull."""
            try:
                if created_new:
                    self.conversations.repository.delete(conversation_id)
                else:
                    messages = conversation.get("messages", [])
                    if messages and messages[-1] is appended_user_message:
                        messages.pop()
                        self.conversations.repository.save(conversation)
                    else:
                        LOGGER.error(
                            "agent pre-stream cancellation could not identify the appended message",
                            extra={
                                "request_id": request_id,
                                "conversation_id": conversation_id,
                            },
                        )
            except Exception:
                LOGGER.exception(
                    "failed to remove a conversation accepted by an unstarted stream",
                    extra={"request_id": request_id, "conversation_id": conversation_id},
                )
            finally:
                try:
                    self._finish_run_safely(
                        run_id,
                        request_id,
                        "cancelled",
                        error_code="client_cancelled_before_stream",
                        conversation_id=conversation_id,
                    )
                finally:
                    release_active()

        def generate() -> Iterator[tuple[str, dict[str, Any]]]:
            backup_group_id: str | None = None
            assistant_content = ""
            sequence = 0
            first_content_recorded = False
            terminal_state: TerminalAgentRunState = "failed"
            terminal_error_code: str | None = "stream_incomplete"
            stream_started = time.monotonic()
            provider_event_count = 0
            provider_byte_count = 0
            content_byte_count = 0

            def ensure_elapsed() -> None:
                if time.monotonic() - stream_started > self.settings.ai_max_stream_seconds:
                    raise StreamBoundaryError(
                        "agent_stream_timeout",
                        "AI processing exceeded the elapsed-time safety limit.",
                    )

            def event_payload(
                event_type: str,
                data: dict[str, Any],
                *,
                event_sequence: int,
            ) -> dict[str, Any]:
                return {
                    "schemaVersion": 1,
                    "runId": run_id,
                    "sequence": event_sequence,
                    "type": event_type,
                    "data": data,
                }

            def event_size(
                event_type: str,
                data: dict[str, Any],
                *,
                event_sequence: int,
            ) -> int:
                payload = event_payload(
                    event_type,
                    data,
                    event_sequence=event_sequence,
                )
                return len(
                    json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                ) + len(event_type.encode("utf-8")) + 32

            def emit(
                event_type: str,
                data: dict[str, Any],
                *,
                enforce_limit: bool = True,
            ) -> tuple[str, dict[str, Any]]:
                nonlocal sequence
                next_sequence = sequence + 1
                encoded_size = event_size(
                    event_type,
                    data,
                    event_sequence=next_sequence,
                )
                if enforce_limit and encoded_size > self.settings.ai_max_sse_event_bytes:
                    raise StreamBoundaryError(
                        "agent_sse_event_limit_exceeded",
                        "An agent stream event exceeded the response safety limit.",
                    )
                sequence = next_sequence
                payload = event_payload(
                    event_type,
                    data,
                    event_sequence=sequence,
                )
                return event_type, payload

            def admit_tool_result(
                call_id: object,
                function_name: object,
                event_arguments: dict[str, Any],
                *,
                include_approval: bool = False,
            ) -> None:
                """Reserve the exact next frame before a tool may mutate state."""
                worst_case = {
                    "call_id": call_id,
                    "name": function_name,
                    "args": event_arguments,
                    # NUL has the largest JSON representation of any one-byte
                    # UTF-8 code unit (``\\u0000``), so these placeholders are
                    # conservative for the bounded actual values below.
                    "result": "\0" * TOOL_RESULT_BYTES,
                    "backup_info": {
                        "type": "\0" * TOOL_RESULT_BACKUP_TYPE_BYTES,
                        "path": "\0" * TOOL_RESULT_BACKUP_PATH_BYTES,
                        "operation_index": MAX_ROLLBACK_OPERATION_INDEX,
                        "recovery_required": True,
                    },
                    "backup_group_id": "\0" * TOOL_RESULT_BACKUP_GROUP_BYTES,
                }
                if include_approval:
                    worst_case["approval"] = {
                        "id": "\0" * TOOL_APPROVAL_ID_BYTES,
                        "status": "pending",
                        "target": "\0" * TOOL_RESULT_BACKUP_PATH_BYTES,
                        "reason": "unselected_resource",
                    }
                    worst_case["resolved_approval_id"] = (
                        "\0" * TOOL_APPROVAL_ID_BYTES
                    )
                if (
                    event_size(
                        "tool_result",
                        worst_case,
                        event_sequence=sequence + 1,
                    )
                    > self.settings.ai_max_sse_event_bytes
                ):
                    raise StreamBoundaryError(
                        "agent_sse_event_limit_exceeded",
                        "An agent stream event exceeded the response safety limit.",
                    )

            try:
                yield emit("conversation_id", {"id": conversation_id})
                if (
                    active_approval
                    and request.approval_decision == "deny"
                    and request.approval_id
                ):
                    resolved_meta = _set_approval_status(
                        conversation, request.approval_id, "denied"
                    )
                    if resolved_meta is None:
                        raise StreamBoundaryError(
                            "tool_approval_unavailable",
                            "The pending file operation is no longer available.",
                        )
                    denial_result = "用户已拒绝该文件操作；文件未被修改。"
                    denial_event = {
                        "call_id": resolved_meta.get("call_id", ""),
                        "name": resolved_meta.get("name", ""),
                        "args": resolved_meta.get("args", {}),
                        "result": denial_result,
                        "backup_info": None,
                        "backup_group_id": None,
                        "approval": {
                            "id": request.approval_id,
                            "status": "denied",
                            "target": active_approval.get("target", ""),
                            "reason": active_approval.get("reason", "unselected_resource"),
                        },
                        "resolved_approval_id": request.approval_id,
                    }
                    self.conversations.repository.save(conversation)
                    yield emit("tool_result", denial_event)
                    terminal_state = "completed"
                    terminal_error_code = None
                    yield emit("done", {"conversation_id": conversation_id})
                    return
                messages_for_api = strip_messages_for_api(conversation["messages"])
                messages_for_api[0]["content"] = get_system_prompt(request.language)
                messages_for_api[-1]["content"] = actual_content
                total_tool_calls = 0
                run_failed = False
                approval_requested = False
                external_content_observed = False

                for _ in range(MAX_TOOL_ITERATIONS):
                    ensure_elapsed()
                    if backup_group_id:
                        self.backup_manager.heartbeat_operation_group(backup_group_id)
                    assistant_content = ""
                    tool_calls_map: dict[int, dict[str, Any]] = {}
                    provider_failed = False
                    provider_terminal: str | None = None
                    content_bytes_this_round = 0
                    tool_argument_bytes: dict[int, int] = {}
                    trimmed = trim_messages_for_api(messages_for_api, self.settings.max_context_chars)
                    if self.provider_stream is None:
                        provider_events = stream_chat_completion(
                            trimmed,
                            tool_definitions,
                            api_key,
                            request.provider,
                            request.model,
                            max_frame_bytes=self.settings.ai_max_provider_frame_bytes,
                            max_events=self.settings.ai_max_provider_events,
                            max_total_bytes=self.settings.ai_max_provider_bytes,
                            max_elapsed_seconds=self.settings.ai_max_stream_seconds,
                        )
                    else:
                        provider_events = self.provider_stream(
                            trimmed,
                            tool_definitions,
                            api_key,
                            request.provider,
                            request.model,
                        )
                    for provider_event in provider_events:
                        ensure_elapsed()
                        provider_event_count += 1
                        provider_byte_count += len(
                            json.dumps(
                                provider_event,
                                ensure_ascii=False,
                                separators=(",", ":"),
                            ).encode("utf-8")
                        )
                        if provider_event_count > self.settings.ai_max_provider_events:
                            raise StreamBoundaryError(
                                "provider_event_limit_exceeded",
                                "AI provider stream exceeded the event safety limit.",
                            )
                        if provider_byte_count > self.settings.ai_max_provider_bytes:
                            raise StreamBoundaryError(
                                "provider_byte_limit_exceeded",
                                "AI provider stream exceeded the byte safety limit.",
                            )
                        event_type = provider_event["type"]
                        if event_type == "content":
                            content = provider_event["content"]
                            if not isinstance(content, str):
                                raise StreamBoundaryError(
                                    "provider_stream_contract_error",
                                    "AI provider returned an invalid stream event.",
                                )
                            content_size = len(content.encode("utf-8"))
                            if (
                                content_bytes_this_round + content_size
                                > self.settings.ai_max_content_bytes_per_round
                            ):
                                raise StreamBoundaryError(
                                    "provider_content_round_limit_exceeded",
                                    "AI provider content exceeded the per-round safety limit.",
                                )
                            if content_byte_count + content_size > self.settings.ai_max_content_bytes_total:
                                raise StreamBoundaryError(
                                    "provider_content_total_limit_exceeded",
                                    "AI provider content exceeded the total safety limit.",
                                )
                            content_bytes_this_round += content_size
                            content_byte_count += content_size
                            if provider_event["content"] and not first_content_recorded:
                                first_content_recorded = self._mark_first_content_safely(
                                    run_id,
                                    request_id,
                                    conversation_id=conversation_id,
                                )
                            assistant_content += provider_event["content"]
                            yield emit("token", {"content": provider_event["content"]})
                        elif event_type == "tool_call_start":
                            tool_argument_bytes[provider_event["index"]] = 0
                            tool_calls_map[provider_event["index"]] = {
                                "id": provider_event["id"],
                                "type": "function",
                                "function": {"name": provider_event["name"], "arguments": ""},
                            }
                            yield emit(
                                "tool_call",
                                {
                                    "call_id": provider_event["id"],
                                    "name": provider_event["name"],
                                    "args": {},
                                },
                            )
                        elif event_type == "tool_call_args" and provider_event["index"] in tool_calls_map:
                            arguments_fragment = provider_event["arguments"]
                            if not isinstance(arguments_fragment, str):
                                raise StreamBoundaryError(
                                    "provider_stream_contract_error",
                                    "AI provider returned an invalid stream event.",
                                )
                            argument_size = len(arguments_fragment.encode("utf-8"))
                            argument_total = tool_argument_bytes.get(provider_event["index"], 0) + argument_size
                            if argument_total > self.settings.ai_max_tool_arguments_bytes:
                                raise StreamBoundaryError(
                                    "tool_arguments_limit_exceeded",
                                    "AI tool arguments exceeded the safety limit.",
                                )
                            tool_argument_bytes[provider_event["index"]] = argument_total
                            tool_calls_map[provider_event["index"]]["function"]["arguments"] += arguments_fragment
                        elif event_type == "error":
                            provider_failed = True
                            provider_terminal = "error"
                            raw_provider_code = provider_event.get("code")
                            provider_code = raw_provider_code if isinstance(raw_provider_code, str) else ""
                            if provider_code in PROVIDER_BOUNDARY_ERROR_CODES:
                                terminal_error_code = provider_code
                                provider_message = PROVIDER_BOUNDARY_ERROR_MESSAGES[provider_code]
                            else:
                                terminal_error_code = "provider_error"
                                provider_message = "AI provider request failed."
                            yield emit(
                                "error",
                                {"code": terminal_error_code, "message": provider_message},
                            )
                            break
                        elif event_type in {"done", "tool_calls_complete"}:
                            provider_terminal = event_type
                            break

                    if provider_terminal is None:
                        provider_failed = True
                        terminal_error_code = "provider_stream_incomplete"
                        yield emit(
                            "error",
                            {
                                "code": terminal_error_code,
                                "message": "AI provider stream ended before a terminal event.",
                            },
                        )

                    if provider_failed:
                        if append_partial_assistant(conversation, assistant_content):
                            self.conversations.repository.save(conversation)
                        run_failed = True
                        if terminal_error_code not in {
                            "provider_stream_incomplete",
                            *PROVIDER_BOUNDARY_ERROR_CODES,
                        }:
                            terminal_error_code = "provider_error"
                        break

                    tool_calls = [tool_calls_map[index] for index in sorted(tool_calls_map)]
                    assistant_message_for_provider: dict[str, Any] = {
                        "role": "assistant",
                        "content": assistant_content or "",
                    }
                    if tool_calls:
                        assistant_message_for_provider["tool_calls"] = tool_calls
                    messages_for_api.append(
                        strip_messages_for_api([assistant_message_for_provider])[0]
                    )
                    persisted_tool_calls = []
                    for tool_call in tool_calls:
                        function = tool_call["function"]
                        persisted_tool_calls.append(
                            {
                                **tool_call,
                                "function": {
                                    **function,
                                    "arguments": sanitize_tool_call_arguments_for_persistence(
                                        function["name"],
                                        function["arguments"],
                                    ),
                                },
                            }
                        )
                    assistant_message: dict[str, Any] = {
                        "role": "assistant",
                        "content": assistant_content or "",
                    }
                    if persisted_tool_calls:
                        assistant_message["tool_calls"] = persisted_tool_calls
                    conversation["messages"].append(assistant_message)
                    if not tool_calls:
                        break

                    approval_targets: dict[str, str] = {}
                    approval_reasons: dict[str, str] = {}
                    round_has_external_content = any(
                        candidate["function"]["name"] in UNTRUSTED_EXTERNAL_CONTENT_TOOLS
                        for candidate in tool_calls
                    )
                    external_guard_active = (
                        external_content_observed or round_has_external_content
                    )
                    if request.allow_write_tools:
                        for candidate in tool_calls:
                            try:
                                candidate_arguments = json.loads(
                                    candidate["function"]["arguments"]
                                )
                            except (json.JSONDecodeError, TypeError):
                                continue
                            if not isinstance(candidate_arguments, dict):
                                continue
                            candidate_target = _approval_target_for_mutation(
                                candidate["function"]["name"],
                                candidate_arguments,
                                documents=self.documents,
                                authorized_files=[
                                    current_resource,
                                    *selected_resources,
                                ],
                                active_approval=active_approval,
                            )
                            candidate_name = candidate["function"]["name"]
                            approval_mismatch = bool(
                                active_approval
                                and candidate_name in MUTATING_TOOLS
                                and not _approval_matches(
                                    active_approval,
                                    candidate_name,
                                    candidate_arguments,
                                )
                            )
                            if (
                                (external_guard_active or approval_mismatch)
                                and candidate_name in MUTATING_TOOLS
                                and not _approval_matches(
                                    active_approval,
                                    candidate_name,
                                    candidate_arguments,
                                )
                            ):
                                approval_targets[candidate["id"]] = (
                                    candidate_target
                                    or _mutation_approval_target(
                                        candidate_name,
                                        candidate_arguments,
                                    )
                                )
                                approval_reasons[candidate["id"]] = (
                                    str(active_approval.get("reason", "unselected_resource"))
                                    if approval_mismatch and active_approval
                                    else "external_content"
                                )
                            elif candidate_target:
                                approval_targets[candidate["id"]] = candidate_target
                                approval_reasons[candidate["id"]] = "unselected_resource"

                    for call in tool_calls:
                        total_tool_calls += 1
                        function_name = call["function"]["name"]
                        if function_name in UNTRUSTED_EXTERNAL_CONTENT_TOOLS:
                            external_content_observed = True
                        metric_tool_name = _metric_tool_name(function_name)
                        command_backup_group_id: str | None = None
                        is_finance_tool = False
                        approval_data: dict[str, Any] | None = None
                        resolved_approval_id: str | None = None
                        try:
                            arguments = json.loads(call["function"]["arguments"])
                            if not isinstance(arguments, dict):
                                raise ValueError
                        except (json.JSONDecodeError, ValueError):
                            arguments = {}
                            event_arguments: dict[str, Any] = {}
                            admit_tool_result(
                                call["id"], function_name, event_arguments
                            )
                            result, backup_info = "Tool arguments are not a valid JSON object.", None
                        else:
                            is_finance_tool = bool(
                                self.finance_mcp is not None
                                and self.finance_mcp.is_tool(function_name)
                            )
                            event_arguments = sanitize_tool_arguments_for_persistence(
                                function_name,
                                arguments,
                            )
                            if (
                                _canonical_json_size(event_arguments)
                                > self.settings.ai_max_tool_arguments_bytes
                            ):
                                raise StreamBoundaryError(
                                    "tool_arguments_limit_exceeded",
                                    "AI tool arguments exceeded the safety limit.",
                                )
                            # The provider's compact JSON can expand after
                            # parsing (for example 1e15 -> 1000000000000000.0).
                            # Admit the real canonical args and identifiers,
                            # plus a worst-case bounded result/rollback record,
                            # before a command is claimed or executed.
                            admit_tool_result(
                                call["id"],
                                function_name,
                                event_arguments,
                                include_approval=(
                                    call["id"] in approval_targets
                                    or _approval_matches(
                                        active_approval,
                                        function_name,
                                        arguments,
                                    )
                                ),
                            )
                            command_id = stable_command_id(
                                run_id,
                                call["id"],
                                function_name,
                                arguments,
                                conversation_id=conversation_id,
                            )
                            claimed, previous = self.journal.claim(
                                command_id,
                                run_id=run_id,
                                conversation_id=conversation_id,
                                tool_name=function_name,
                            )
                            recovered_command = (
                                self.backup_manager.find_command(command_id)
                                if claimed and function_name in MUTATING_TOOLS
                                else None
                            )
                            if not claimed:
                                if previous:
                                    result = str(previous.get("result", "Command already completed."))
                                    backup_info = previous.get("backup_info")
                                    previous_group_id = previous.get("backup_group_id")
                                    if isinstance(previous_group_id, str) and previous_group_id:
                                        command_backup_group_id = previous_group_id
                                else:
                                    result, backup_info = "Command is already in progress.", None
                                TOOL_COMMANDS.labels(metric_tool_name, "duplicate").inc()
                            elif recovered_command and recovered_command.get("state") != "compensated":
                                command_backup_group_id = str(
                                    recovered_command.get("backup_group_id") or ""
                                ) or None
                                recovered_info = recovered_command.get("backup_info")
                                backup_info = (
                                    dict(recovered_info) if isinstance(recovered_info, dict) else None
                                )
                                recovered_state = str(recovered_command.get("state") or "prepared")
                                if recovered_state in {"prepared", "applied"} and recovered_command.get(
                                    "backup_lease_active"
                                ):
                                    # The command-journal lease expired first, but the worker's
                                    # longer backup lease is still live. Do not execute or mark
                                    # the command terminal: the fenced owner will either commit
                                    # unsuccessfully and compensate, or its backup lease expires.
                                    result = (
                                        "The previous command attempt is still within its recovery lease; "
                                        "automatic replay was deferred."
                                    )
                                    backup_info = None
                                    command_backup_group_id = None
                                    TOOL_COMMANDS.labels(metric_tool_name, "reconciliation_pending").inc()
                                elif recovered_state in {"applied", "committed"}:
                                    result = str(recovered_command.get("result") or "Command already applied.")
                                    try:
                                        reconciled = self.journal.complete(
                                            command_id,
                                            {
                                                "result": result[:5000],
                                                "backup_info": backup_info,
                                                "backup_group_id": command_backup_group_id,
                                            },
                                        )
                                        if not reconciled:
                                            raise RuntimeError("command lease was lost during reconciliation")
                                    except Exception:
                                        # The durable manifest remains an idempotency fence;
                                        # a later lease takeover will reconcile it again.
                                        LOGGER.exception(
                                            "failed to reconcile applied command into journal",
                                            extra={
                                                "request_id": request_id,
                                                "conversation_id": conversation_id,
                                                "command_id": command_id,
                                            },
                                        )
                                    TOOL_COMMANDS.labels(metric_tool_name, "recovered").inc()
                                else:
                                    if backup_info is None:
                                        backup_info = {}
                                    backup_info["recovery_required"] = True
                                    result = (
                                        "A previous worker stopped during this mutation; "
                                        "automatic replay was refused and recovery is required."
                                    )
                                    try:
                                        self.journal.fail(
                                            command_id,
                                            {
                                                "result": result,
                                                "backup_info": backup_info,
                                                "backup_group_id": command_backup_group_id,
                                            },
                                        )
                                    except Exception:
                                        LOGGER.exception(
                                            "failed to persist prepared-command recovery state",
                                            extra={
                                                "request_id": request_id,
                                                "conversation_id": conversation_id,
                                                "command_id": command_id,
                                            },
                                        )
                                    TOOL_COMMANDS.labels(metric_tool_name, "recovery_required").inc()
                            elif total_tool_calls > MAX_TOTAL_TOOL_CALLS:
                                result, backup_info = "Tool call safety limit exceeded.", None
                                self.journal.fail(command_id, {"result": result})
                                TOOL_COMMANDS.labels(metric_tool_name, "limited").inc()
                            elif function_name in MUTATING_TOOLS and not request.allow_write_tools:
                                result, backup_info = (
                                    "未执行：该操作会修改文件。请开启本次文档写权限后重试。",
                                    None,
                                )
                                self.journal.fail(command_id, {"result": result})
                                TOOL_COMMANDS.labels(metric_tool_name, "denied").inc()
                            elif approval_target := approval_targets.get(call["id"]):
                                approval_reason = approval_reasons.get(
                                    call["id"], "unselected_resource"
                                )
                                approval_data = {
                                    "id": uuid.uuid4().hex,
                                    "status": "pending",
                                    "target": approval_target,
                                    "reason": approval_reason,
                                }
                                if approval_reason == "external_content":
                                    result = (
                                        "等待用户确认：本轮使用了外部不可信网页内容。"
                                        "为防止间接提示注入，请确认后仅执行这一次明确的文件操作。"
                                    )
                                else:
                                    result = (
                                        "等待用户确认：该文件不在当前文档或本轮附件中，"
                                        "确认后仅执行这一次明确的文件操作。"
                                    )
                                backup_info = None
                                approval_requested = True
                                self.journal.fail(command_id, {"result": result})
                                TOOL_COMMANDS.labels(
                                    metric_tool_name, "approval_required"
                                ).inc()
                            elif (
                                approval_targets
                                and active_approval is None
                                and function_name in MUTATING_TOOLS
                            ):
                                result, backup_info = (
                                    "未执行：同一批操作中有文件需要用户确认，"
                                    "为避免只完成部分修改，本次写操作已暂停。",
                                    None,
                                )
                                self.journal.fail(command_id, {"result": result})
                                TOOL_COMMANDS.labels(
                                    metric_tool_name, "approval_blocked"
                                ).inc()
                            elif binding_error := _resource_binding_error(
                                function_name,
                                arguments,
                                user_message=request.message,
                                current_file=current_resource,
                                selected_files=selected_resources,
                            ):
                                result, backup_info = binding_error, None
                                self.journal.fail(command_id, {"result": result})
                                TOOL_COMMANDS.labels(metric_tool_name, "denied").inc()
                            else:
                                if function_name in MUTATING_TOOLS and not backup_group_id:
                                    backup_group_id = self.backup_manager.create_operation_group(conversation_id)
                                if is_finance_tool and self.finance_mcp is not None:
                                    try:
                                        result = self.finance_mcp.call_tool(
                                            function_name,
                                            arguments,
                                            tushare_token=(
                                                self.credential_loader("tushare_token")
                                                if self.credential_loader
                                                else ""
                                            ),
                                            qveris_api_key=(
                                                self.credential_loader("qveris_api_key")
                                                if self.credential_loader
                                                else ""
                                            ),
                                        )
                                    except FinanceMcpError as error:
                                        result = str(error)
                                    backup_info = None
                                else:
                                    result, backup_info = (self.tool_executor or execute_tool)(
                                        function_name,
                                        arguments,
                                        str(self.settings.library_folder),
                                        self.backup_manager,
                                        backup_group_id,
                                        api_key=api_key,
                                        provider_id=request.provider,
                                        model_id=request.model,
                                        document_service=self.documents,
                                        command_id=command_id,
                                    )
                                if backup_info:
                                    command_backup_group_id = backup_group_id
                                command_outcome = "completed"
                                try:
                                    operation_index = (
                                        backup_info.get("operation_index")
                                        if isinstance(backup_info, dict)
                                        else None
                                    )
                                    if (
                                        command_backup_group_id
                                        and isinstance(backup_info, dict)
                                        and isinstance(operation_index, int)
                                        and not isinstance(operation_index, bool)
                                    ):
                                        self.backup_manager.record_command_result(
                                            command_backup_group_id,
                                            operation_index,
                                            command_id,
                                            result,
                                            backup_info,
                                        )
                                    command_payload = {
                                        "result": result[:5000],
                                        "backup_info": backup_info,
                                        "backup_group_id": command_backup_group_id,
                                    }
                                    committed = self.journal.complete(command_id, command_payload)
                                    if not committed:
                                        durable_command = self.journal.inspect(command_id)
                                        durable_result = (
                                            durable_command.get("result")
                                            if isinstance(durable_command, dict)
                                            else None
                                        )
                                        terminal_matches = (
                                            isinstance(durable_command, dict)
                                            and durable_command.get("state") == "completed"
                                            and isinstance(durable_result, dict)
                                            and (
                                                (
                                                    bool(command_backup_group_id)
                                                    and durable_result.get("backup_group_id")
                                                    == command_backup_group_id
                                                    and isinstance(
                                                        durable_result.get("backup_info"), dict
                                                    )
                                                    and durable_result["backup_info"].get(
                                                        "operation_index"
                                                    )
                                                    == operation_index
                                                )
                                                or (
                                                    not command_backup_group_id
                                                    and durable_result == command_payload
                                                )
                                            )
                                        )
                                        if not terminal_matches:
                                            raise RuntimeError("command lease was lost before result commit")
                                except Exception:
                                    LOGGER.exception(
                                        "tool command commit failed; compensating applied mutation",
                                        extra={
                                            "request_id": request_id,
                                            "conversation_id": conversation_id,
                                            "command_id": command_id,
                                        },
                                    )
                                    command_outcome = "commit_failed"
                                    compensated = backup_info is None
                                    operation_index = (
                                        backup_info.get("operation_index")
                                        if isinstance(backup_info, dict)
                                        else None
                                    )
                                    if (
                                        command_backup_group_id
                                        and isinstance(backup_info, dict)
                                        and isinstance(operation_index, int)
                                        and not isinstance(operation_index, bool)
                                    ):
                                        try:
                                            compensated, _ = (
                                                self.backup_manager.compensate_active_operation(
                                                    command_backup_group_id,
                                                    operation_index,
                                                    observed_path=str(
                                                        backup_info.get("target")
                                                        or backup_info.get("path")
                                                        or arguments.get("path")
                                                        or arguments.get("source")
                                                        or ""
                                                    ),
                                                    require_after_match=True,
                                                )
                                            )
                                        except Exception:
                                            compensated = False
                                            LOGGER.exception(
                                                "tool command compensation failed",
                                                extra={
                                                    "request_id": request_id,
                                                    "conversation_id": conversation_id,
                                                    "command_id": command_id,
                                                },
                                            )

                                    if compensated:
                                        result = (
                                            "Command result could not be committed; "
                                            "the mutation was restored."
                                        )
                                        backup_info = None
                                        command_backup_group_id = None
                                    else:
                                        recovery_info = dict(backup_info or {})
                                        recovery_info["recovery_required"] = True
                                        backup_info = recovery_info
                                        result = (
                                            "Command commit and automatic compensation failed; "
                                            "recovery is required."
                                        )
                                    try:
                                        failure_recorded = self.journal.fail(
                                            command_id,
                                            {
                                                "result": result[:5000],
                                                "backup_info": backup_info,
                                                "backup_group_id": command_backup_group_id,
                                            },
                                        )
                                        if not failure_recorded:
                                            LOGGER.warning(
                                                "command failure result was fenced by a newer lease owner",
                                                extra={
                                                    "request_id": request_id,
                                                    "conversation_id": conversation_id,
                                                    "command_id": command_id,
                                                },
                                            )
                                    except Exception:
                                        # If the journal is unavailable, an expired lease may
                                        # retry only after successful compensation made it safe.
                                        LOGGER.exception(
                                            "failed to persist compensated command state",
                                            extra={
                                                "request_id": request_id,
                                                "conversation_id": conversation_id,
                                                "command_id": command_id,
                                            },
                                        )
                                else:
                                    if (
                                        command_backup_group_id
                                        and isinstance(operation_index, int)
                                        and not isinstance(operation_index, bool)
                                    ):
                                        try:
                                            self.backup_manager.mark_command_committed(
                                                command_backup_group_id,
                                                operation_index,
                                                command_id,
                                            )
                                        except Exception:
                                            # The journal is authoritative once committed. The
                                            # manifest marker is only crash reconciliation data.
                                            LOGGER.exception(
                                                "failed to mirror committed command state to backup manifest",
                                                extra={
                                                    "request_id": request_id,
                                                    "conversation_id": conversation_id,
                                                    "command_id": command_id,
                                                },
                                            )

                                try:
                                    self.journal.audit(
                                        request_id=request_id,
                                        conversation_id=conversation_id,
                                        command_id=command_id,
                                        action=function_name,
                                        target=str(arguments.get("path") or arguments.get("source") or "")[:1024]
                                        or None,
                                        outcome=command_outcome,
                                        details={
                                            "has_backup": bool(backup_info),
                                            "recovery_required": bool(
                                                isinstance(backup_info, dict)
                                                and backup_info.get("recovery_required")
                                            ),
                                        },
                                    )
                                except Exception:
                                    LOGGER.exception(
                                        "failed to append tool command audit record",
                                        extra={
                                            "request_id": request_id,
                                            "conversation_id": conversation_id,
                                            "command_id": command_id,
                                        },
                                    )
                                TOOL_COMMANDS.labels(metric_tool_name, command_outcome).inc()

                        if (
                            backup_info
                            and active_approval
                            and _approval_matches(
                                active_approval, function_name, arguments
                            )
                        ):
                            approval_id = str(active_approval["id"])
                            if _set_approval_status(
                                conversation, approval_id, "approved"
                            ):
                                resolved_approval_id = approval_id
                        event_backup_info = _compact_backup_info(backup_info)
                        event_backup_group_id = (
                            command_backup_group_id
                            if event_backup_info
                            and "operation_index" in event_backup_info
                            and isinstance(command_backup_group_id, str)
                            and len(command_backup_group_id.encode("utf-8"))
                            <= TOOL_RESULT_BACKUP_GROUP_BYTES
                            else None
                        )
                        if event_backup_info and command_backup_group_id and not event_backup_group_id:
                            event_backup_info["recovery_required"] = True
                        event_data = {
                            "call_id": call["id"],
                            "name": function_name,
                            "args": event_arguments,
                            "result": _bounded_utf8_text(result, TOOL_RESULT_BYTES),
                            "backup_info": event_backup_info,
                            # A group alone is insufficient: only the command
                            # that actually produced a snapshot is rollbackable.
                            "backup_group_id": event_backup_group_id,
                        }
                        if approval_data:
                            event_data["approval"] = approval_data
                        if resolved_approval_id:
                            event_data["resolved_approval_id"] = (
                                resolved_approval_id
                            )
                        provider_tool_result = result if is_finance_tool else result[:5000]
                        tool_message = {
                            "role": "tool",
                            "tool_call_id": call["id"],
                            "content": provider_tool_result,
                            "_tool_meta": event_data,
                        }
                        conversation["messages"].append(tool_message)
                        messages_for_api.append(
                            {"role": "tool", "tool_call_id": call["id"], "content": provider_tool_result}
                        )
                        # The durable rollback handle is committed before it is
                        # exposed. A disconnect immediately after tool_result
                        # must not leave an applied mutation undiscoverable.
                        self.conversations.repository.save(conversation)
                        yield emit("tool_result", event_data)
                    self.conversations.repository.save(conversation)
                    if approval_requested:
                        break
                else:
                    run_failed = True
                    terminal_error_code = "tool_iteration_limit"
                    yield emit(
                        "error",
                        {
                            "code": terminal_error_code,
                            "message": "Agent stopped after reaching the tool-iteration safety limit.",
                        },
                    )

                if run_failed:
                    return

                ensure_elapsed()

                user_count = sum(
                    1 for message in conversation["messages"] if message.get("role") == "user"
                )
                if self.settings.ai_generate_titles and user_count == 1:
                    title = generate_conversation_title(
                        request.message,
                        assistant_content,
                        api_key,
                        request.provider,
                        request.model,
                        request.language,
                    )
                    # Title generation is a blocking provider request and is
                    # part of the same bounded user-visible run.
                    ensure_elapsed()
                    if title:
                        conversation["title"] = title
                        yield emit("title_generated", {"title": title})
                self.conversations.repository.save(conversation)
                terminal_state = "completed"
                terminal_error_code = None
                yield emit("done", {"conversation_id": conversation_id})
            except (GeneratorExit, asyncio.CancelledError):
                if terminal_state != "completed":
                    terminal_state = "cancelled"
                    terminal_error_code = "client_cancelled"
                append_partial_assistant(conversation, assistant_content)
                self.conversations.repository.save(conversation)
                raise
            except StreamBoundaryError as error:
                terminal_state = "failed"
                terminal_error_code = error.code
                LOGGER.warning(
                    "agent stream safety limit reached",
                    extra={
                        "request_id": request_id,
                        "conversation_id": conversation_id,
                        "error_code": error.code,
                    },
                )
                append_partial_assistant(conversation, assistant_content)
                self.conversations.repository.save(conversation)
                yield emit(
                    "error",
                    {"code": error.code, "message": error.public_message},
                    enforce_limit=False,
                )
            except Exception:
                terminal_state = "failed"
                terminal_error_code = "internal_error"
                LOGGER.exception(
                    "agent stream failed",
                    extra={"request_id": request_id, "conversation_id": conversation_id},
                )
                append_partial_assistant(conversation, assistant_content)
                self.conversations.repository.save(conversation)
                yield emit(
                    "error",
                    {
                        "code": terminal_error_code,
                        "message": "AI processing failed. See the correlated server log.",
                    },
                    enforce_limit=False,
                )
            finally:
                try:
                    try:
                        if backup_group_id:
                            try:
                                self.backup_manager.complete_operation_group(backup_group_id)
                            except Exception:
                                LOGGER.exception(
                                    "failed to finalize agent backup group",
                                    extra={
                                        "request_id": request_id,
                                        "conversation_id": conversation_id,
                                        "backup_group_id": backup_group_id,
                                    },
                                )
                            try:
                                self.backup_manager.cleanup()
                            except Exception:
                                LOGGER.exception(
                                    "failed to enforce agent backup retention",
                                    extra={
                                        "request_id": request_id,
                                        "conversation_id": conversation_id,
                                        "backup_group_id": backup_group_id,
                                    },
                                )
                    finally:
                        self._finish_run_safely(
                            run_id,
                            request_id,
                            terminal_state,
                            error_code=terminal_error_code,
                            conversation_id=conversation_id,
                        )
                finally:
                    release_active()

        return _ManagedAgentStream(generate(), cancel_before_start)

    def _mark_first_content_safely(
        self,
        run_id: str,
        request_id: str,
        *,
        conversation_id: str,
    ) -> bool:
        try:
            recorded = self.run_journal.mark_first_content(run_id, request_id)
        except Exception:
            LOGGER.exception(
                "failed to persist agent first-content timestamp",
                extra={
                    "request_id": request_id,
                    "conversation_id": conversation_id,
                    "run_id": run_id,
                },
            )
            return False
        if not recorded:
            LOGGER.warning(
                "agent first-content timestamp was fenced by terminal state",
                extra={
                    "request_id": request_id,
                    "conversation_id": conversation_id,
                    "run_id": run_id,
                },
            )
        return recorded

    def _finish_run_safely(
        self,
        run_id: str,
        request_id: str,
        state: TerminalAgentRunState,
        *,
        error_code: str | None,
        conversation_id: str | None,
    ) -> None:
        try:
            finished = self.run_journal.finish(
                run_id,
                request_id,
                state,
                error_code=error_code,
            )
        except Exception:
            # A durable running row is preferable to fabricating completion;
            # operations can identify and reconcile it after an outage.
            LOGGER.exception(
                "failed to persist terminal agent run state",
                extra={
                    "request_id": request_id,
                    "conversation_id": conversation_id,
                    "run_id": run_id,
                    "agent_run_state": state,
                },
            )
            return
        if not finished:
            LOGGER.warning(
                "terminal agent run update was rejected",
                extra={
                    "request_id": request_id,
                    "conversation_id": conversation_id,
                    "run_id": run_id,
                    "agent_run_state": state,
                },
            )

    def is_active(self, conversation_id: str) -> bool:
        with self._active_guard:
            return conversation_id in self._active_conversations

    @contextmanager
    def exclusive_conversation(self, conversation_id: str) -> Iterator[None]:
        """Serialize chat streams and destructive conversation commands."""
        with self._active_guard:
            if conversation_id in self._active_conversations:
                raise Problem(
                    409,
                    "conversation_busy",
                    "Conversation is busy",
                    "Wait for the active stream or conversation operation to finish.",
                )
            self._active_conversations.add(conversation_id)
        try:
            yield
        finally:
            with self._active_guard:
                self._active_conversations.discard(conversation_id)

    def _validate_request(self, request: ChatRequest) -> None:
        provider = PROVIDERS.get(request.provider)
        if not provider:
            raise Problem(422, "unknown_ai_provider", "Unknown AI provider", "Select a supported provider.")
        models: object = provider.get("models")
        valid_models = (
            {str(model["id"]) for model in models if isinstance(model, dict) and "id" in model}
            if isinstance(models, list)
            else set()
        )
        if request.model not in valid_models:
            raise Problem(422, "invalid_ai_model", "Invalid AI model", "The model does not belong to the provider.")
        if len(request.attached_files) > self.settings.max_attachment_files:
            raise Problem(422, "attachment_limit", "Too many attachments", "Attachment count exceeds the limit.")

    def _prepare_content(
        self,
        message: str,
        context_file: str,
        attached_files: list[str],
    ) -> tuple[str, str, list[str], str, list[str]]:
        total_bytes = 0
        selected_labels: list[str] = []
        current_label = ""
        loaded_documents: list[tuple[str, str]] = []
        seen: set[str] = set()

        for role, relative_path in [
            ("current", context_file),
            *(("selected", value) for value in attached_files),
        ]:
            if not relative_path:
                continue
            try:
                normalized = normalize_relative_path(relative_path, allow_empty=False)
                document = self.documents.read(normalized)
            except (PathValidationError, DocumentError) as error:
                raise Problem(
                    400,
                    "invalid_attachment",
                    "Invalid attachment",
                    "The attachment is unavailable or outside the document library.",
                ) from error
            if role == "current":
                current_label = normalized
            elif normalized not in selected_labels:
                selected_labels.append(normalized)
            if normalized in seen:
                continue
            seen.add(normalized)
            if len(seen) > self.settings.max_attachment_files:
                raise Problem(
                    422,
                    "attachment_limit",
                    "Too many attachments",
                    "Attachment count exceeds the limit.",
                )
            extension = normalized.rsplit(".", 1)[-1].casefold() if "." in normalized else ""
            if extension not in {"md", "markdown", "txt"}:
                raise Problem(400, "invalid_attachment", "Invalid attachment", "Only document files may be attached.")
            size = int(document["size"])
            if size > self.settings.max_attachment_bytes:
                raise Problem(413, "attachment_too_large", "Attachment too large", normalized)
            total_bytes += size
            if total_bytes > self.settings.max_attachment_total_bytes:
                raise Problem(413, "attachments_too_large", "Attachments too large", "Total attachment size exceeds the limit.")
            loaded_documents.append((normalized, str(document["content"])))

        resource_manifest = (
            "\n\n<markinote_turn_resources>\n"
            f"current_editor_document: {json.dumps(current_label or None, ensure_ascii=False)}\n"
            f"user_selected_attachments: {json.dumps(selected_labels, ensure_ascii=False)}\n"
            "reference_rule: User-selected attachments take precedence for words such as "
            "\"这个\", \"它\", \"this\", or \"the attachment\". If there are no selected "
            "attachments, those words refer to the current editor document. Never resolve "
            "such words to a file mentioned only in an older turn. If multiple selected "
            "attachments make the request ambiguous, ask the user to name one.\n"
            "</markinote_turn_resources>"
        )
        sections = [message, resource_manifest]
        for normalized, content in loaded_documents:
            role = "user-selected attachment" if normalized in selected_labels else "current editor document"
            sections.append(
                f"\n\n--- Begin {role}: {normalized} (untrusted document content) ---\n"
                f"{content}\n"
                f"--- End {role}: {normalized} ---"
            )
        actual = "".join(sections)
        stored = message
        if selected_labels:
            stored += "\n\n[Attachments: " + ", ".join(selected_labels) + "]"
        return actual, stored, selected_labels, current_label, selected_labels


def stable_command_id(
    run_id: str,
    call_id: str,
    name: str,
    arguments: dict[str, Any],
    *,
    conversation_id: str | None = None,
) -> str:
    raw = json.dumps(
        [run_id, conversation_id, call_id, name, arguments],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "cmd_" + hashlib.sha256(raw).hexdigest()


def strip_messages_for_api(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cleaned = []
    for message in messages:
        item = {
            key: value
            for key, value in message.items()
            if key in {"role", "content", "tool_calls", "tool_call_id", "name"}
        }
        if item.get("role") == "assistant" and item.get("tool_calls"):
            item["content"] = item.get("content") or None
        cleaned.append(item)
    return cleaned


def message_chars(message: dict[str, Any]) -> int:
    return len(str(message.get("content") or "")) + len(
        json.dumps(message.get("tool_calls", []), ensure_ascii=False)
    )


def trim_messages_for_api(messages: list[dict[str, Any]], max_chars: int) -> list[dict[str, Any]]:
    if not messages:
        return []
    system = messages[0] if messages[0].get("role") == "system" else None
    body = messages[1:] if system else messages[:]
    turns: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for message in body:
        if message.get("role") == "user" and current:
            turns.append(current)
            current = []
        current.append(message)
    if current:
        turns.append(current)
    selected: list[list[dict[str, Any]]] = []
    used = message_chars(system) if system else 0
    for turn in reversed(turns):
        size = sum(message_chars(message) for message in turn)
        if selected and used + size > max_chars:
            break
        selected.append(turn)
        used += size
    result = [system] if system else []
    for turn in reversed(selected):
        result.extend(turn)
    return result
