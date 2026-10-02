"""Database-backed accounts and one-time email verification tokens."""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column

from markinote_api.modules.conversations.repository import Base, Database

EMAIL_PATTERN = re.compile(
    r"^[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
    r"(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$"
)
USERNAME_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{2,31}$")
SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 32


class AccountRecord(Base):
    __tablename__ = "accounts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    email: Mapped[str] = mapped_column(String(254), nullable=False, unique=True, index=True)
    username: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    session_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    email_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    disabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EmailVerificationRecord(Base):
    __tablename__ = "email_verifications"

    account_id: Mapped[str] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"),
        primary_key=True,
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AccountAlreadyExistsError(ValueError):
    pass


class InvalidEmailError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Account:
    id: str
    email: str
    username: str
    session_version: int
    email_verified: bool


def normalize_email(value: str) -> str:
    email = value.strip().casefold()
    if len(email) > 254 or not EMAIL_PATTERN.fullmatch(email):
        raise InvalidEmailError("Enter a valid email address.")
    return email


def normalize_username(value: str) -> str:
    username = value.strip().casefold()
    if not USERNAME_PATTERN.fullmatch(username):
        raise ValueError("Username must contain 3-32 lowercase letters, digits, underscores, or hyphens.")
    return username


def _password_hash(password: str, *, salt: bytes | None = None) -> str:
    password_bytes = password.encode("utf-8")
    if not 10 <= len(password) <= 128 or len(password_bytes) > 512:
        raise ValueError("Password must contain 10-128 characters.")
    salt = salt or os.urandom(16)
    digest = hashlib.scrypt(
        password_bytes,
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=SCRYPT_DKLEN,
    )
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt.hex()}${digest.hex()}"


def _password_matches(password: str, encoded: str) -> bool:
    try:
        algorithm, raw_n, raw_r, raw_p, raw_salt, raw_digest = encoded.split("$", 5)
        if algorithm != "scrypt":
            return False
        expected = bytes.fromhex(raw_digest)
        candidate = hashlib.scrypt(
            password.encode("utf-8"),
            salt=bytes.fromhex(raw_salt),
            n=int(raw_n),
            r=int(raw_r),
            p=int(raw_p),
            dklen=len(expected),
        )
    except (TypeError, ValueError, UnicodeError):
        return False
    return hmac.compare_digest(candidate, expected)


def _account(record: AccountRecord) -> Account:
    return Account(
        id=record.id,
        email=record.email,
        username=record.username,
        session_version=record.session_version,
        email_verified=record.email_verified,
    )


class AccountStore:
    def __init__(self, database: Database):
        self.database = database
        self._dummy_hash = _password_hash("markinote-dummy-password")

    def register(self, email: str, password: str, *, username: str = "") -> Account:
        normalized = normalize_email(email)
        normalized_username = normalize_username(username or normalized.split("@", 1)[0])
        record = AccountRecord(
            id=uuid.uuid4().hex,
            email=normalized,
            username=normalized_username,
            password_hash=_password_hash(password),
            session_version=1,
            email_verified=False,
            disabled=False,
            created_at=datetime.now(UTC),
        )
        try:
            with self.database.session() as session, session.begin():
                session.add(record)
        except IntegrityError as error:
            raise AccountAlreadyExistsError("Email is already registered.") from error
        return _account(record)

    def authenticate(self, identity: str, password: str) -> Account | None:
        normalized = identity.strip().casefold()
        if "@" in normalized:
            try:
                normalized = normalize_email(normalized)
            except InvalidEmailError:
                _password_matches(password, self._dummy_hash)
                return None
            predicate = AccountRecord.email == normalized
        else:
            try:
                normalized = normalize_username(normalized)
            except ValueError:
                _password_matches(password, self._dummy_hash)
                return None
            predicate = AccountRecord.username == normalized
        with self.database.session() as session:
            record = session.scalar(
                select(AccountRecord).where(predicate)
            )
        encoded = record.password_hash if record is not None else self._dummy_hash
        valid = _password_matches(password, encoded)
        if record is None or not valid or record.disabled:
            return None
        return _account(record)

    def session_account(self, account_id: str, session_version: int) -> Account | None:
        if not re.fullmatch(r"[0-9a-f]{32}", account_id):
            return None
        with self.database.session() as session:
            record = session.get(AccountRecord, account_id)
        if record is None or record.disabled or record.session_version != session_version:
            return None
        return _account(record)

    def account_by_email(self, email: str) -> Account | None:
        try:
            normalized = normalize_email(email)
        except InvalidEmailError:
            return None
        with self.database.session() as session:
            record = session.scalar(
                select(AccountRecord).where(AccountRecord.email == normalized)
            )
        return None if record is None or record.disabled else _account(record)

    def mark_email_verified(self, account_id: str) -> Account:
        """Verify an account from an authenticated operator provisioning path."""
        with self.database.session() as session, session.begin():
            record = session.get(AccountRecord, account_id)
            if record is None or record.disabled:
                raise ValueError("Account does not exist.")
            record.email_verified = True
            session.execute(
                delete(EmailVerificationRecord).where(
                    EmailVerificationRecord.account_id == account_id
                )
            )
            session.flush()
            result = _account(record)
        return result

    def create_verification(self, account_id: str, *, ttl_seconds: int) -> str:
        token = secrets.token_urlsafe(32)
        now = datetime.now(UTC)
        record = EmailVerificationRecord(
            account_id=account_id,
            token_hash=hashlib.sha256(token.encode("ascii")).hexdigest(),
            expires_at=now + timedelta(seconds=ttl_seconds),
            created_at=now,
        )
        with self.database.session() as session, session.begin():
            session.execute(
                delete(EmailVerificationRecord).where(
                    EmailVerificationRecord.account_id == account_id
                )
            )
            session.add(record)
        return token

    def verify_email(self, token: str) -> Account | None:
        if not 20 <= len(token) <= 256:
            return None
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        now = datetime.now(UTC)
        with self.database.session() as session, session.begin():
            verification = session.scalar(
                select(EmailVerificationRecord).where(
                    EmailVerificationRecord.token_hash == token_hash
                )
            )
            if verification is None:
                return None
            expires_at = verification.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=UTC)
            if expires_at <= now:
                session.delete(verification)
                return None
            record = session.get(AccountRecord, verification.account_id)
            if record is None or record.disabled:
                return None
            record.email_verified = True
            session.delete(verification)
            session.flush()
            result = _account(record)
        return result

    def ready(self) -> bool:
        return self.database.ready()
