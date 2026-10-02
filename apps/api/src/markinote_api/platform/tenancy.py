"""Request-scoped service bundles backed by one tenant-keyed database."""
from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from typing import Any

from fastapi import Request

from markinote_api.config import Settings
from markinote_api.modules.accounts.credentials import CredentialVault
from markinote_api.modules.agent.run_journal import SqlAgentRunJournal
from markinote_api.modules.agent.service import AgentService
from markinote_api.modules.conversations.repository import Database, SqlConversationRepository
from markinote_api.modules.conversations.service import ConversationService
from markinote_api.modules.documents.database_storage import DatabaseDocumentStorage
from markinote_api.modules.documents.service import DocumentService
from markinote_api.modules.operations.database_backup import DatabaseBackupManager
from markinote_api.modules.operations.journal import SqlCommandJournal
from markinote_api.platform.errors import Problem

_ACCOUNT_ID = re.compile(r"^[0-9a-f]{32}$")


@dataclass(slots=True)
class UserServices:
    settings: Settings
    document_service: DocumentService
    backup_manager: Any
    conversation_service: ConversationService
    command_journal: Any
    agent_run_journal: Any
    agent_service: AgentService


class UserServiceRegistry:
    def __init__(
        self,
        settings: Settings,
        database: Database | None,
        legacy: UserServices,
        *,
        credential_vault: CredentialVault | None,
        finance_mcp: Any = None,
        provider_stream: Any = None,
    ) -> None:
        self.settings = settings
        self.database = database
        self.legacy = legacy
        self.credential_vault = credential_vault
        self.finance_mcp = finance_mcp
        self.provider_stream = provider_stream
        self._guard = threading.Lock()
        self._services: dict[str, UserServices] = {}

    def get(self, user_id: str | None) -> UserServices:
        if self.settings.auth_mode != "accounts":
            return self.legacy
        if self.database is None or self.credential_vault is None:
            raise RuntimeError("account service registry requires database dependencies")
        if user_id is None or not _ACCOUNT_ID.fullmatch(user_id):
            raise Problem(401, "authentication_required", "Authentication required", "Sign in to access this workspace.")
        with self._guard:
            services = self._services.get(user_id)
            if services is None:
                services = self._build(user_id)
                self._services[user_id] = services
            return services

    def _build(self, user_id: str) -> UserServices:
        if self.database is None or self.credential_vault is None:
            raise RuntimeError("account service registry requires database dependencies")
        database = self.database
        credential_vault = self.credential_vault
        storage = DatabaseDocumentStorage(
            database,
            user_id,
            allowed_extensions=self.settings.allowed_extensions,
            max_document_bytes=self.settings.max_document_bytes,
            max_library_bytes=self.settings.max_library_bytes,
            trash_max_items=self.settings.trash_max_items,
            trash_max_bytes=self.settings.trash_max_bytes,
        )
        documents = DocumentService(storage)
        backups = DatabaseBackupManager(
            database,
            user_id,
            storage,
            self.settings.backup_max_groups,
            self.settings.backup_max_bytes,
        )
        conversations = ConversationService(
            SqlConversationRepository(database, user_id=user_id),
            backups,
        )
        journal = SqlCommandJournal(database, user_id=user_id)
        run_journal = SqlAgentRunJournal(database, user_id=user_id)
        agent = AgentService(
            settings=self.settings,
            conversations=conversations,
            backup_manager=backups,
            journal=journal,
            run_journal=run_journal,
            documents=documents,
            provider_stream=self.provider_stream,
            finance_mcp=self.finance_mcp,
            credential_loader=lambda name: credential_vault.get(user_id, name),
        )
        return UserServices(
            settings=self.settings,
            document_service=documents,
            backup_manager=backups,
            conversation_service=conversations,
            command_journal=journal,
            agent_run_journal=run_journal,
            agent_service=agent,
        )


def services_for_request(request: Request) -> UserServices:
    registry: UserServiceRegistry = request.app.state.user_service_registry
    return registry.get(getattr(request.state, "user_id", None))
