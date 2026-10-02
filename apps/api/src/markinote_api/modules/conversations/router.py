"""Typed conversation HTTP adapter."""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, ConfigDict, Field

from markinote_api.modules.agent.service import AgentService
from markinote_api.modules.conversations.service import ConversationService
from markinote_api.platform.errors import Problem
from markinote_api.platform.tenancy import services_for_request

router = APIRouter(prefix="/api/v1/conversations", tags=["conversations"])


def get_service(request: Request) -> ConversationService:
    return services_for_request(request).conversation_service


def get_agent_service(request: Request) -> AgentService:
    return services_for_request(request).agent_service


class ConversationSummary(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    title: str
    created_at: str | None = None
    updated_at: str | None = None
    message_count: int = 0


class ConversationList(BaseModel):
    items: list[ConversationSummary]


class ConversationMessage(BaseModel):
    model_config = ConfigDict(extra="allow")
    role: Literal["user", "assistant", "tool"]
    content: str
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None
    tool_meta: dict[str, Any] | None = None
    reasoning: str | None = None
    attachments: list[str] | None = None
    context_file: str | None = None


class ConversationDetail(BaseModel):
    id: str
    title: str
    messages: list[ConversationMessage]


class ConversationEnvelope(BaseModel):
    conversation: ConversationDetail


class RenameConversation(BaseModel):
    title: str = Field(min_length=1, max_length=100)


class PartialAssistant(BaseModel):
    content: str = Field(default="", max_length=32 * 1024)
    reasoning: str = Field(default="", max_length=32 * 1024)


class TruncateConversation(BaseModel):
    user_message_number: int = Field(ge=0)
    include_user_message: bool = True


class RenameConversationResponse(BaseModel):
    success: Literal[True] = True
    title: str


class DeleteConversationResponse(BaseModel):
    success: Literal[True] = True
    backups_removed: int


class PartialAssistantResponse(BaseModel):
    success: Literal[True] = True
    saved: bool


class RollbackResult(BaseModel):
    group_id: str
    success: bool
    message: str


class TruncateConversationResponse(BaseModel):
    success: Literal[True] = True
    committed: Literal[True] = True
    message: str
    rollback_results: list[RollbackResult]


def _rollback_failure_detail(results: object) -> str:
    if not isinstance(results, list):
        return "Rollback could not be completed safely. The conversation and documents were left unchanged."
    messages = [
        str(item.get("message", ""))
        for item in results if isinstance(item, dict)
    ]
    if any("changed after the AI operation" in message for message in messages):
        return (
            "Rollback was stopped because a related document changed after the AI operation. "
            "To protect the newer edits, the conversation and documents were left unchanged."
        )
    if any(
        "snapshot is unavailable" in message or "older backup cannot verify" in message
        or "backup does not exist" in message or "备份不存在" in message
        for message in messages
    ):
        return (
            "Rollback was stopped because the required recovery data is unavailable. "
            "The conversation and documents were left unchanged."
        )
    return "Rollback could not be completed safely. The conversation and documents were left unchanged."


@router.get("", response_model=ConversationList)
def list_conversations(service: ConversationService = Depends(get_service)) -> ConversationList:
    return ConversationList(items=[ConversationSummary.model_validate(item) for item in service.list()])


@router.get("/{conversation_id}", response_model=ConversationEnvelope)
def get_conversation(
    conversation_id: str,
    service: ConversationService = Depends(get_service),
) -> ConversationEnvelope:
    return ConversationEnvelope(
        conversation=ConversationDetail.model_validate(service.get_display(conversation_id))
    )


@router.patch("/{conversation_id}", response_model=RenameConversationResponse)
def rename_conversation(
    conversation_id: str,
    body: RenameConversation,
    service: ConversationService = Depends(get_service),
    agent_service: AgentService = Depends(get_agent_service),
) -> dict[str, object]:
    with agent_service.exclusive_conversation(conversation_id):
        return {"success": True, "title": service.rename(conversation_id, body.title)}


@router.delete(
    "/{conversation_id}",
    status_code=status.HTTP_200_OK,
    response_model=DeleteConversationResponse,
)
def delete_conversation(
    conversation_id: str,
    service: ConversationService = Depends(get_service),
    agent_service: AgentService = Depends(get_agent_service),
) -> dict[str, object]:
    with agent_service.exclusive_conversation(conversation_id):
        return {"success": True, "backups_removed": service.delete(conversation_id)}


@router.post("/{conversation_id}/partial", response_model=PartialAssistantResponse)
def save_partial(
    conversation_id: str,
    body: PartialAssistant,
    service: ConversationService = Depends(get_service),
    agent_service: AgentService = Depends(get_agent_service),
) -> dict[str, object]:
    with agent_service.exclusive_conversation(conversation_id):
        return {
            "success": True,
            "saved": service.save_partial(conversation_id, body.content, body.reasoning),
        }


@router.post("/{conversation_id}/truncate", response_model=TruncateConversationResponse)
def truncate(
    conversation_id: str,
    body: TruncateConversation,
    service: ConversationService = Depends(get_service),
    agent_service: AgentService = Depends(get_agent_service),
) -> dict[str, object]:
    with agent_service.exclusive_conversation(conversation_id):
        result = service.truncate(
            conversation_id, body.user_message_number, body.include_user_message
        )
        if result.get("committed") is not True:
            raise Problem(
                409,
                "conversation_truncate_not_committed",
                "Conversation rollback was not committed",
                _rollback_failure_detail(result.get("rollback_results", [])),
                extra={"rollbackResults": result.get("rollback_results", [])},
            )
        return {
            "success": True,
            **result,
        }
