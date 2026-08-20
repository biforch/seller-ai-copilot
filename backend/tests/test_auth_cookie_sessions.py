"""S4b1 revocable cookie session and CSRF tests."""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.api.amazon_oauth_deps import get_amazon_oauth_service, get_amazon_oauth_service_factory
from app.core.auth_session_constants import CSRF_COOKIE_NAME, CSRF_HEADER_NAME, SESSION_COOKIE_NAME
from app.core.auth_session_tokens import hash_session_secret
from app.core.config import Settings, settings
from app.core.csrf import extract_request_origin, origin_is_allowed
from app.core.exceptions import (
    AUTH_CSRF_INVALID,
    AUTH_ORIGIN_INVALID,
    AUTH_SESSION_INVALID,
)
from app.core.rate_limit import limiter
from app.integrations.amazon.config import AmazonEndpointMode, AmazonSettings
from app.main import app
from app.models.amazon_oauth_state import OAuthStateIntent
from app.models.auth_session import AuthSession
from app.services.amazon_oauth_service import AmazonOAuthStartResult
from tests.integrations.amazon.conftest import TEST_CLIENT_ID, TEST_CLIENT_SECRET

CANARY_JWT = "canary.jwt.token.value.must-not-leak"
CANARY_CSRF = "canary-csrf-token-value-must-not-leak"
CANARY_JTI = "canary-jti-value-must-not-leak"
TEST_ORIGIN = "http://localhost:3000"
LOGIN_URL = "/api/v1/auth/login"
LOGOUT_URL = "/api/v1/auth/logout"
ME_URL = "/api/v1/auth/me"
OAUTH_START_URL = "/api/v1/amazon/oauth/start"
OAUTH_CALLBACK_URL = "/api/v1/amazon/oauth/callback"


@pytest.fixture(autouse=True)
def reset_rate_limits():
    limiter.reset()
    yield
    limiter.reset()


@pytest.fixture
def enable_cookie_sessions(monkeypatch):
    monkeypatch.setattr(settings, "COOKIE_SESSION_ENABLED", True)
    monkeypatch.setattr(settings, "SESSION_COOKIE_SECURE", False)
    monkeypatch.setattr(settings, "SESSION_TTL_MINUTES", 30)


def _set_cookie_headers(response) -> list[str]:
    if hasattr(response.headers, "get_list"):
        return response.headers.get_list("set-cookie")
    raw = response.headers.get("set-cookie", "")
    return [raw] if raw else []


def _cookie_login(client, email: str, password: str = "Password1"):
    return client.post(
        LOGIN_URL,
        json={"email": email, "password": password},
    )


def _csrf_headers(client) -> dict[str, str]:
    csrf = client.cookies.get(CSRF_COOKIE_NAME)
    assert csrf
    return {
        CSRF_HEADER_NAME: csrf,
        "Origin": TEST_ORIGIN,
    }


class FakeOAuthService:
    def start_authorization(self, **kwargs: Any) -> AmazonOAuthStartResult:
        return AmazonOAuthStartResult(
            authorization_url="https://sellercentral.amazon.com/apps/authorize/consent?state=test",
            marketplace_code="US",
            region="na",
            expires_at=datetime.now(UTC) + timedelta(minutes=10),
        )


@pytest.fixture
def oauth_service_override(monkeypatch):
    oauth_settings = AmazonSettings(
        enabled=True,
        oauth_enabled=True,
        lwa_client_id=TEST_CLIENT_ID,
        lwa_client_secret=TEST_CLIENT_SECRET,
        lwa_token_url="https://mock.lwa.local/auth/o2/token",
        sp_api_region="na",
        endpoint_mode=AmazonEndpointMode.MOCK,
        user_agent="SellerAI-Copilot-Test/1.0.0 (Language=Python)",
        environment="testing",
        application_id="amzn1.sp.solution.test-app",
        oauth_redirect_uri="https://api.oauth.test/api/v1/amazon/oauth/callback",
        oauth_frontend_success_url="https://app.oauth.test/oauth/success",
        oauth_frontend_error_url="https://app.oauth.test/oauth/error",
        oauth_consent_version="beta",
    )
    service = FakeOAuthService()

    def factory_provider():
        def factory() -> FakeOAuthService:
            return service

        return factory

    monkeypatch.setattr("app.api.amazon_oauth._amazon_settings", lambda: oauth_settings)
    app.dependency_overrides[get_amazon_oauth_service] = lambda: service
    app.dependency_overrides[get_amazon_oauth_service_factory] = factory_provider
    yield service
    app.dependency_overrides.pop(get_amazon_oauth_service, None)
    app.dependency_overrides.pop(get_amazon_oauth_service_factory, None)


def test_auth_session_model_repr_is_redacted(db_session: Session, user_factory):
    user = user_factory("repr-redaction@example.com")
    record = AuthSession(
        user_id=user.id,
        jti_hash=hash_session_secret(CANARY_JTI),
        csrf_token_hash=hash_session_secret(CANARY_CSRF),
        expires_at=datetime.now(UTC) + timedelta(minutes=30),
    )
    db_session.add(record)
    db_session.flush()
    rendered = repr(record)
    assert CANARY_JTI not in rendered
    assert CANARY_CSRF not in rendered
    assert "AuthSession" in rendered


def test_database_stores_only_hashes(
    db_session: Session, user_factory, enable_cookie_sessions, client
):
    user = user_factory("hash-only@example.com")
    response = _cookie_login(client, user.email)
    assert response.status_code == 200

    rows = db_session.query(AuthSession).filter(AuthSession.user_id == user.id).all()
    assert len(rows) == 1
    row = rows[0]
    assert len(row.jti_hash) == 64
    assert len(row.csrf_token_hash) == 64
    assert re.fullmatch(r"[0-9a-f]{64}", row.jti_hash)
    assert CANARY_JWT not in row.jti_hash
    assert CANARY_CSRF not in row.csrf_token_hash
    assert client.cookies.get(SESSION_COOKIE_NAME) not in (row.jti_hash, row.csrf_token_hash)


def test_login_cookie_attributes(enable_cookie_sessions, client, user_factory):
    user = user_factory("cookie-attrs@example.com")
    response = _cookie_login(client, user.email)
    assert response.status_code == 200

    headers = _set_cookie_headers(response)
    session_header = next(h for h in headers if h.startswith(f"{SESSION_COOKIE_NAME}="))
    csrf_header = next(h for h in headers if h.startswith(f"{CSRF_COOKIE_NAME}="))

    assert "HttpOnly" in session_header
    assert "HttpOnly" not in csrf_header
    assert "Path=/" in session_header
    assert "Path=/" in csrf_header
    assert "samesite=lax" in session_header.lower()
    assert "Domain=" not in session_header
    assert "Max-Age=1800" in session_header


def test_staging_rejects_insecure_session_cookie():
    with pytest.raises(ValidationError, match="SESSION_COOKIE_SECURE"):
        Settings(
            ENVIRONMENT="staging",
            DATABASE_URL="postgresql://user:pass@localhost:5432/sellerai_staging",
            JWT_SECRET_KEY="staging-jwt-secret-key-min-32-chars",
            OPENAI_API_KEY="staging-openai-key",
            CORS_ORIGINS="https://app.example.com",
            DEBUG=False,
            SESSION_COOKIE_SECURE=False,
        )


def test_production_rejects_insecure_session_cookie():
    with pytest.raises(ValidationError, match="SESSION_COOKIE_SECURE"):
        Settings(
            ENVIRONMENT="production",
            DATABASE_URL="postgresql://user:pass@localhost:5432/sellerai_prod",
            JWT_SECRET_KEY="production-jwt-secret-key-min-32",
            OPENAI_API_KEY="production-openai-key",
            CORS_ORIGINS="https://app.example.com",
            DEBUG=False,
            SESSION_COOKIE_SECURE=False,
        )


def test_session_fixation_creates_new_jti(enable_cookie_sessions, client, user_factory, db_session):
    user = user_factory("fixation@example.com")
    first = _cookie_login(client, user.email)
    assert first.status_code == 200
    first_hash = (
        db_session.query(AuthSession.jti_hash).filter(AuthSession.user_id == user.id).scalar()
    )

    second = _cookie_login(client, user.email)
    assert second.status_code == 200
    hashes = [
        row.jti_hash
        for row in db_session.query(AuthSession).filter(AuthSession.user_id == user.id).all()
    ]
    assert len(hashes) == 2
    assert first_hash in hashes
    assert len(set(hashes)) == 2


def test_cookie_login_response_excludes_access_token(
    enable_cookie_sessions, client, user_factory, caplog
):
    user = user_factory("no-body-token@example.com")
    with caplog.at_level(logging.ERROR):
        response = _cookie_login(client, user.email)
    assert response.status_code == 200
    body = response.json()
    assert "access_token" not in body["data"]
    assert body["data"]["token_type"] == "cookie"
    assert CANARY_JWT not in response.text
    assert CANARY_JWT not in caplog.text


def test_cookie_me_success(enable_cookie_sessions, client, user_factory):
    user = user_factory("me-cookie@example.com")
    login = _cookie_login(client, user.email)
    assert login.status_code == 200
    response = client.get(ME_URL)
    assert response.status_code == 200
    assert response.json()["data"]["email"] == user.email


def test_missing_session_cookie_returns_403(enable_cookie_sessions, client):
    response = client.get(ME_URL)
    assert response.status_code == 403


def test_tampered_session_cookie_returns_401(enable_cookie_sessions, client, user_factory):
    user = user_factory("tampered@example.com")
    _cookie_login(client, user.email)
    client.cookies.set(SESSION_COOKIE_NAME, CANARY_JWT)
    response = client.get(ME_URL)
    assert response.status_code == 401
    assert response.json()["error_code"] == AUTH_SESSION_INVALID


def test_revoked_session_returns_401(enable_cookie_sessions, client, user_factory, db_session):
    user = user_factory("revoked@example.com")
    _cookie_login(client, user.email)
    row = db_session.query(AuthSession).filter(AuthSession.user_id == user.id).one()
    row.revoked_at = datetime.now(UTC)
    db_session.flush()

    response = client.get(ME_URL)
    assert response.status_code == 401
    assert response.json()["error_code"] == AUTH_SESSION_INVALID
    assert CANARY_JWT not in response.text


def test_expired_session_returns_401(enable_cookie_sessions, client, user_factory, db_session):
    user = user_factory("expired@example.com")
    _cookie_login(client, user.email)
    row = db_session.query(AuthSession).filter(AuthSession.user_id == user.id).one()
    row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db_session.flush()

    response = client.get(ME_URL)
    assert response.status_code == 401
    assert response.json()["error_code"] == AUTH_SESSION_INVALID


def test_logout_revokes_session(enable_cookie_sessions, client, user_factory, db_session):
    user = user_factory("logout@example.com")
    _cookie_login(client, user.email)
    session_cookie = client.cookies.get(SESSION_COOKIE_NAME)
    response = client.post(LOGOUT_URL, headers=_csrf_headers(client))
    assert response.status_code == 200

    row = db_session.query(AuthSession).filter(AuthSession.user_id == user.id).one()
    assert row.revoked_at is not None

    client.cookies.set(SESSION_COOKIE_NAME, session_cookie)
    retry = client.get(ME_URL)
    assert retry.status_code == 401


def test_logout_is_idempotent_on_repeat(enable_cookie_sessions, client, user_factory, db_session):
    user = user_factory("logout-repeat@example.com")
    _cookie_login(client, user.email)
    headers = _csrf_headers(client)
    cookies = dict(client.cookies)
    first = client.post(LOGOUT_URL, headers=headers, cookies=cookies)
    second = client.post(LOGOUT_URL, headers=headers, cookies=cookies)
    assert first.status_code == 200
    assert second.status_code == 200
    row = db_session.query(AuthSession).filter(AuthSession.user_id == user.id).one()
    assert row.revoked_at is not None


def test_origin_allowlist_rejects_foreign_origin(monkeypatch):
    monkeypatch.setattr(settings, "CORS_ORIGINS", "http://localhost:3000")
    assert origin_is_allowed(TEST_ORIGIN) is True
    assert origin_is_allowed("https://evil.example.com") is False
    assert (
        extract_request_origin(
            type("Req", (), {"headers": {"referer": "https://evil.example.com/path"}})()
        )
        == "https://evil.example.com"
    )


def test_invalid_origin_rejected(
    enable_cookie_sessions, client, user_factory, db_session, monkeypatch
):
    user = user_factory("origin-invalid@example.com")
    _cookie_login(client, user.email)

    def _reject(_origin: str | None) -> bool:
        return False

    monkeypatch.setattr("app.core.csrf.origin_is_allowed", _reject)
    response = client.post(LOGOUT_URL, headers=_csrf_headers(client))
    assert response.status_code == 403
    assert response.json()["error_code"] == AUTH_ORIGIN_INVALID


def test_csrf_missing_rejected(enable_cookie_sessions, client, user_factory):
    user = user_factory("csrf-missing@example.com")
    _cookie_login(client, user.email)
    response = client.post(LOGOUT_URL, headers={"Origin": TEST_ORIGIN})
    assert response.status_code == 403
    assert response.json()["error_code"] == AUTH_CSRF_INVALID


def test_csrf_mismatch_rejected(enable_cookie_sessions, client, user_factory):
    user = user_factory("csrf-wrong@example.com")
    _cookie_login(client, user.email)
    response = client.post(
        LOGOUT_URL,
        headers={CSRF_HEADER_NAME: "wrong-token", "Origin": TEST_ORIGIN},
    )
    assert response.status_code == 403
    assert response.json()["error_code"] == AUTH_CSRF_INVALID


def test_csrf_cross_session_rejected(enable_cookie_sessions, client, user_factory):
    first = user_factory("csrf-owner@example.com")
    second = user_factory("csrf-other@example.com")
    _cookie_login(client, first.email)
    foreign_csrf = client.cookies.get(CSRF_COOKIE_NAME)
    _cookie_login(client, second.email)

    response = client.post(
        LOGOUT_URL,
        headers={CSRF_HEADER_NAME: foreign_csrf, "Origin": TEST_ORIGIN},
    )
    assert response.status_code == 403
    assert response.json()["error_code"] == AUTH_CSRF_INVALID


def test_bearer_path_regression_without_csrf(
    client, user_factory, auth_header, enable_cookie_sessions
):
    user = user_factory("bearer-regression@example.com")
    response = client.get("/api/v1/projects", headers=auth_header(user))
    assert response.status_code == 200


def test_bearer_login_still_returns_access_token_when_cookie_disabled(client, user_factory):
    user = user_factory("bearer-login@example.com")
    response = client.post(
        LOGIN_URL,
        json={"email": user.email, "password": "Password1"},
    )
    assert response.status_code == 200
    assert response.json()["data"]["access_token"]


def test_oauth_start_requires_csrf_in_cookie_mode(
    enable_cookie_sessions,
    client,
    user_factory,
    oauth_service_override,
):
    user = user_factory("oauth-cookie@example.com")
    _cookie_login(client, user.email)
    denied = client.post(
        OAUTH_START_URL,
        json={
            "marketplace_code": "US",
            "intent": OAuthStateIntent.CONNECT,
            "target_account_id": None,
        },
        headers={"Origin": TEST_ORIGIN},
    )
    assert denied.status_code == 403

    allowed = client.post(
        OAUTH_START_URL,
        json={
            "marketplace_code": "US",
            "intent": OAuthStateIntent.CONNECT,
        },
        headers=_csrf_headers(client),
    )
    assert allowed.status_code == 200, allowed.text


def test_oauth_callback_get_unaffected_by_csrf(enable_cookie_sessions, client):
    response = client.get(
        f"{OAUTH_CALLBACK_URL}?state=x&spapi_oauth_code=y&selling_partner_id=z",
    )
    assert response.status_code in {303, 400, 500}


def test_tenant_isolation_with_cookie_session(
    enable_cookie_sessions,
    client,
    user_factory,
    tenant_bundle,
):
    owner_bundle = tenant_bundle("cookie-owner")
    foreign_bundle = tenant_bundle("cookie-foreign-tenant")
    _cookie_login(client, owner_bundle["user"].email)

    foreign_project_id = foreign_bundle["project"].id
    response = client.get(f"/api/v1/projects/{foreign_project_id}")
    assert response.status_code == 404


def test_amazon_accounts_list_with_cookie_session(
    enable_cookie_sessions,
    client,
    user_factory,
):
    user = user_factory("amazon-cookie@example.com")
    _cookie_login(client, user.email)
    response = client.get("/api/v1/amazon/accounts")
    assert response.status_code == 200


def test_canary_not_leaked_on_auth_failure(enable_cookie_sessions, client, user_factory, caplog):
    user = user_factory("canary-fail@example.com")
    _cookie_login(client, user.email)
    client.cookies.set(SESSION_COOKIE_NAME, CANARY_JWT)
    with caplog.at_level(logging.DEBUG):
        response = client.get(ME_URL)
    assert response.status_code == 401
    assert CANARY_JWT not in response.text
    assert CANARY_JWT not in caplog.text


def test_session_ttl_configuration_bounds():
    with pytest.raises(ValidationError):
        Settings(
            ENVIRONMENT="testing",
            DATABASE_URL=settings.DATABASE_URL,
            SESSION_TTL_MINUTES=4,
        )
    with pytest.raises(ValidationError):
        Settings(
            ENVIRONMENT="testing",
            DATABASE_URL=settings.DATABASE_URL,
            SESSION_TTL_MINUTES=61,
        )
