"""Provision one verified account and its encrypted integration credentials."""
from __future__ import annotations

import os

from markinote_api.config import get_settings
from markinote_api.modules.accounts.credentials import CredentialVault
from markinote_api.modules.accounts.provisioning import provision_default_workspace
from markinote_api.modules.accounts.store import AccountStore
from markinote_api.modules.conversations.repository import Database
from markinote_api.modules.documents.database_storage import DatabaseDocumentStorage
from markinote_api.modules.documents.service import DocumentService


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"{name} is required")
    return value


def main() -> None:
    settings = get_settings()
    database = Database(settings.database_url, create_schema=False)
    store = AccountStore(database)
    email = _required("MARKINOTE_BOOTSTRAP_EMAIL")
    account = store.account_by_email(email)
    created = account is None
    if account is None:
        account = store.register(
            email,
            _required("MARKINOTE_BOOTSTRAP_PASSWORD"),
            username=_required("MARKINOTE_BOOTSTRAP_USERNAME"),
        )
    account = store.mark_email_verified(account.id)
    documents = DocumentService(
        DatabaseDocumentStorage(
            database,
            account.id,
            allowed_extensions=settings.allowed_extensions,
            max_document_bytes=settings.max_document_bytes,
            max_library_bytes=settings.max_library_bytes,
            trash_max_items=settings.trash_max_items,
            trash_max_bytes=settings.trash_max_bytes,
        )
    )
    provision_default_workspace(documents)
    credentials = {
        "deepseek_api_key": os.environ.get("MARKINOTE_BOOTSTRAP_DEEPSEEK_API_KEY"),
        "tushare_token": os.environ.get("MARKINOTE_BOOTSTRAP_TUSHARE_TOKEN"),
        "qveris_api_key": os.environ.get("MARKINOTE_BOOTSTRAP_QVERIS_API_KEY"),
    }
    CredentialVault(database, settings).set_many(
        account.id,
        {name: value for name, value in credentials.items() if value},
    )
    database.close()
    action = "created" if created else "updated"
    print(f"account {account.username} {action}; workspace and encrypted credentials provisioned")


if __name__ == "__main__":
    main()
