"""Security, correlation, timing, and access-control middleware."""
from __future__ import annotations

import hashlib
import hmac
import re
import threading
import time
import uuid
from collections import defaultdict, deque
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from prometheus_client import Counter, Histogram
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from markinote_api.config import Settings
from markinote_api.platform.logging import request_id_var

HTTP_REQUESTS = Counter(
    "markinote_http_requests_total",
    "HTTP requests",
    ("method", "route", "status"),
)
HTTP_DURATION = Histogram(
    "markinote_http_request_duration_seconds",
    "HTTP request duration",
    ("method", "route"),
)

_MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SESSION_SALT = "markinote-api-session-v1"
_ACCESS_TOKEN_VERSION_CONTEXT = b"markinote-access-token-version-v1\0"


class AccessTokenExchange(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    access_token: SecretStr = Field(alias="accessToken", min_length=1, max_length=4096)


def _origin_key(value: str) -> tuple[str, str, int] | None:
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme.casefold() not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            return None
        scheme = parsed.scheme.casefold()
        return scheme, parsed.hostname.casefold().rstrip("."), parsed.port or (443 if scheme == "https" else 80)
    except ValueError:
        return None


def _same_origin(request: Request, origin: str, trusted_origins: set[tuple[str, str, int]]) -> bool:
    supplied = _origin_key(origin)
    accepted = {_origin_key(str(request.base_url)), *trusted_origins}
    accepted.discard(None)
    return supplied is not None and supplied in accepted


def _protected_api_path(path: str) -> bool:
    """Return whether the typed API requires deployment authentication."""
    return path.startswith("/api/v1") or path in {"/api/openapi.json"} or path.startswith(
        ("/api/docs", "/api/redoc")
    )


def _access_token_version(signing_secret: str, access_token: str) -> str:
    """Return a domain-separated, non-reversible version marker for session binding."""
    return hmac.new(
        signing_secret.encode("utf-8"),
        _ACCESS_TOKEN_VERSION_CONTEXT + access_token.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def install_middleware(app: FastAPI, settings: Settings) -> None:
    trusted_origins = {
        key
        for item in [*settings.trusted_origins, settings.public_origin]
        if item and (key := _origin_key(item)) is not None
    }
    configured_token = settings.access_token.get_secret_value() if settings.access_token else ""
    signing_secret = (
        settings.secret_key.get_secret_value()
        if settings.secret_key
        else configured_token
        if configured_token
        else uuid.uuid4().hex
    )
    session_serializer = URLSafeTimedSerializer(signing_secret, salt=_SESSION_SALT)
    access_token_version = _access_token_version(signing_secret, configured_token)
    auth_attempts: defaultdict[str, deque[float]] = defaultdict(deque)
    auth_attempts_guard = threading.Lock()

    def valid_session(cookie: str) -> bool:
        if not cookie:
            return False
        try:
            value = session_serializer.loads(cookie, max_age=settings.session_max_age_seconds)
        except (BadSignature, SignatureExpired):
            return False
        if not isinstance(value, dict):
            return False
        token_version = value.get("accessTokenVersion")
        return (
            value.get("authenticated") is True
            and value.get("version") == 2
            and isinstance(token_version, str)
            and hmac.compare_digest(token_version, access_token_version)
        )

    @app.middleware("http")
    async def platform_middleware(request: Request, call_next):
        supplied_request_id = request.headers.get("x-request-id", "").strip()
        request_id = supplied_request_id if _REQUEST_ID.fullmatch(supplied_request_id) else f"req_{uuid.uuid4().hex}"
        request.state.request_id = request_id
        context_token = request_id_var.set(request_id)
        started = time.perf_counter()

        def finalize(response):
            route = request.scope.get("route")
            route_name = getattr(route, "path", "unresolved")
            elapsed = time.perf_counter() - started
            if settings.metrics_enabled:
                HTTP_REQUESTS.labels(request.method, route_name, str(response.status_code)).inc()
                HTTP_DURATION.labels(request.method, route_name).observe(elapsed)

            security_headers = {
                "X-Request-ID": request_id,
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
                "Referrer-Policy": "no-referrer",
                "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
                "Cross-Origin-Opener-Policy": "same-origin",
                "Cross-Origin-Resource-Policy": "same-origin",
                "Content-Security-Policy": (
                    "default-src 'self'; base-uri 'self'; frame-ancestors 'none'; object-src 'none'; "
                    "script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; "
                    "font-src 'self' data:; connect-src 'self'"
                ),
            }
            for name, value in security_headers.items():
                if name not in response.headers:
                    response.headers[name] = value
            if (
                request.url.path.startswith("/api/")
                or request.url.path == "/auth/access-token"
            ) and "Cache-Control" not in response.headers:
                response.headers["Cache-Control"] = "no-store"
            if not request.url.path.startswith("/health/"):
                request.app.state.logger.info(
                    "http request completed",
                    extra={
                        "request_id": request_id,
                        "http_method": request.method,
                        "http_route": route_name,
                        "http_status": response.status_code,
                        "duration_ms": round(elapsed * 1000, 3),
                    },
                )
            return response

        try:
            if "access_token" in request.query_params:
                return finalize(JSONResponse(
                    {
                        "type": "https://markinote.local/problems/query-credential-forbidden",
                        "title": "Credential in URL rejected",
                        "status": 400,
                        "code": "query_credential_forbidden",
                        "detail": "Submit credentials only to the same-origin POST exchange.",
                        "requestId": request_id,
                    },
                    status_code=400,
                ))
            if request.url.path == "/auth/access-token" and request.method == "POST":
                client_key = request.client.host if request.client else "unknown"
                now = time.monotonic()
                with auth_attempts_guard:
                    attempts = auth_attempts[client_key]
                    while attempts and attempts[0] <= now - 60:
                        attempts.popleft()
                    if len(attempts) >= 5:
                        return finalize(JSONResponse(
                            {
                                "type": "https://markinote.local/problems/rate-limited",
                                "title": "Too many authentication attempts",
                                "status": 429,
                                "code": "authentication_rate_limited",
                                "detail": "Wait before trying another access token.",
                                "requestId": request_id,
                            },
                            status_code=429,
                            headers={"Retry-After": "60"},
                        ))
                    attempts.append(now)

            if request.method in _MUTATING_METHODS:
                if request.headers.get("sec-fetch-site", "").casefold() == "cross-site":
                    return finalize(JSONResponse(
                        {
                            "type": "https://markinote.local/problems/cross-site-request",
                            "title": "Cross-site request blocked",
                            "status": 403,
                            "code": "cross_site_request",
                            "detail": "Cross-site browser requests are not accepted.",
                            "requestId": request_id,
                        },
                        status_code=403,
                    ))
                origin = request.headers.get("origin")
                if origin and not _same_origin(request, origin, trusted_origins):
                    return finalize(JSONResponse(
                        {
                            "type": "https://markinote.local/problems/cross-site-request",
                            "title": "Cross-site request blocked",
                            "status": 403,
                            "code": "cross_site_request",
                            "detail": "The request origin is not trusted.",
                            "requestId": request_id,
                        },
                        status_code=403,
                    ))

            content_length = request.headers.get("content-length")
            if content_length:
                try:
                    request_size = int(content_length)
                except ValueError:
                    request_size = -1
                if request_size < 0 or request_size > settings.max_request_bytes:
                    return finalize(JSONResponse(
                        {
                            "type": "https://markinote.local/problems/request-too-large",
                            "title": "Request too large",
                            "status": 413,
                            "code": "request_too_large",
                            "detail": "The request body exceeds the configured limit.",
                            "requestId": request_id,
                        },
                        status_code=413,
                    ))

            if request.method in _MUTATING_METHODS:
                chunks: list[bytes] = []
                received = 0
                async for chunk in request.stream():
                    received += len(chunk)
                    if received > settings.max_request_bytes:
                        return finalize(JSONResponse(
                            {
                                "type": "https://markinote.local/problems/request-too-large",
                                "title": "Request too large",
                                "status": 413,
                                "code": "request_too_large",
                                "detail": "The streamed request body exceeds the configured limit.",
                                "requestId": request_id,
                            },
                            status_code=413,
                        ))
                    chunks.append(chunk)
                # BaseHTTPMiddleware replays a cached body to the downstream app.
                request._body = b"".join(chunks)

            if configured_token and _protected_api_path(request.url.path):
                cookie_valid = valid_session(request.cookies.get(settings.session_cookie_name, ""))
                authorization = request.headers.get("authorization", "")
                bearer_valid = False
                if authorization.lower().startswith("bearer "):
                    bearer_valid = hmac.compare_digest(authorization[7:].strip(), configured_token)
                if not cookie_valid and not bearer_valid:
                    return finalize(JSONResponse(
                        {
                            "type": "https://markinote.local/problems/authentication-required",
                            "title": "Authentication required",
                            "status": 401,
                            "code": "authentication_required",
                            "detail": "A valid access token is required.",
                            "requestId": request_id,
                        },
                        status_code=401,
                        headers={"WWW-Authenticate": "Bearer"},
                    ))

            response = await call_next(request)
            return finalize(response)
        finally:
            request_id_var.reset(context_token)

    @app.post("/auth/access-token", include_in_schema=False)
    async def exchange_access_token(request: Request, payload: AccessTokenExchange):
        origin = request.headers.get("origin", "")
        if not origin or not _same_origin(request, origin, trusted_origins):
            return JSONResponse(
                {
                    "code": "same_origin_required",
                    "detail": "A same-origin Origin header is required.",
                },
                status_code=403,
            )
        supplied_token = payload.access_token.get_secret_value()
        if not configured_token or not hmac.compare_digest(supplied_token, configured_token):
            return JSONResponse(
                {"code": "invalid_access_token", "detail": "Invalid access token."},
                status_code=401,
            )
        response = JSONResponse({"authenticated": True})
        response.set_cookie(
            settings.session_cookie_name,
            session_serializer.dumps(
                {
                    "authenticated": True,
                    "version": 2,
                    "accessTokenVersion": access_token_version,
                }
            ),
            httponly=True,
            secure=settings.environment == "production",
            samesite="strict",
            max_age=settings.session_max_age_seconds,
            path="/",
        )
        return response
