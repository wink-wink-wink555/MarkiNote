"""Registration, login, logout, and session endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from markinote_api.modules.accounts.auth import AccountAuth
from markinote_api.modules.accounts.credentials import CredentialVault
from markinote_api.modules.accounts.mailer import MailDeliveryError, VerificationMailer
from markinote_api.modules.accounts.provisioning import provision_default_workspace
from markinote_api.modules.accounts.store import (
    AccountAlreadyExistsError,
    AccountStore,
    InvalidEmailError,
)
from markinote_api.platform.errors import Problem

router = APIRouter(prefix="/auth", tags=["accounts"])
credential_router = APIRouter(prefix="/api/v1/account", tags=["accounts"])


class AuthConfigResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    mode: str
    registration_enabled: bool = Field(alias="registrationEnabled")


class Credentials(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=254)
    username: str = Field(default="", max_length=32)
    password: SecretStr = Field(min_length=10, max_length=128, repr=False)


class LoginCredentials(BaseModel):
    model_config = ConfigDict(extra="forbid")

    identity: str = Field(min_length=3, max_length=254)
    password: SecretStr = Field(min_length=10, max_length=128, repr=False)


class AccountSessionResponse(BaseModel):
    authenticated: bool
    email: str | None = None
    username: str | None = None


class CredentialUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    deepseek_api_key: SecretStr | None = Field(default=None, alias="deepseekApiKey", repr=False)
    tushare_token: SecretStr | None = Field(default=None, alias="tushareToken", repr=False)
    qveris_api_key: SecretStr | None = Field(default=None, alias="qverisApiKey", repr=False)


class CredentialStatus(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    deepseek_api_key: bool = Field(alias="deepseekApiKey")
    tushare_token: bool = Field(alias="tushareToken")
    qveris_api_key: bool = Field(alias="qverisApiKey")


class EmailRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=254)


class VerifyEmailRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: SecretStr = Field(min_length=20, max_length=256, repr=False)


class VerificationResponse(BaseModel):
    accepted: bool = True


def _components(request: Request) -> tuple[AccountStore, AccountAuth, VerificationMailer]:
    store = getattr(request.app.state, "account_store", None)
    auth = getattr(request.app.state, "account_auth", None)
    mailer = getattr(request.app.state, "verification_mailer", None)
    if (
        not isinstance(store, AccountStore)
        or not isinstance(auth, AccountAuth)
        or not isinstance(mailer, VerificationMailer)
    ):
        raise Problem(404, "account_auth_disabled", "Account authentication disabled", "Account login is not enabled.")
    return store, auth, mailer


@router.get("/config", response_model=AuthConfigResponse)
def auth_config(request: Request) -> dict[str, object]:
    settings = request.app.state.settings
    return {
        "mode": settings.auth_mode,
        "registrationEnabled": settings.registration_enabled,
    }


@router.get("/session", response_model=AccountSessionResponse)
def session(request: Request) -> dict[str, object]:
    account = getattr(request.state, "account", None)
    return {
        "authenticated": account is not None,
        "email": account.email if account is not None else None,
        "username": account.username if account is not None else None,
    }


@router.post("/register", response_model=AccountSessionResponse)
def register(body: Credentials, request: Request) -> JSONResponse:
    settings = request.app.state.settings
    if settings.auth_mode != "accounts" or not settings.registration_enabled:
        raise Problem(403, "registration_disabled", "Registration disabled", "New account registration is disabled.")
    store, _auth, mailer = _components(request)
    try:
        account = store.register(
            body.email,
            body.password.get_secret_value(),
            username=body.username,
        )
    except AccountAlreadyExistsError as error:
        raise Problem(409, "email_unavailable", "Email unavailable", "This email is already registered.") from error
    except (InvalidEmailError, ValueError) as error:
        raise Problem(422, "invalid_credentials", "Invalid account credentials", str(error)) from error
    token = store.create_verification(
        account.id,
        ttl_seconds=settings.email_verification_ttl_seconds,
    )
    try:
        provision_default_workspace(
            request.app.state.user_service_registry.get(account.id).document_service
        )
    except Exception:
        request.app.state.logger.exception("default account workspace provisioning failed")
        raise Problem(
            500,
            "workspace_provisioning_failed",
            "Workspace provisioning failed",
            "The account was created but its database workspace could not be initialized.",
        ) from None
    try:
        mailer.send_verification(account.email, token)
    except MailDeliveryError as error:
        raise Problem(
            503,
            "email_delivery_failed",
            "Verification email unavailable",
            "The account was created, but its verification email could not be delivered. Retry shortly.",
        ) from error
    return JSONResponse(
        {"authenticated": False, "email": account.email, "username": account.username},
        status_code=202,
    )


@router.post("/login", response_model=AccountSessionResponse)
def login(body: LoginCredentials, request: Request) -> JSONResponse:
    settings = request.app.state.settings
    if settings.auth_mode != "accounts":
        raise Problem(404, "account_auth_disabled", "Account authentication disabled", "Account login is not enabled.")
    store, auth, _mailer = _components(request)
    account = store.authenticate(body.identity, body.password.get_secret_value())
    if account is None:
        raise Problem(401, "invalid_login", "Invalid login", "The email or password is incorrect.")
    if not account.email_verified:
        raise Problem(403, "email_unverified", "Email not verified", "Verify this email address before signing in.")
    response = JSONResponse(
        {"authenticated": True, "email": account.email, "username": account.username}
    )
    auth.set_cookie(response, account)
    return response


@router.post("/verify-email", response_model=AccountSessionResponse)
def verify_email(body: VerifyEmailRequest, request: Request) -> JSONResponse:
    store, auth, _mailer = _components(request)
    account = store.verify_email(body.token.get_secret_value())
    if account is None:
        raise Problem(400, "invalid_verification", "Invalid verification link", "The verification link is invalid or expired.")
    response = JSONResponse(
        {"authenticated": True, "email": account.email, "username": account.username}
    )
    auth.set_cookie(response, account)
    return response


@router.post("/resend-verification", response_model=VerificationResponse)
def resend_verification(body: EmailRequest, request: Request) -> dict[str, bool]:
    settings = request.app.state.settings
    store, _auth, mailer = _components(request)
    account = store.account_by_email(body.email)
    if account is not None and not account.email_verified:
        token = store.create_verification(
            account.id,
            ttl_seconds=settings.email_verification_ttl_seconds,
        )
        try:
            mailer.send_verification(account.email, token)
        except MailDeliveryError:
            request.app.state.logger.error(
                "verification email delivery failed",
                extra={"request_id": request.state.request_id},
            )
    return {"accepted": True}


@router.post("/logout", response_model=AccountSessionResponse)
def logout(request: Request) -> JSONResponse:
    _store, auth, _mailer = _components(request)
    response = JSONResponse({"authenticated": False, "email": None, "username": None})
    auth.clear_cookie(response)
    return response


def _vault(request: Request) -> tuple[CredentialVault, str]:
    vault = getattr(request.app.state, "credential_vault", None)
    user_id = getattr(request.state, "user_id", None)
    if not isinstance(vault, CredentialVault) or not isinstance(user_id, str):
        raise Problem(401, "authentication_required", "Authentication required", "Sign in to manage credentials.")
    return vault, user_id


@credential_router.get("/credentials", response_model=CredentialStatus)
def credential_status(request: Request) -> dict[str, bool]:
    vault, user_id = _vault(request)
    values = vault.configured(user_id)
    return {
        "deepseekApiKey": values["deepseek_api_key"],
        "tushareToken": values["tushare_token"],
        "qverisApiKey": values["qveris_api_key"],
    }


@credential_router.put("/credentials", response_model=CredentialStatus)
def update_credentials(body: CredentialUpdate, request: Request) -> dict[str, bool]:
    vault, user_id = _vault(request)
    values: dict[str, str | None] = {}
    for field_name in body.model_fields_set:
        secret = getattr(body, field_name)
        values[field_name] = secret.get_secret_value() if secret is not None else None
    vault.set_many(user_id, values)
    return credential_status(request)
