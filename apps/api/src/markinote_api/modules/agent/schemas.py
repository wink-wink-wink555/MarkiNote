"""Typed AI HTTP contracts."""
from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel, SecretStr, field_validator


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=32 * 1024)
    conversation_id: str = Field(default="", max_length=64)
    run_id: str = Field(default="", max_length=96)
    provider: str = Field(default="deepseek", max_length=64)
    model: str = Field(default="deepseek-v4-flash", max_length=128)
    api_key: SecretStr | None = Field(default=None, repr=False)
    context_file: str = Field(default="", max_length=1024)
    attached_files: list[str] = Field(default_factory=list, max_length=5)
    language: Literal["zh-CN", "en", "fr", "ja"] = "zh-CN"
    allow_write_tools: bool = False
    approval_id: str | None = Field(default=None, max_length=64)
    approval_decision: Literal["approve", "deny"] | None = None

    @field_validator("message")
    @classmethod
    def strip_message(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("message cannot be empty")
        return value


class ValidateKeyRequest(BaseModel):
    provider: str = Field(max_length=64)
    api_key: SecretStr = Field(repr=False)


class ProviderModel(BaseModel):
    id: str
    name: str


class ProviderInfo(BaseModel):
    name: str
    models: list[ProviderModel]


class ProvidersResponse(BaseModel):
    providers: dict[str, ProviderInfo]
    limits: dict[str, int]
    server_key_configured: bool = Field(alias="serverKeyConfigured")


class ValidateKeyResponse(BaseModel):
    success: bool
    message: str


class ConversationIdEventData(BaseModel):
    id: str


class TokenEventData(BaseModel):
    content: str


class ToolCallEventData(BaseModel):
    call_id: str
    name: str
    args: dict[str, Any]


class ToolApprovalData(BaseModel):
    id: str
    status: Literal["pending", "approved", "denied"]
    target: str
    reason: Literal["unselected_resource", "external_content"] = "unselected_resource"


class ToolResultEventData(ToolCallEventData):
    result: str
    backup_info: dict[str, Any] | None = None
    backup_group_id: str | None = None
    approval: ToolApprovalData | None = None
    resolved_approval_id: str | None = None


class TitleEventData(BaseModel):
    title: str


class DoneEventData(BaseModel):
    conversation_id: str


class ErrorEventData(BaseModel):
    code: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    message: str


class AgentEventEnvelope(BaseModel):
    schema_version: int = Field(default=1, alias="schemaVersion")
    run_id: str = Field(alias="runId")
    sequence: int


class ConversationIdAgentEvent(AgentEventEnvelope):
    type: Literal["conversation_id"]
    data: ConversationIdEventData


class TokenAgentEvent(AgentEventEnvelope):
    type: Literal["token"]
    data: TokenEventData


class ToolCallAgentEvent(AgentEventEnvelope):
    type: Literal["tool_call"]
    data: ToolCallEventData


class ToolResultAgentEvent(AgentEventEnvelope):
    type: Literal["tool_result"]
    data: ToolResultEventData


class TitleAgentEvent(AgentEventEnvelope):
    type: Literal["title_generated"]
    data: TitleEventData


class DoneAgentEvent(AgentEventEnvelope):
    type: Literal["done"]
    data: DoneEventData


class ErrorAgentEvent(AgentEventEnvelope):
    type: Literal["error"]
    data: ErrorEventData


class AgentEvent(
    RootModel[
        Annotated[
            ConversationIdAgentEvent
            | TokenAgentEvent
            | ToolCallAgentEvent
            | ToolResultAgentEvent
            | TitleAgentEvent
            | DoneAgentEvent
            | ErrorAgentEvent,
            Field(discriminator="type"),
        ]
    ]
):
    """Discriminated SSE contract used by OpenAPI and generated clients."""
