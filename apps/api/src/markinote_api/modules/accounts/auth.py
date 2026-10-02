"""Signed account-session cookies."""
from __future__ import annotations

import uuid

from fastapi import Response
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from markinote_api.config import Settings
from markinote_api.modules.accounts.store import Account, AccountStore

_ACCOUNT_SESSION_SALT = "markinote-account-session-v1"


class AccountAuth:
    def __init__(self, settings: Settings, store: AccountStore):
        secret = (
            settings.secret_key.get_secret_value()
            if settings.secret_key
            else uuid.uuid4().hex
        )
        self.settings = settings
        self.store = store
        self.serializer = URLSafeTimedSerializer(secret, salt=_ACCOUNT_SESSION_SALT)

    def from_cookie(self, cookie: str) -> Account | None:
        if not cookie:
            return None
        try:
            value = self.serializer.loads(
                cookie,
                max_age=self.settings.session_max_age_seconds,
            )
        except (BadSignature, SignatureExpired):
            return None
        if not isinstance(value, dict) or value.get("version") != 1:
            return None
        account_id = value.get("accountId")
        session_version = value.get("sessionVersion")
        if not isinstance(account_id, str) or not isinstance(session_version, int):
            return None
        account = self.store.session_account(account_id, session_version)
        return account if account is not None and account.email_verified else None

    def set_cookie(self, response: Response, account: Account) -> None:
        response.set_cookie(
            self.settings.session_cookie_name,
            self.serializer.dumps(
                {
                    "version": 1,
                    "accountId": account.id,
                    "sessionVersion": account.session_version,
                }
            ),
            httponly=True,
            secure=self.settings.environment == "production",
            samesite="strict",
            max_age=self.settings.session_max_age_seconds,
            path="/",
        )

    def clear_cookie(self, response: Response) -> None:
        response.delete_cookie(
            self.settings.session_cookie_name,
            httponly=True,
            secure=self.settings.environment == "production",
            samesite="strict",
            path="/",
        )
