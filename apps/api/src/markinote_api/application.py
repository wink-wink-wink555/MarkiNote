"""ASGI composition root for MarkiNote."""
from __future__ import annotations

from contextlib import asynccontextmanager
from functools import partial
from typing import cast

from fastapi import FastAPI
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.openapi.utils import get_openapi
from starlette.middleware.trustedhost import TrustedHostMiddleware

from markinote_api.config import Settings, get_settings
from markinote_api.modules.accounts.auth import AccountAuth
from markinote_api.modules.accounts.credentials import CredentialVault
from markinote_api.modules.accounts.mailer import VerificationMailer
from markinote_api.modules.accounts.router import credential_router
from markinote_api.modules.accounts.router import router as account_router
from markinote_api.modules.accounts.store import AccountStore
from markinote_api.modules.agent.finance_mcp import FinanceMcpClient
from markinote_api.modules.agent.ports import AgentRunJournal
from markinote_api.modules.agent.provider import stream_chat_completion
from markinote_api.modules.agent.router import router as agent_router
from markinote_api.modules.agent.run_journal import (
    PROCESS_RESTARTED_ERROR_CODE,
    JsonAgentRunJournal,
    SqlAgentRunJournal,
)
from markinote_api.modules.agent.service import AgentService
from markinote_api.modules.conversations.repository import (
    ConversationRepository,
    Database,
    JsonConversationRepository,
    SqlConversationRepository,
)
from markinote_api.modules.conversations.router import router as conversation_router
from markinote_api.modules.conversations.service import ConversationService
from markinote_api.modules.documents.router import router as document_router
from markinote_api.modules.documents.service import DocumentService
from markinote_api.modules.documents.storage import LocalDocumentStorage
from markinote_api.modules.operations.backup import BackupManager
from markinote_api.modules.operations.journal import CommandJournal, JsonCommandJournal, SqlCommandJournal
from markinote_api.modules.operations.router import router as operations_router
from markinote_api.modules.rendering.router import router as rendering_router
from markinote_api.platform.errors import ProblemDetails, install_exception_handlers
from markinote_api.platform.health import router as health_router
from markinote_api.platform.logging import configure_logging
from markinote_api.platform.middleware import install_middleware
from markinote_api.platform.schemas import ApiRootResponse
from markinote_api.platform.telemetry import configure_telemetry
from markinote_api.platform.tenancy import UserServiceRegistry, UserServices


def create_application(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    settings.ensure_directories()
    logger = configure_logging(settings.log_level, json_logs=settings.json_logs)

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        try:
            application.state.agent_run_reconciled_count = 0
            if settings.agent_run_reconcile_on_startup:
                try:
                    reconciled = application.state.agent_run_journal.reconcile_running(
                        limit=settings.agent_run_reconcile_limit,
                        apply=True,
                    )
                except Exception:
                    logger.exception(
                        "agent run startup reconciliation failed",
                        extra={"error_code": "agent_run_reconciliation_failed"},
                    )
                    raise RuntimeError("agent run startup reconciliation failed") from None
                application.state.agent_run_reconciled_count = reconciled
                if reconciled:
                    logger.warning(
                        "stale agent runs reconciled after sole-writer process restart",
                        extra={
                            "agent_run_state": "failed",
                            "error_code": PROCESS_RESTARTED_ERROR_CODE,
                        },
                    )
            yield
        finally:
            database = getattr(application.state, "database", None)
            if database is not None:
                database.close()
            tracer_provider = getattr(application.state, "tracer_provider", None)
            if tracer_provider is not None:
                tracer_provider.shutdown()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        summary="Typed API for the MarkiNote document workspace and AI agent",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
        responses={
            status_code: {"model": ProblemDetails, "description": description}
            for status_code, description in {
                400: "Invalid request",
                401: "Authentication required",
                403: "Request forbidden",
                404: "Resource not found",
                409: "Resource conflict",
                413: "Request or resource too large",
                422: "Contract validation failed",
                500: "Internal server error",
            }.items()
        },
    )
    app.state.settings = settings
    app.state.logger = logger

    backup_manager = BackupManager(
        settings.backups_folder,
        settings.library_folder,
        settings.backup_max_groups,
        settings.backup_max_bytes,
    )
    app.state.backup_manager = backup_manager
    app.state.document_service = DocumentService(
        LocalDocumentStorage(
            settings.library_folder,
            settings.trash_folder,
            allowed_extensions=settings.allowed_extensions,
            max_document_bytes=settings.max_document_bytes,
            max_library_bytes=settings.max_library_bytes,
            trash_max_items=settings.trash_max_items,
            trash_max_bytes=settings.trash_max_bytes,
        )
    )

    database: Database | None = None
    conversation_repository: ConversationRepository
    command_journal: CommandJournal
    agent_run_journal: AgentRunJournal
    if settings.conversation_backend == "database":
        database = Database(settings.database_url, create_schema=settings.auto_create_database)
        conversation_repository = SqlConversationRepository(database)
        command_journal = SqlCommandJournal(database)
        agent_run_journal = SqlAgentRunJournal(database)
    else:
        conversation_repository = JsonConversationRepository(settings.conversations_folder)
        command_journal = JsonCommandJournal(settings.backups_folder)
        agent_run_journal = JsonAgentRunJournal(settings.backups_folder)

    conversation_service = ConversationService(conversation_repository, backup_manager)
    app.state.database = database
    app.state.conversation_repository = conversation_repository
    app.state.conversation_service = conversation_service
    app.state.command_journal = command_journal
    app.state.agent_run_journal = agent_run_journal
    app.state.agent_service = AgentService(
        settings=settings,
        conversations=conversation_service,
        backup_manager=backup_manager,
        journal=command_journal,
        run_journal=agent_run_journal,
        documents=app.state.document_service,
        provider_stream=(
            partial(
                stream_chat_completion,
                base_url_override=settings.ai_provider_fixture_url,
            )
            if settings.ai_provider_fixture_url
            else None
        ),
    )
    finance_mcp = (
        FinanceMcpClient(
            settings.finance_mcp_url,
            timeout_seconds=settings.finance_mcp_timeout_seconds,
        )
        if settings.finance_mcp_url
        else None
    )
    app.state.finance_mcp = finance_mcp
    if finance_mcp is not None:
        app.state.agent_service.finance_mcp = finance_mcp

    credential_vault = CredentialVault(database, settings) if database is not None else None
    if settings.auth_mode == "accounts":
        if database is None or credential_vault is None:
            raise RuntimeError("account mode requires a database")
        account_store = AccountStore(database)
        app.state.account_store = account_store
        app.state.account_auth = AccountAuth(settings, account_store)
        app.state.verification_mailer = VerificationMailer(settings)
        app.state.credential_vault = credential_vault

    app.state.user_service_registry = UserServiceRegistry(
        settings,
        database,
        UserServices(
            settings=settings,
            document_service=app.state.document_service,
            backup_manager=backup_manager,
            conversation_service=conversation_service,
            command_journal=command_journal,
            agent_run_journal=agent_run_journal,
            agent_service=app.state.agent_service,
        ),
        credential_vault=credential_vault,
        finance_mcp=finance_mcp,
        provider_stream=app.state.agent_service.provider_stream,
    )
    install_exception_handlers(app)
    install_middleware(app, settings)
    app.state.telemetry_enabled = configure_telemetry(app, settings)
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    # Register this last so Starlette evaluates the Host header before all
    # application middleware and routers.
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)
    app.include_router(health_router)
    app.include_router(account_router)
    app.include_router(credential_router)
    app.include_router(rendering_router)
    app.include_router(document_router)
    app.include_router(conversation_router)
    app.include_router(agent_router)
    app.include_router(operations_router)

    def enterprise_openapi() -> dict[str, object]:
        if app.openapi_schema is not None:
            return cast(dict[str, object], app.openapi_schema)
        schema = get_openapi(
            title=app.title,
            version=app.version,
            summary=app.summary,
            description=app.description,
            routes=app.routes,
        )
        components = schema.setdefault("components", {})
        security_schemes = components.setdefault("securitySchemes", {})
        security_schemes.update(
            {
                "bearerAuth": {
                    "type": "http",
                    "scheme": "bearer",
                    "description": "Deployment access token for non-browser clients.",
                },
                "sessionCookie": {
                    "type": "apiKey",
                    "in": "cookie",
                    "name": settings.session_cookie_name,
                    "description": "Signed HttpOnly cookie issued by the same-origin POST exchange.",
                },
            }
        )
        for path, path_item in schema.get("paths", {}).items():
            if not str(path).startswith("/api/v1") or not isinstance(path_item, dict):
                continue
            for operation in path_item.values():
                if isinstance(operation, dict) and "responses" in operation:
                    operation["security"] = [{"bearerAuth": []}, {"sessionCookie": []}]
        chat_operation = schema.get("paths", {}).get("/api/v1/agent/chat", {}).get("post", {})
        chat_content = chat_operation.get("responses", {}).get("200", {}).get("content", {})
        if isinstance(chat_content, dict):
            # The Pydantic model registers the reusable event component; the
            # wire response itself is exclusively SSE, never JSON.
            chat_content.pop("application/json", None)
        app.openapi_schema = schema
        return cast(dict[str, object], schema)

    app.openapi = enterprise_openapi  # type: ignore[method-assign]

    @app.get("/api/v1", tags=["platform"], response_model=ApiRootResponse)
    def api_root() -> ApiRootResponse:
        return ApiRootResponse(
            name=settings.app_name,
            version=settings.app_version,
            contract=1,
        )

    return app


app = create_application()
