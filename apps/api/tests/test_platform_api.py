from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from starlette.exceptions import HTTPException

from markinote_api.application import create_application
from markinote_api.config import Settings


def test_production_configuration_fails_closed():
    with pytest.raises(ValidationError, match="access token"):
        Settings(environment="production")

    with pytest.raises(ValidationError, match="HTTPS origin"):
        Settings(
            environment="production",
            access_token="a" * 32,
            secret_key="b" * 48,
            public_origin="http://example.test",
        )

    with pytest.raises(ValidationError, match=r"trusted_hosts.*explicitly"):
        Settings(
            environment="production",
            access_token="a" * 32,
            secret_key="b" * 48,
            public_origin="https://notes.example.test",
        )

    with pytest.raises(ValidationError, match="include the public_origin hostname"):
        Settings(
            environment="production",
            access_token="a" * 32,
            secret_key="b" * 48,
            public_origin="https://notes.example.test",
            trusted_hosts=["api", "localhost"],
        )

    with pytest.raises(ValidationError, match=r"health checks.*internal monitoring"):
        Settings(
            environment="production",
            access_token="a" * 32,
            secret_key="b" * 48,
            public_origin="https://notes.example.test",
            trusted_hosts=["notes.example.test"],
        )

    configured = Settings(
        environment="production",
        access_token="a" * 32,
        secret_key="b" * 48,
        public_origin="https://notes.example.test",
        trusted_hosts=["notes.example.test", "127.0.0.1", "api"],
    )
    assert configured.environment == "production"

    for origin in ("https://notes.example.test:0", "https://notes.example.test:65536"):
        with pytest.raises(ValidationError, match="valid TCP port"):
            Settings(
                environment="production",
                access_token="a" * 32,
                secret_key="b" * 48,
                public_origin=origin,
                trusted_hosts=["notes.example.test"],
            )


@pytest.mark.parametrize(
    "field",
    ("max_library_bytes", "max_preview_bytes", "trash_max_items", "trash_max_bytes"),
)
@pytest.mark.parametrize("value", (0, -1))
def test_capacity_limits_fail_closed(field: str, value: int) -> None:
    with pytest.raises(ValidationError, match="limits must be positive"):
        Settings(**{field: value})


def test_ai_provider_fixture_is_test_only_and_pinned_to_the_isolated_origin() -> None:
    fixture_url = "http://fake-provider:8099"
    assert Settings(environment="test", ai_provider_fixture_url=fixture_url).ai_provider_fixture_url == fixture_url

    with pytest.raises(ValidationError, match="allowed only in the test environment"):
        Settings(environment="development", ai_provider_fixture_url=fixture_url)
    with pytest.raises(ValidationError, match="isolated http://fake-provider:8099 origin"):
        Settings(environment="test", ai_provider_fixture_url="https://api.deepseek.com")
    with pytest.raises(ValidationError, match="title generation to be disabled"):
        Settings(
            environment="test",
            ai_provider_fixture_url=fixture_url,
            ai_generate_titles=True,
        )


def test_trusted_host_rejects_unlisted_host_before_routing():
    client, temp = build_client()
    try:
        rejected = client.get("/health/live", headers={"Host": "attacker.example"})
        assert rejected.status_code == 400
        assert rejected.text == "Invalid host header"
        assert client.get("/health/live", headers={"Host": "testserver"}).status_code == 200
    finally:
        client.close()
        temp.cleanup()


def build_client(
    *,
    backend: str = "json",
    settings_overrides: dict[str, Any] | None = None,
    raise_server_exceptions: bool = True,
) -> tuple[TestClient, tempfile.TemporaryDirectory]:
    temp = tempfile.TemporaryDirectory()
    root = Path(temp.name)
    values: dict[str, Any] = dict(
        environment="test",
        library_folder=root / "library",
        conversations_folder=root / "conversations",
        backups_folder=root / "backups",
        trash_folder=root / "trash",
        conversation_backend=backend,
        database_url=f"sqlite:///{(root / 'test.db').as_posix()}",
        auto_create_database=True,
        serve_web_dist=False,
        json_logs=False,
    )
    values.update(settings_overrides or {})
    settings = Settings(**values)
    return TestClient(
        create_application(settings),
        raise_server_exceptions=raise_server_exceptions,
    ), temp


def test_health_and_security_headers():
    client, temp = build_client()
    try:
        response = client.get("/health/live")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["x-request-id"].startswith("req_")
    finally:
        client.close()
        temp.cleanup()


def test_http_exception_detail_is_not_reflected() -> None:
    client, temp = build_client()
    sentinel = "INTERNAL_PATH_AND_SECRET_CANNOT_ESCAPE"

    @client.app.get("/_test/http-exception")
    def raise_http_exception() -> None:
        raise HTTPException(status_code=409, detail=sentinel)

    try:
        response = client.get("/_test/http-exception")
        assert response.status_code == 409
        assert response.json()["detail"] == "The HTTP request was rejected."
        assert sentinel not in response.text
    finally:
        client.close()
        temp.cleanup()


def test_openapi_and_rendering_contract():
    client, temp = build_client()
    try:
        schema = client.get("/api/openapi.json")
        assert schema.status_code == 200
        assert "/api/v1/rendering/preview" in schema.json()["paths"]
        assert "/api/v1/operations/rollback" in schema.json()["paths"]
        response = client.post("/api/v1/rendering/preview", json={"markdown": "# Hello"})
        assert response.status_code == 200
        assert "<h1" in response.json()["html"]
    finally:
        client.close()
        temp.cleanup()


def test_rendering_preview_has_an_independent_configured_limit():
    client, temp = build_client(
        settings_overrides={"max_document_bytes": 32, "max_preview_bytes": 4}
    )
    try:
        response = client.post("/api/v1/rendering/preview", json={"markdown": "12345"})
        assert response.status_code == 413
        assert response.json()["code"] == "document_too_large"
        assert client.app.state.settings.max_preview_bytes == 4
    finally:
        client.close()
        temp.cleanup()


def test_access_token_is_exchanged_for_signed_http_only_session():
    raw_token = "do-not-persist-this-token"
    client, temp = build_client(
        settings_overrides={"access_token": raw_token, "secret_key": "test-signing-secret"}
    )
    try:
        unauthenticated = client.get("/api/v1")
        assert unauthenticated.status_code == 401
        assert unauthenticated.headers["x-request-id"].startswith("req_")
        assert unauthenticated.headers["cache-control"] == "no-store"
        response = client.post(
            "/auth/access-token",
            json={"accessToken": raw_token},
            headers={"Origin": "http://testserver"},
        )
        assert response.status_code == 200
        assert response.json() == {"authenticated": True}
        cookie = response.headers["set-cookie"]
        assert "HttpOnly" in cookie
        assert raw_token not in cookie
        assert client.get("/api/v1").status_code == 200

        # The primary credential must never travel in a URL or browser history.
        get_exchange = client.get(
            "/auth/access-token",
            params={"access_token": raw_token},
        )
        assert get_exchange.status_code == 400
        assert get_exchange.json()["code"] == "query_credential_forbidden"
    finally:
        client.close()
        temp.cleanup()


def test_access_token_rotation_immediately_revokes_existing_signed_session():
    signing_secret = "stable-and-separate-session-signing-secret"
    old_token = "old-access-token-that-will-be-rotated"
    new_token = "new-access-token-after-security-rotation"
    old_client, old_temp = build_client(
        settings_overrides={"access_token": old_token, "secret_key": signing_secret}
    )
    new_client = None
    new_temp = None
    try:
        exchanged = old_client.post(
            "/auth/access-token",
            json={"accessToken": old_token},
            headers={"Origin": "http://testserver"},
        )
        assert exchanged.status_code == 200
        signed_session = old_client.cookies.get("markinote_access")
        assert signed_session
        assert old_token not in signed_session

        # Keep the signing key stable so this specifically proves the access
        # token version binding, rather than ordinary signature invalidation.
        new_client, new_temp = build_client(
            settings_overrides={"access_token": new_token, "secret_key": signing_secret}
        )
        new_client.cookies.set("markinote_access", signed_session)
        revoked = new_client.get("/api/v1")
        assert revoked.status_code == 401
        assert revoked.json()["code"] == "authentication_required"

        assert new_client.get(
            "/api/v1",
            headers={"Authorization": f"Bearer {new_token}"},
        ).status_code == 200
    finally:
        old_client.close()
        old_temp.cleanup()
        if new_client is not None:
            new_client.close()
        if new_temp is not None:
            new_temp.cleanup()


def test_access_token_exchange_requires_same_origin_and_is_rate_limited():
    client, temp = build_client(
        settings_overrides={
            "access_token": "correct-access-token",
            "secret_key": "separate-test-signing-secret",
        }
    )
    try:
        cross_site = client.post(
            "/auth/access-token",
            json={"accessToken": "correct-access-token"},
            headers={"Origin": "https://attacker.example"},
        )
        assert cross_site.status_code == 403
        assert "set-cookie" not in cross_site.headers

        for _ in range(4):
            rejected = client.post(
                "/auth/access-token",
                json={"accessToken": "wrong-token"},
                headers={"Origin": "http://testserver"},
            )
            assert rejected.status_code == 401

        limited = client.post(
            "/auth/access-token",
            json={"accessToken": "correct-access-token"},
            headers={"Origin": "http://testserver"},
        )
        assert limited.status_code == 429
        assert limited.json()["code"] == "authentication_rate_limited"
        assert limited.headers["retry-after"] == "60"
        assert "set-cookie" not in limited.headers
    finally:
        client.close()
        temp.cleanup()


def test_mutation_origin_requires_exact_scheme_host_and_port():
    client, temp = build_client()
    try:
        rejected = client.post(
            "/api/v1/rendering/preview",
            headers={"Origin": "https://testserver"},
            json={"markdown": "hello"},
        )
        assert rejected.status_code == 403
        assert rejected.json()["code"] == "cross_site_request"
        accepted = client.post(
            "/api/v1/rendering/preview",
            headers={"Origin": "http://testserver"},
            json={"markdown": "hello"},
        )
        assert accepted.status_code == 200
    finally:
        client.close()
        temp.cleanup()


def test_chunked_request_body_is_limited_without_content_length():
    client, temp = build_client(settings_overrides={"max_request_bytes": 4})
    try:
        response = client.post(
            "/api/v1/rendering/preview",
            content=iter([b"123", b"45"]),
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 413
        assert response.json()["code"] == "request_too_large"
    finally:
        client.close()
        temp.cleanup()


def test_readiness_returns_503_when_dependency_directory_is_missing():
    client, temp = build_client()
    try:
        client.app.state.settings.backups_folder = client.app.state.settings.backups_folder / "missing"
        response = client.get("/health/ready")
        assert response.status_code == 503
        assert response.json()["status"] == "degraded"
        assert response.json()["checks"]["backups"] is False
    finally:
        client.close()
        temp.cleanup()


def test_database_conversation_round_trip():
    client, temp = build_client(backend="database")
    try:
        service = client.app.state.conversation_service
        conversation = service.create("hello", "system")
        conversation["messages"].extend(
            [
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "world"},
            ]
        )
        service.repository.save(conversation)
        listed = client.get("/api/v1/conversations")
        assert listed.status_code == 200
        assert listed.json()["items"][0]["id"] == conversation["id"]
        assert listed.json()["items"][0]["message_count"] == 2
    finally:
        client.close()
        database = client.app.state.database
        if database is not None:
            database.close()
        temp.cleanup()


def test_database_readiness_detects_missing_migration_schema():
    client, temp = build_client(
        backend="database", settings_overrides={"auto_create_database": False}
    )
    try:
        response = client.get("/health/ready")
        assert response.status_code == 503
        assert response.json()["checks"]["database"] is False
    finally:
        client.close()
        database = client.app.state.database
        if database is not None:
            database.close()
        temp.cleanup()
