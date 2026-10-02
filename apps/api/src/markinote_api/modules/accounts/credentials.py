"""Encrypted, database-backed per-account integration credentials."""
from __future__ import annotations

import base64
import hashlib
from datetime import UTC, datetime

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import DateTime, ForeignKey, LargeBinary, String, UniqueConstraint, delete, select
from sqlalchemy.orm import Mapped, mapped_column

from markinote_api.config import Settings
from markinote_api.modules.conversations.repository import Base, Database

SUPPORTED_CREDENTIALS = frozenset({"deepseek_api_key", "tushare_token", "qveris_api_key"})


class UserCredentialRecord(Base):
    __tablename__ = "user_credentials"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_user_credentials_name"),)

    user_id: Mapped[str] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"),
        primary_key=True,
    )
    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    encrypted_value: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


def _development_key(settings: Settings) -> bytes:
    material = (
        settings.credential_encryption_key.get_secret_value()
        if settings.credential_encryption_key
        else settings.secret_key.get_secret_value()
        if settings.secret_key
        else "markinote-development-credential-key"
    )
    return base64.urlsafe_b64encode(hashlib.sha256(material.encode("utf-8")).digest())


class CredentialVault:
    def __init__(self, database: Database, settings: Settings):
        self.database = database
        raw_key = (
            settings.credential_encryption_key.get_secret_value().encode("ascii")
            if settings.credential_encryption_key
            else _development_key(settings)
        )
        try:
            self.cipher = Fernet(raw_key)
        except (TypeError, ValueError) as error:
            raise ValueError("credential_encryption_key must be a Fernet key") from error

    def configured(self, user_id: str) -> dict[str, bool]:
        with self.database.session() as session:
            names = set(
                session.scalars(
                    select(UserCredentialRecord.name).where(
                        UserCredentialRecord.user_id == user_id
                    )
                )
            )
        return {name: name in names for name in sorted(SUPPORTED_CREDENTIALS)}

    def get(self, user_id: str, name: str) -> str:
        if name not in SUPPORTED_CREDENTIALS:
            return ""
        with self.database.session() as session:
            record = session.get(UserCredentialRecord, (user_id, name))
        if record is None:
            return ""
        try:
            return self.cipher.decrypt(record.encrypted_value).decode("utf-8")
        except (InvalidToken, UnicodeDecodeError) as error:
            raise RuntimeError("stored credential cannot be decrypted") from error

    def set_many(self, user_id: str, values: dict[str, str | None]) -> None:
        unknown = set(values) - SUPPORTED_CREDENTIALS
        if unknown:
            raise ValueError("unsupported credential name")
        now = datetime.now(UTC)
        with self.database.session() as session, session.begin():
            for name, raw_value in values.items():
                value = (raw_value or "").strip()
                record = session.get(UserCredentialRecord, (user_id, name))
                if not value:
                    if record is not None:
                        session.delete(record)
                    continue
                encrypted = self.cipher.encrypt(value.encode("utf-8"))
                if record is None:
                    session.add(
                        UserCredentialRecord(
                            user_id=user_id,
                            name=name,
                            encrypted_value=encrypted,
                            updated_at=now,
                        )
                    )
                else:
                    record.encrypted_value = encrypted
                    record.updated_at = now

    def delete_all(self, user_id: str) -> None:
        with self.database.session() as session, session.begin():
            session.execute(
                delete(UserCredentialRecord).where(UserCredentialRecord.user_id == user_id)
            )
