"""S4d cookie-only authentication regressions."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from starlette import status

from app.api.amazon_oauth_deps import get_amazon_oauth_service, get_amazon_oauth_service_factory
from app.core.auth_session_constants import CSRF_COOKIE_NAME, CSRF_HEADER_NAME, SESSION_COOKIE_NAME
from app.core.config import settings
from app.core.csrf import validate_request_origin
from app.core.exceptions import AUTH_ORIGIN_INVALID, AppException
from app.core.rate_limit import limiter
from app.integrations.amazon.config import AmazonEndpointMode, AmazonSettings
from app.main import app
from app.models.amazon_oauth_state import OAuthStateIntent
from app.services.amazon_oauth_service import AmazonOAuthStartResult
from tests.integrations.amazon.conftest import TEST_CLIENT_ID, TEST_CLIENT_SECRET

LOGIN_URL = "/api/v1/auth/login"
OAUTH_CALLBACK_URL = "/api/v1/amazon/oauth/callback"
OAUTH_START_URL = "/api/v1/amazon/oauth/start"
TEST_ORIGIN = "http://localhost:3000"
CANARY = "canary-auth-value-must-not-leak"


@pytest.fixture(autouse=True)
def reset_rate_limits():
    limiter.reset()
    yield
    limiter.reset()


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


def _cookie_login(client, email: str, password: str = "Password1"):
    return client.post(
        LOGIN_URL,
        json={"email": email, "password": password},
        headers={"Origin": TEST_ORIGIN},
    )


def _csrf_headers(client) -> dict[str, str]:
    csrf = client.cookies.get(CSRF_COOKIE_NAME)
    assert csrf
    return {
        CSRF_HEADER_NAME: csrf,
        "Origin": TEST_ORIGIN,
    }


def _start_body():
    return {
        "marketplace_code": "US",
        "intent": OAuthStateIntent.CONNECT,
    }


def test_openapi_uses_cookie_auth_not_bearer():
    schema = app.openapi()
    assert "HTTPBearer" not in schema["components"].get("securitySchemes", {})
    assert schema["components"]["securitySchemes"]["cookieAuth"]["name"] == SESSION_COOKIE_NAME
    start = schema["paths"]["/api/v1/amazon/oauth/start"]["post"]
    callback = schema["paths"]["/api/v1/amazon/oauth/callback"]["get"]
    assert start["security"] == [{"cookieAuth": []}]
    assert "security" not in callback


def test_login_register_require_allowed_origin(client, user_factory):
    user = user_factory("origin-ok@example.com")
    login = client.post(
        LOGIN_URL,
        json={"email": user.email, "password": "Password1"},
        headers={"Origin": TEST_ORIGIN},
    )
    assert login.status_code == 200
    assert "access_token" not in login.json()["data"]

    register = client.post(
        "/api/v1/auth/register",
        json={"email": "origin-register@example.com", "password": "Password1!abc"},
        headers={"Origin": TEST_ORIGIN},
    )
    assert register.status_code == 200


def test_origin_allowlist_blocks_foreign_values():
    from app.core.csrf import normalize_origin, origin_is_allowed

    assert origin_is_allowed(TEST_ORIGIN) is True
    assert origin_is_allowed("https://evil.example.com") is False
    assert origin_is_allowed("http://localhost:3001") is False
    assert normalize_origin("http://user@localhost:3000") is None
    assert normalize_origin("http://localhost:3000.evil.com") == "http://localhost:3000.evil.com"
    assert origin_is_allowed("http://localhost:3000.evil.com") is False


def test_login_rejects_missing_origin(client, user_factory):
    user = user_factory("origin-missing@example.com")
    response = client.post(
        LOGIN_URL,
        json={"email": user.email, "password": "Password1"},
    )
    assert response.status_code == 403
    assert response.json()["error_code"] == AUTH_ORIGIN_INVALID


def test_validate_request_origin_rejects_malformed_values():
    class Req:
        headers = {"origin": "http://user@localhost:3000"}

    with pytest.raises(AppException) as exc_info:
        validate_request_origin(Req())  # type: ignore[arg-type]
    assert exc_info.value.error_code == AUTH_ORIGIN_INVALID


def test_oauth_callback_get_unaffected_by_origin_or_csrf(client):
    response = client.get(
        f"{OAUTH_CALLBACK_URL}?state=x&spapi_oauth_code=y&selling_partner_id=z",
    )
    assert response.status_code in {303, 400, 500}


def test_oauth_start_rate_limit_uses_distinct_session_buckets(
    client,
    user_factory,
    oauth_service_override,
):
    first = user_factory("oauth-limit-a@example.com")
    second = user_factory("oauth-limit-b@example.com")
    assert _cookie_login(client, first.email).status_code == 200
    first_csrf = _csrf_headers(client)
    client.post(OAUTH_START_URL, json=_start_body(), headers=first_csrf)

    assert _cookie_login(client, second.email).status_code == 200
    second_csrf = _csrf_headers(client)
    for _ in range(5):
        response = client.post(OAUTH_START_URL, json=_start_body(), headers=second_csrf)
        assert response.status_code == status.HTTP_200_OK

    blocked = client.post(OAUTH_START_URL, json=_start_body(), headers=second_csrf)
    assert blocked.status_code == status.HTTP_429_TOO_MANY_REQUESTS
    assert CANARY not in blocked.text

    client.cookies.clear()
    invalid = client.post(
        OAUTH_START_URL,
        json=_start_body(),
        headers={"Origin": TEST_ORIGIN, CSRF_HEADER_NAME: "missing"},
    )
    assert invalid.status_code in {401, 403, 429}
    assert CANARY not in invalid.text


def test_oauth_start_rate_limit_logs_do_not_leak_session_canaries(
    client,
    user_factory,
    oauth_service_override,
    caplog: pytest.LogCaptureFixture,
):
    user = user_factory("oauth-limit-log@example.com")
    _cookie_login(client, user.email)
    headers = _csrf_headers(client)
    session_cookie = client.cookies.get(SESSION_COOKIE_NAME)
    csrf_cookie = client.cookies.get(CSRF_COOKIE_NAME)
    assert session_cookie
    assert csrf_cookie

    with caplog.at_level(logging.WARNING):
        for _ in range(6):
            client.post(OAUTH_START_URL, json=_start_body(), headers=headers)

    joined = caplog.text
    assert session_cookie not in joined
    assert csrf_cookie not in joined
    assert str(user.id) not in joined


def test_testing_can_allow_missing_origin_when_explicitly_enabled(client, user_factory, monkeypatch):
    monkeypatch.setattr(settings, "AUTH_TESTING_ALLOW_MISSING_ORIGIN", True)
    user = user_factory("origin-testing-bypass@example.com")
    response = client.post(
        LOGIN_URL,
        json={"email": user.email, "password": "Password1"},
    )
    assert response.status_code == 200
