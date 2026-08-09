"""Validated runtime configuration for the ASGI application."""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
AI_SSE_TOOL_EVENT_OVERHEAD_BYTES = 64 * 1024
AI_SSE_TOOL_ARGUMENT_COPIES = 1
_HOSTNAME = re.compile(
    r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)"
    r"(?:\.(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?))*$"
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MARKINOTE_",
        env_file=(".env", ".env.local"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    environment: Literal["development", "test", "production"] = "development"
    app_name: str = "MarkiNote"
    app_version: str = "4.0.0"
    log_level: str = "INFO"
    json_logs: bool = True

    library_folder: Path = REPOSITORY_ROOT / "lib"
    conversations_folder: Path = REPOSITORY_ROOT / ".ai_conversations"
    backups_folder: Path = REPOSITORY_ROOT / ".ai_backups"
    trash_folder: Path = REPOSITORY_ROOT / ".trash"

    conversation_backend: Literal["json", "database"] = "json"
    database_url: str = f"sqlite:///{(REPOSITORY_ROOT / '.markinote.db').as_posix()}"
    # Schema ownership belongs to Alembic. Tests may opt in to ephemeral creation.
    auto_create_database: bool = False

    access_token: SecretStr | None = None
    secret_key: SecretStr | None = None
    session_cookie_name: str = "markinote_access"
    session_max_age_seconds: int = 8 * 60 * 60
    public_origin: str = ""
    trusted_origins: list[str] = Field(default_factory=list)
    trusted_hosts: list[str] = Field(
        default_factory=lambda: ["127.0.0.1", "localhost", "testserver", "api"]
    )

    max_request_bytes: int = 16 * 1024 * 1024
    max_document_bytes: int = 2 * 1024 * 1024
    max_preview_bytes: int = 2 * 1024 * 1024
    max_library_bytes: int = 1024 * 1024 * 1024
    trash_max_items: int = 500
    trash_max_bytes: int = 1024 * 1024 * 1024
    allowed_extensions: set[str] = Field(default_factory=lambda: {"md", "markdown", "txt"})
    max_message_chars: int = 32 * 1024
    max_attachment_bytes: int = 256 * 1024
    max_attachment_total_bytes: int = 768 * 1024
    max_attachment_files: int = 5
    max_context_chars: int = 120 * 1024
    # AI streams cross two untrusted boundaries: the upstream provider and
    # the browser-facing SSE response. Keep every allocation and run bounded.
    ai_max_provider_frame_bytes: int = Field(default=256 * 1024, ge=1_024, le=4 * 1024 * 1024)
    ai_max_provider_events: int = Field(default=4_096, ge=1, le=100_000)
    ai_max_provider_bytes: int = Field(default=8 * 1024 * 1024, ge=4_096, le=64 * 1024 * 1024)
    ai_max_content_bytes_per_round: int = Field(default=512 * 1024, ge=1_024, le=16 * 1024 * 1024)
    ai_max_content_bytes_total: int = Field(default=1024 * 1024, ge=1_024, le=32 * 1024 * 1024)
    ai_max_tool_arguments_bytes: int = Field(default=64 * 1024, ge=256, le=1024 * 1024)
    ai_max_sse_event_bytes: int = Field(default=512 * 1024, ge=1_024, le=4 * 1024 * 1024)
    ai_max_stream_seconds: int = Field(default=10 * 60, ge=1, le=60 * 60)
    backup_max_groups: int = 100
    backup_max_bytes: int = 256 * 1024 * 1024
    ai_generate_titles: bool = False
    ai_api_key: SecretStr | None = None
    # CI-only upstream fixture. Keeping the override in typed configuration,
    # rather than mutating the provider registry, makes the production guard
    # auditable and prevents a smoke test from reaching a real provider.
    ai_provider_fixture_url: str = ""
    # Reconciliation is destructive to active runs and is therefore disabled
    # unless an operator explicitly attests that exactly one API writer exists.
    agent_run_reconcile_on_startup: bool = False
    agent_run_single_writer: bool = False
    agent_run_reconcile_limit: int = Field(default=1_000, ge=1, le=10_000)

    metrics_enabled: bool = True
    otel_enabled: bool = False
    otel_endpoint: str = "http://otel-collector:4318/v1/traces"
    otel_service_name: str = "markinote-api"

    @field_validator(
        "max_document_bytes",
        "max_preview_bytes",
        "max_request_bytes",
        "max_message_chars",
        "max_attachment_bytes",
        "max_attachment_total_bytes",
        "max_attachment_files",
        "max_context_chars",
        "backup_max_groups",
        "backup_max_bytes",
        "session_max_age_seconds",
        "max_library_bytes",
        "trash_max_items",
        "trash_max_bytes",
    )
    @classmethod
    def positive_limit(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("limits must be positive")
        return value

    @field_validator("trusted_hosts")
    @classmethod
    def validate_trusted_hosts(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for raw_value in values:
            value = raw_value.strip().casefold().rstrip(".")
            if value == "*":
                candidate = value
            else:
                candidate = value[2:] if value.startswith("*.") else value
                if not _HOSTNAME.fullmatch(candidate):
                    raise ValueError(
                        "trusted_hosts entries must be hostnames without a scheme, path, or port"
                    )
            if value not in normalized:
                normalized.append(value)
        return normalized

    @model_validator(mode="after")
    def validate_production_security(self) -> Settings:
        if self.ai_max_content_bytes_total < self.ai_max_content_bytes_per_round:
            raise ValueError(
                "ai_max_content_bytes_total must be at least ai_max_content_bytes_per_round"
            )
        if self.ai_max_provider_bytes < self.ai_max_content_bytes_total:
            raise ValueError(
                "ai_max_provider_bytes must be at least ai_max_content_bytes_total"
            )
        if (
            self.ai_max_sse_event_bytes
            < self.ai_max_tool_arguments_bytes * AI_SSE_TOOL_ARGUMENT_COPIES
            + AI_SSE_TOOL_EVENT_OVERHEAD_BYTES
        ):
            raise ValueError(
                "ai_max_sse_event_bytes must cover ai_max_tool_arguments_bytes "
                "plus the tool-result envelope"
            )
        if self.agent_run_reconcile_on_startup and not self.agent_run_single_writer:
            raise ValueError(
                "agent run startup reconciliation requires an explicit single-writer "
                "acknowledgement"
            )
        if self.ai_provider_fixture_url:
            fixture = urlsplit(self.ai_provider_fixture_url)
            if self.environment != "test":
                raise ValueError("ai_provider_fixture_url is allowed only in the test environment")
            if self.ai_generate_titles:
                raise ValueError("ai provider fixture requires automatic title generation to be disabled")
            if (
                fixture.scheme != "http"
                or fixture.hostname != "fake-provider"
                or fixture.port != 8099
                or fixture.username
                or fixture.password
                or fixture.path not in {"", "/"}
                or fixture.query
                or fixture.fragment
            ):
                raise ValueError(
                    "test ai_provider_fixture_url must be the isolated "
                    "http://fake-provider:8099 origin"
                )
        if self.environment != "production":
            return self
        token = self.access_token.get_secret_value() if self.access_token else ""
        secret = self.secret_key.get_secret_value() if self.secret_key else ""
        if len(token) < 24:
            raise ValueError("production requires an access token of at least 24 characters")
        if len(secret) < 32:
            raise ValueError("production requires a distinct secret key of at least 32 characters")
        if hmac_compare(token, secret):
            raise ValueError("production access token and secret key must be different")
        origin = urlsplit(self.public_origin)
        try:
            origin_port = origin.port
        except ValueError as error:
            raise ValueError("production public_origin must contain a valid TCP port") from error
        if origin.scheme != "https" or not origin.hostname or origin.username or origin.password:
            raise ValueError("production public_origin must be an HTTPS origin without credentials")
        if origin_port is not None and not 1 <= origin_port <= 65535:
            raise ValueError("production public_origin must contain a valid TCP port")
        if origin.path not in {"", "/"} or origin.query or origin.fragment:
            raise ValueError("production public_origin must not contain a path, query, or fragment")
        if "trusted_hosts" not in self.model_fields_set:
            raise ValueError("production requires trusted_hosts to be configured explicitly")
        if not self.trusted_hosts or "*" in self.trusted_hosts:
            raise ValueError("production trusted_hosts must be non-empty and cannot contain '*'")
        origin_host = origin.hostname.casefold().rstrip(".")
        if not any(trusted_host_matches(origin_host, pattern) for pattern in self.trusted_hosts):
            raise ValueError("production trusted_hosts must include the public_origin hostname")
        required_internal_hosts = {"127.0.0.1", "api"}
        if not required_internal_hosts.issubset(self.trusted_hosts):
            raise ValueError(
                "production trusted_hosts must include '127.0.0.1' for health checks "
                "and 'api' for internal monitoring"
            )
        if self.auto_create_database:
            raise ValueError("production schema auto-creation is forbidden; run Alembic migrations")
        return self

    def ensure_directories(self) -> None:
        for path in (
            self.library_folder,
            self.conversations_folder,
            self.backups_folder,
            self.trash_folder,
        ):
            path.mkdir(parents=True, exist_ok=True)

@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_directories()
    return settings


def hmac_compare(left: str, right: str) -> bool:
    """Constant-time equality without exposing SecretStr values in validation errors."""
    import hmac

    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


def trusted_host_matches(hostname: str, pattern: str) -> bool:
    """Mirror Starlette's exact/leading-wildcard host matching for validation."""
    if pattern.startswith("*."):
        return hostname.endswith(pattern[1:]) and hostname != pattern[2:]
    return hostname == pattern
