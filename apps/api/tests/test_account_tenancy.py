from __future__ import annotations

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select

from markinote_api.config import Settings
from markinote_api.modules.accounts.credentials import CredentialVault, UserCredentialRecord
from markinote_api.modules.accounts.store import AccountStore
from markinote_api.modules.conversations.repository import Database
from markinote_api.modules.documents.database_storage import DatabaseDocumentStorage
from markinote_api.modules.documents.errors import DocumentCapacityExceeded, DocumentNotFound
from markinote_api.modules.documents.service import DocumentService

from .test_platform_api import build_client


def _documents(database: Database, user_id: str, *, quota: int = 30 * 1024 * 1024) -> DocumentService:
    return DocumentService(
        DatabaseDocumentStorage(
            database,
            user_id,
            allowed_extensions={"md", "txt"},
            max_document_bytes=quota,
            max_library_bytes=quota,
            trash_max_items=100,
            trash_max_bytes=quota,
        )
    )


def test_database_workspaces_and_encrypted_credentials_are_tenant_scoped(tmp_path) -> None:
    database = Database(f"sqlite:///{(tmp_path / 'accounts.db').as_posix()}", create_schema=True)
    store = AccountStore(database)
    first = store.register("first@example.test", "first-password", username="first")
    second = store.register("second@example.test", "second-password", username="second")
    first_documents = _documents(database, first.id, quota=16)
    second_documents = _documents(database, second.id, quota=16)

    first_documents.create_file("", "private.md", "first account")
    with pytest.raises(DocumentNotFound):
        second_documents.read("private.md")
    second_documents.create_file("", "private.md", "second")
    assert first_documents.read("private.md")["content"] == "first account"
    assert second_documents.read("private.md")["content"] == "second"

    with pytest.raises(DocumentCapacityExceeded):
        first_documents.create_file("", "overflow.md", "12345")
    second_documents.create_file("", "within.txt", "123456789")

    key = Fernet.generate_key().decode("ascii")
    vault = CredentialVault(
        database,
        Settings(credential_encryption_key=key),
    )
    vault.set_many(first.id, {"deepseek_api_key": "private-deepseek-key"})
    assert vault.get(first.id, "deepseek_api_key") == "private-deepseek-key"
    assert vault.get(second.id, "deepseek_api_key") == ""
    with database.session() as session:
        encrypted = session.scalar(
            select(UserCredentialRecord.encrypted_value).where(
                UserCredentialRecord.user_id == first.id,
                UserCredentialRecord.name == "deepseek_api_key",
            )
        )
    assert encrypted is not None
    assert b"private-deepseek-key" not in encrypted
    database.close()


def test_registration_verification_defaults_and_cookie_isolation() -> None:
    client, temp = build_client(
        backend="database",
        settings_overrides={
            "auth_mode": "accounts",
            "registration_enabled": True,
            "credential_encryption_key": Fernet.generate_key().decode("ascii"),
        },
    )
    verification_tokens: dict[str, str] = {}
    client.app.state.verification_mailer.send_verification = (
        lambda email, token: verification_tokens.__setitem__(email, token)
    )
    same_origin = {"Origin": "http://testserver"}
    try:
        registered = client.post(
            "/auth/register",
            json={"email": "one@example.test", "username": "account_one", "password": "account-one-password"},
            headers=same_origin,
        )
        assert registered.status_code == 202
        verified = client.post(
            "/auth/verify-email",
            json={"token": verification_tokens["one@example.test"]},
            headers=same_origin,
        )
        assert verified.status_code == 200
        assert client.get("/api/v1/documents", params={"path": "Getting Started"}).status_code == 200
        assert client.post(
            "/api/v1/documents/files",
            json={"path": "", "name": "private.md", "content": "one"},
        ).status_code == 200
        first_cookie = client.cookies.get("markinote_access")
        assert first_cookie

        client.cookies.clear()
        registered = client.post(
            "/auth/register",
            json={"email": "two@example.test", "username": "account_two", "password": "account-two-password"},
            headers=same_origin,
        )
        assert registered.status_code == 202
        assert client.post(
            "/auth/verify-email",
            json={"token": verification_tokens["two@example.test"]},
            headers=same_origin,
        ).status_code == 200
        assert client.get("/api/v1/documents/content", params={"path": "private.md"}).status_code == 404
        assert client.post(
            "/api/v1/documents/files",
            json={"path": "", "name": "private.md", "content": "two"},
        ).status_code == 200
        second_cookie = client.cookies.get("markinote_access")
        assert second_cookie and second_cookie != first_cookie

        client.cookies.clear()
        client.cookies.set("markinote_access", first_cookie)
        first_document = client.get("/api/v1/documents/content", params={"path": "private.md"})
        assert first_document.status_code == 200
        assert first_document.json()["content"] == "one"
    finally:
        client.close()
        client.app.state.database.close()
        temp.cleanup()
