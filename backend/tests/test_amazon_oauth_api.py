"""HTTP API tests for Amazon OAuth start and callback endpoints."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import status

from app.api.amazon_oauth_deps import get_amazon_oauth_service, get_amazon_oauth_service_factory
from app.core.exceptions import (
    AMAZON_OAUTH_MARKETPLACE_PUBLIC_MESSAGE,
    public_message_for_amazon_error_code,
)
from app.integrations.amazon.config import AmazonEndpointMode, AmazonSettings
from app.integrations.amazon.exceptions import (
    AMAZON_ACCOUNT_NOT_FOUND,
    AMAZON_CONFIG_INVALID,
    AMAZON_OAUTH_ACCOUNT_PERSIST_FAILED,
    AMAZON_OAUTH_DISABLED,
    AMAZON_OAUTH_INTENT_INVALID,
    AMAZON_OAUTH_MARKETPLACE_INVALID,
    AMAZON_OAUTH_REDIRECT_INVALID,
    AMAZON_OAUTH_SELLER_ALREADY_LINKED,
    AMAZON_OAUTH_SELLER_INVALID,
    AMAZON_OAUTH_STATE_EXPIRED,
    AMAZON_OAUTH_STATE_INVALID,
    AMAZON_OAUTH_STATE_REPLAY,
    AMAZON_OAUTH_TOKEN_EXCHANGE_FAILED,
    AmazonError,
    amazon_config_invalid_error,
    amazon_oauth_account_persist_failed_error,
    amazon_oauth_disabled_error,
    amazon_oauth_state_expired_error,
    amazon_oauth_state_invalid_error,
    amazon_oauth_state_replay_error,
    amazon_oauth_token_exchange_failed_error,
)
from app.main import app
from app.models.amazon_oauth_state import OAuthStateIntent
from app.services.amazon_account_service import AmazonAccountSummary
from app.services.amazon_oauth_service import AmazonOAuthStartResult
from tests.integrations.amazon.conftest import TEST_CLIENT_ID, TEST_CLIENT_SECRET

START_URL = "/api/v1/amazon/oauth/start"
CALLBACK_URL = "/api/v1/amazon/oauth/callback"
SUCCESS_URL = "https://app.oauth.test/oauth/success"
ERROR_URL = "https://app.oauth.test/oauth/error"
CANARY_STATE = "C" * 43
CANARY_CODE = "CANARY_OAUTH_CODE_SECRET_MARKER"
CANARY_SELLER = "CANARYSELLER123456"
CANARY_SECRET = "CANARY_CLIENT_SECRET_MARKER"
CANARY_MESSAGE = f"CANARY_DYNAMIC_MESSAGE_{CANARY_SECRET}"
MALICIOUS_ERROR_CODE = "EVIL\r\nLocation: https://evil.example/\x7fCANARY"
FIXED_START_URL = (
    "https://sellercentral.amazon.com/apps/authorize/consent"
    f"?application_id=app-id&state={CANARY_STATE}&version=beta"
)


class FakeOAuthService:
    start_calls: list[dict[str, Any]] = []
    complete_calls: list[dict[str, Any]] = []
    start_error: AmazonError | None = None
    complete_error: AmazonError | None = None
    complete_unexpected: bool = False
    complete_cancelled: bool = False
    factory_build_count: int = 0

    def __init__(self) -> None:
        self.start_result = AmazonOAuthStartResult(
            authorization_url=FIXED_START_URL,
            marketplace_code="US",
            region="na",
            expires_at=datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
        )
        self.complete_result = AmazonAccountSummary(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            region="na",
            endpoint_mode="production",
            status="active",
            last_verified_at=None,
            created_at=datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
            updated_at=datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
        )

    @classmethod
    def reset(cls) -> None:
        cls.start_calls = []
        cls.complete_calls = []
        cls.start_error = None
        cls.complete_error = None
        cls.complete_unexpected = False
        cls.complete_cancelled = False
        cls.factory_build_count = 0

    def start_authorization(self, **kwargs) -> AmazonOAuthStartResult:
        self.start_calls.append(kwargs)
        if self.start_error is not None:
            raise self.start_error
        return self.start_result

    async def complete_authorization(self, **kwargs) -> AmazonAccountSummary:
        self.complete_calls.append(kwargs)
        if self.complete_cancelled:
            raise asyncio.CancelledError()
        if self.complete_unexpected:
            raise RuntimeError(f"unexpected failure {CANARY_CODE}")
        if self.complete_error is not None:
            raise self.complete_error
        return self.complete_result


def _make_oauth_factory_override(service: FakeOAuthService):
    def factory_provider():
        def factory() -> FakeOAuthService:
            service.factory_build_count += 1
            return service

        return factory

    return factory_provider


@pytest.fixture
def fake_oauth_service(
    monkeypatch: pytest.MonkeyPatch,
    oauth_api_settings: AmazonSettings,
) -> FakeOAuthService:
    FakeOAuthService.reset()
    service = FakeOAuthService()

    app.dependency_overrides[get_amazon_oauth_service] = lambda: service
    app.dependency_overrides[get_amazon_oauth_service_factory] = _make_oauth_factory_override(service)
    monkeypatch.setattr("app.api.amazon_oauth._amazon_settings", lambda: oauth_api_settings)
    yield service
    app.dependency_overrides.pop(get_amazon_oauth_service, None)
    app.dependency_overrides.pop(get_amazon_oauth_service_factory, None)


@pytest.fixture
def failing_oauth_factory_override(
    monkeypatch: pytest.MonkeyPatch,
    oauth_api_settings: AmazonSettings,
):
    build_count = {"n": 0}

    def factory_provider():
        def factory():
            build_count["n"] += 1
            raise amazon_config_invalid_error("Amazon token encryption is not configured")

        return factory

    monkeypatch.setattr("app.api.amazon_oauth._amazon_settings", lambda: oauth_api_settings)
    app.dependency_overrides[get_amazon_oauth_service_factory] = factory_provider
    yield build_count
    app.dependency_overrides.pop(get_amazon_oauth_service_factory, None)


@pytest.fixture
def oauth_api_settings() -> AmazonSettings:
    return AmazonSettings(
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
        oauth_frontend_success_url=SUCCESS_URL,
        oauth_frontend_error_url=ERROR_URL,
        oauth_consent_version="beta",
    )


@pytest.fixture
def oauth_frontend_settings(oauth_api_settings: AmazonSettings, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("app.api.amazon_oauth._amazon_settings", lambda: oauth_api_settings)
    return oauth_api_settings


def _start_body(**overrides) -> dict:
    body = {
        "marketplace_code": "US",
        "intent": OAuthStateIntent.CONNECT,
        "target_account_id": None,
    }
    body.update(overrides)
    return body


def _callback_params(**overrides) -> dict[str, str]:
    params = {
        "state": CANARY_STATE,
        "spapi_oauth_code": "ANspapi-oauth-code-placeholder",
        "selling_partner_id": "CallbackApiSeller1",
    }
    params.update(overrides)
    return params


def _assert_start_cache_headers(response) -> None:
    assert response.headers.get("Cache-Control") == "no-store"
    assert response.headers.get("Pragma") == "no-cache"


def _assert_callback_security_headers(response) -> None:
    assert response.headers.get("Cache-Control") == "no-store"
    assert response.headers.get("Pragma") == "no-cache"
    assert response.headers.get("Referrer-Policy") == "no-referrer"
    assert response.headers.get("X-Content-Type-Options") == "nosniff"


def _error_location_query(response) -> dict[str, list[str]]:
    location = response.headers["location"]
    return parse_qs(urlparse(location).query)


def test_start_connect_success(client, user_factory, auth_header, fake_oauth_service: FakeOAuthService):
    user = user_factory("oauth-api-connect@example.com")
    response = client.post(
        START_URL,
        headers=auth_header(user),
        json=_start_body(),
    )
    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert body["code"] == 200
    assert set(body["data"]) == {"authorization_url", "marketplace_code", "region", "expires_at"}
    assert body["data"]["marketplace_code"] == "US"
    assert CANARY_STATE in body["data"]["authorization_url"]
    assert "state" not in body["data"]
    _assert_start_cache_headers(response)
    assert len(fake_oauth_service.start_calls) == 1
    assert fake_oauth_service.start_calls[0]["user_id"] == user.id


def test_start_reauthorize_success(client, user_factory, auth_header, fake_oauth_service: FakeOAuthService):
    user = user_factory("oauth-api-reauth@example.com")
    account_id = uuid.uuid4()
    response = client.post(
        START_URL,
        headers=auth_header(user),
        json=_start_body(intent=OAuthStateIntent.REAUTHORIZE, target_account_id=str(account_id)),
    )
    assert response.status_code == status.HTTP_200_OK
    call = fake_oauth_service.start_calls[0]
    assert call["intent"] == OAuthStateIntent.REAUTHORIZE
    assert call["target_account_id"] == account_id


def test_start_unauthenticated(client, fake_oauth_service: FakeOAuthService):
    response = client.post(START_URL, json=_start_body())
    assert response.status_code in {status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN}
    assert fake_oauth_service.start_calls == []


def test_start_oauth_disabled(client, user_factory, auth_header, fake_oauth_service: FakeOAuthService):
    user = user_factory("oauth-api-disabled@example.com")
    fake_oauth_service.start_error = amazon_oauth_disabled_error()
    response = client.post(START_URL, headers=auth_header(user), json=_start_body())
    assert response.status_code == 503
    assert response.json()["error_code"] == AMAZON_OAUTH_DISABLED


@pytest.mark.parametrize(
    ("body", "expected_code"),
    [
        (_start_body(marketplace_code="ZZ"), AMAZON_OAUTH_MARKETPLACE_INVALID),
        (_start_body(intent=OAuthStateIntent.REAUTHORIZE), AMAZON_OAUTH_INTENT_INVALID),
    ],
)
def test_start_business_validation_errors(
    client,
    user_factory,
    auth_header,
    fake_oauth_service: FakeOAuthService,
    body,
    expected_code: str,
):
    user = user_factory(f"oauth-api-{expected_code.lower()}@example.com")
    fake_oauth_service.start_error = AmazonError(
        "validation",
        error_code=expected_code,
        status_code=400,
    )
    response = client.post(START_URL, headers=auth_header(user), json=body)
    assert response.json()["error_code"] == expected_code


def test_start_cross_tenant_target_account(
    client,
    user_factory,
    auth_header,
    fake_oauth_service: FakeOAuthService,
):
    user = user_factory("oauth-api-cross-tenant@example.com")
    fake_oauth_service.start_error = AmazonError(
        "not found",
        error_code=AMAZON_ACCOUNT_NOT_FOUND,
        status_code=404,
    )
    response = client.post(
        START_URL,
        headers=auth_header(user),
        json=_start_body(
            intent=OAuthStateIntent.REAUTHORIZE,
            target_account_id=str(uuid.uuid4()),
        ),
    )
    assert response.json()["error_code"] == AMAZON_ACCOUNT_NOT_FOUND


@pytest.mark.parametrize(
    "extra",
    [
        {"user_id": str(uuid.uuid4())},
        {"redirect_uri": "https://evil.example/callback"},
        {"region": "eu"},
        {"endpoint_mode": "sandbox"},
        {"state": CANARY_STATE},
        {"application_id": "evil-app"},
    ],
)
def test_start_rejects_extra_or_override_fields(
    client,
    user_factory,
    auth_header,
    fake_oauth_service: FakeOAuthService,
    extra: dict,
):
    user = user_factory("oauth-api-extra@example.com")
    response = client.post(
        START_URL,
        headers=auth_header(user),
        json={**_start_body(), **extra},
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert fake_oauth_service.start_calls == []


def test_start_does_not_redirect(client, user_factory, auth_header, fake_oauth_service: FakeOAuthService):
    user = user_factory("oauth-api-no-redirect@example.com")
    response = client.post(START_URL, headers=auth_header(user), json=_start_body())
    assert response.status_code == status.HTTP_200_OK
    assert "location" not in response.headers


def test_callback_success_without_auth_header(
    client,
    fake_oauth_service: FakeOAuthService,
    oauth_frontend_settings,
):
    response = client.get(CALLBACK_URL, params=_callback_params(), follow_redirects=False)
    assert response.status_code == status.HTTP_303_SEE_OTHER
    assert response.headers["location"] == SUCCESS_URL
    _assert_callback_security_headers(response)
    assert len(fake_oauth_service.complete_calls) == 1
    call = fake_oauth_service.complete_calls[0]
    assert set(call) == {"state", "spapi_oauth_code", "selling_partner_id"}
    assert call["state"] == CANARY_STATE
    assert CANARY_STATE not in response.headers["location"]
    assert CANARY_CODE not in response.text
    assert response.text == ""


@pytest.mark.parametrize(
    ("error_factory", "expected_code"),
    [
        (amazon_oauth_state_invalid_error, AMAZON_OAUTH_STATE_INVALID),
        (amazon_oauth_state_expired_error, AMAZON_OAUTH_STATE_EXPIRED),
        (amazon_oauth_state_replay_error, AMAZON_OAUTH_STATE_REPLAY),
        (lambda: AmazonError("seller", error_code=AMAZON_OAUTH_SELLER_INVALID, status_code=400), AMAZON_OAUTH_SELLER_INVALID),
        (amazon_oauth_token_exchange_failed_error, AMAZON_OAUTH_TOKEN_EXCHANGE_FAILED),
        (lambda: AmazonError("conflict", error_code=AMAZON_OAUTH_SELLER_ALREADY_LINKED, status_code=409), AMAZON_OAUTH_SELLER_ALREADY_LINKED),
        (amazon_oauth_account_persist_failed_error, AMAZON_OAUTH_ACCOUNT_PERSIST_FAILED),
    ],
)
def test_callback_business_failures_redirect_with_stable_error_code(
    client,
    fake_oauth_service: FakeOAuthService,
    oauth_frontend_settings,
    error_factory,
    expected_code: str,
):
    fake_oauth_service.complete_error = error_factory()
    response = client.get(CALLBACK_URL, params=_callback_params(), follow_redirects=False)
    assert response.status_code == status.HTTP_303_SEE_OTHER
    location = response.headers["location"]
    assert location.startswith(ERROR_URL)
    query = parse_qs(urlparse(location).query)
    assert query == {"error_code": [expected_code]}
    assert CANARY_STATE not in location
    assert CANARY_CODE not in location
    assert CANARY_SELLER not in location


def test_callback_unexpected_error_uses_fixed_code(
    client,
    fake_oauth_service: FakeOAuthService,
    oauth_frontend_settings,
    caplog: pytest.LogCaptureFixture,
):
    fake_oauth_service.complete_unexpected = True
    with caplog.at_level("WARNING"):
        response = client.get(CALLBACK_URL, params=_callback_params(), follow_redirects=False)
    assert _error_location_query(response)["error_code"] == [AMAZON_OAUTH_ACCOUNT_PERSIST_FAILED]
    assert CANARY_CODE not in caplog.text
    assert CANARY_CODE not in response.text


def test_callback_provider_denial_skips_service(
    client,
    fake_oauth_service: FakeOAuthService,
    oauth_frontend_settings,
    caplog: pytest.LogCaptureFixture,
):
    with caplog.at_level("WARNING"):
        response = client.get(
            CALLBACK_URL,
            params={"error": "access_denied", "error_description": CANARY_SECRET},
            follow_redirects=False,
        )
    assert fake_oauth_service.complete_calls == []
    assert _error_location_query(response)["error_code"] == [AMAZON_OAUTH_REDIRECT_INVALID]
    assert CANARY_SECRET not in caplog.text
    assert CANARY_SECRET not in response.headers["location"]


@pytest.mark.parametrize("missing_field", ["state", "spapi_oauth_code", "selling_partner_id"])
def test_callback_missing_required_param(
    client,
    fake_oauth_service: FakeOAuthService,
    oauth_frontend_settings,
    missing_field: str,
):
    params = _callback_params()
    del params[missing_field]
    response = client.get(CALLBACK_URL, params=params, follow_redirects=False)
    assert fake_oauth_service.complete_calls == []
    assert _error_location_query(response)["error_code"] == [AMAZON_OAUTH_REDIRECT_INVALID]


def test_callback_ignores_client_identity_overrides(
    client,
    fake_oauth_service: FakeOAuthService,
    oauth_frontend_settings,
):
    params = _callback_params(
        user_id=str(uuid.uuid4()),
        redirect_uri="https://evil.example/steal",
        frontend_success_url="https://evil.example/success",
    )
    response = client.get(CALLBACK_URL, params=params, follow_redirects=False)
    assert response.headers["location"] == SUCCESS_URL
    assert "evil.example" not in response.headers["location"]
    assert fake_oauth_service.complete_calls[0]["state"] == CANARY_STATE


def test_router_paths_unique_and_registered():
    oauth_paths = [
        route.path
        for route in app.routes
        if getattr(route, "path", "").startswith("/api/v1/amazon/oauth")
    ]
    assert sorted(oauth_paths) == ["/api/v1/amazon/oauth/callback", "/api/v1/amazon/oauth/start"]


def test_openapi_start_requires_auth_and_callback_public():
    schema = app.openapi()
    start = schema["paths"]["/api/v1/amazon/oauth/start"]["post"]
    callback = schema["paths"]["/api/v1/amazon/oauth/callback"]["get"]
    assert start.get("security") == [{"HTTPBearer": []}]
    assert callback.get("security") in (None, [])
    start_props = start["responses"]["200"]["content"]["application/json"]["schema"]
    serialized = str(start_props)
    assert "refresh_token" not in serialized.lower()
    assert "state_token_hash" not in serialized.lower()
    assert "selling_partner_id" not in serialized.lower()


def test_oauth_disabled_start_does_not_invoke_lwa(
    client,
    user_factory,
    auth_header,
    oauth_api_settings: AmazonSettings,
    token_encryption_service,
):
    lwa_calls = {"count": 0}

    class CountingLwaClient:
        async def exchange_authorization_code(self, code: str):
            lwa_calls["count"] += 1
            raise AssertionError("LWA should not be called")

    from app.api.amazon_oauth_deps import build_amazon_oauth_service

    disabled_settings = oauth_api_settings.model_copy(update={"oauth_enabled": False})

    def _service_factory():
        return build_amazon_oauth_service(
            amazon_settings=disabled_settings,
            encryption_service=token_encryption_service,
            lwa_client_factory=lambda: CountingLwaClient(),  # type: ignore[return-value]
        )

    def _factory_provider():
        return _service_factory

    app.dependency_overrides[get_amazon_oauth_service] = _service_factory
    app.dependency_overrides[get_amazon_oauth_service_factory] = _factory_provider
    try:
        user = user_factory("oauth-api-disabled-lwa@example.com")
        response = client.post(START_URL, headers=auth_header(user), json=_start_body())
        assert response.json()["error_code"] == AMAZON_OAUTH_DISABLED
        assert lwa_calls["count"] == 0
    finally:
        app.dependency_overrides.pop(get_amazon_oauth_service, None)
        app.dependency_overrides.pop(get_amazon_oauth_service_factory, None)


def test_oauth_disabled_callback_does_not_invoke_lwa(
    client,
    oauth_api_settings: AmazonSettings,
    token_encryption_service,
    monkeypatch: pytest.MonkeyPatch,
):
    lwa_calls = {"count": 0}

    class CountingLwaClient:
        async def exchange_authorization_code(self, code: str):
            lwa_calls["count"] += 1
            raise AssertionError("LWA should not be called")

    from app.api.amazon_oauth_deps import build_amazon_oauth_service

    disabled = oauth_api_settings.model_copy(update={"oauth_enabled": False})
    monkeypatch.setattr("app.api.amazon_oauth._amazon_settings", lambda: disabled)

    def _service_factory():
        return build_amazon_oauth_service(
            amazon_settings=disabled,
            encryption_service=token_encryption_service,
            lwa_client_factory=lambda: CountingLwaClient(),  # type: ignore[return-value]
        )

    def _factory_provider():
        return _service_factory

    app.dependency_overrides[get_amazon_oauth_service_factory] = _factory_provider
    try:
        response = client.get(CALLBACK_URL, params=_callback_params(), follow_redirects=False)
        assert _error_location_query(response)["error_code"] == [AMAZON_OAUTH_DISABLED]
        assert lwa_calls["count"] == 0
    finally:
        app.dependency_overrides.pop(get_amazon_oauth_service_factory, None)


def test_callback_provider_denial_skips_lazy_factory_when_build_would_fail(
    client,
    failing_oauth_factory_override,
):
    response = client.get(
        CALLBACK_URL,
        params={"error": "access_denied", "error_description": CANARY_SECRET},
        follow_redirects=False,
    )
    assert response.status_code == status.HTTP_303_SEE_OTHER
    assert _error_location_query(response)["error_code"] == [AMAZON_OAUTH_REDIRECT_INVALID]
    assert failing_oauth_factory_override["n"] == 0
    assert CANARY_SECRET not in response.text
    assert "token encryption" not in response.text.lower()


@pytest.mark.parametrize("missing_field", ["state", "spapi_oauth_code", "selling_partner_id"])
def test_callback_missing_params_skip_lazy_factory_when_build_would_fail(
    client,
    failing_oauth_factory_override,
    missing_field: str,
):
    params = _callback_params()
    del params[missing_field]
    response = client.get(CALLBACK_URL, params=params, follow_redirects=False)
    assert response.status_code == status.HTTP_303_SEE_OTHER
    assert _error_location_query(response)["error_code"] == [AMAZON_OAUTH_REDIRECT_INVALID]
    assert failing_oauth_factory_override["n"] == 0


def test_callback_lazy_factory_invoked_once_on_success(
    client,
    fake_oauth_service: FakeOAuthService,
    oauth_frontend_settings,
):
    response = client.get(CALLBACK_URL, params=_callback_params(), follow_redirects=False)
    assert response.status_code == status.HTTP_303_SEE_OTHER
    assert fake_oauth_service.factory_build_count == 1
    assert len(fake_oauth_service.complete_calls) == 1


def test_global_amazon_error_handler_masks_dynamic_message(
    client,
    user_factory,
    auth_header,
    fake_oauth_service: FakeOAuthService,
    caplog: pytest.LogCaptureFixture,
):
    user = user_factory("oauth-api-canary-message@example.com")
    fake_oauth_service.start_error = AmazonError(
        CANARY_MESSAGE,
        error_code=AMAZON_OAUTH_MARKETPLACE_INVALID,
        status_code=400,
    )
    with caplog.at_level("WARNING"):
        response = client.post(START_URL, headers=auth_header(user), json=_start_body())
    body = response.json()
    assert body["error_code"] == AMAZON_OAUTH_MARKETPLACE_INVALID
    assert body["message"] == public_message_for_amazon_error_code(AMAZON_OAUTH_MARKETPLACE_INVALID)
    assert body["message"] == AMAZON_OAUTH_MARKETPLACE_PUBLIC_MESSAGE
    assert CANARY_MESSAGE not in response.text
    assert CANARY_SECRET not in response.text
    assert CANARY_MESSAGE not in caplog.text


def test_global_amazon_error_handler_sanitizes_malicious_error_code(
    client,
    user_factory,
    auth_header,
    fake_oauth_service: FakeOAuthService,
):
    user = user_factory("oauth-api-malicious-code@example.com")
    fake_oauth_service.start_error = AmazonError(
        CANARY_MESSAGE,
        error_code=MALICIOUS_ERROR_CODE,
        status_code=400,
    )
    response = client.post(START_URL, headers=auth_header(user), json=_start_body())
    body = response.json()
    assert body["error_code"] == AMAZON_CONFIG_INVALID
    assert MALICIOUS_ERROR_CODE not in response.text
    assert "CANARY" not in response.text
    assert "\r\n" not in response.text
    assert "\x7f" not in response.text
    assert "Location" not in response.headers


@pytest.mark.parametrize(
    "query_suffix",
    [
        f"state=A&state=B&spapi_oauth_code={CANARY_CODE}&selling_partner_id={CANARY_SELLER}",
        f"state={CANARY_STATE}&spapi_oauth_code=A&spapi_oauth_code=B&selling_partner_id={CANARY_SELLER}",
        f"state={CANARY_STATE}&spapi_oauth_code={CANARY_CODE}&selling_partner_id=A&selling_partner_id=B",
        "error=access_denied&error=server_error",
        "error=access_denied&error_description=a&error_description=b",
    ],
)
def test_callback_duplicate_query_params_skip_service(
    client,
    fake_oauth_service: FakeOAuthService,
    oauth_frontend_settings,
    query_suffix: str,
):
    response = client.get(f"{CALLBACK_URL}?{query_suffix}", follow_redirects=False)
    assert response.status_code == status.HTTP_303_SEE_OTHER
    assert _error_location_query(response)["error_code"] == [AMAZON_OAUTH_REDIRECT_INVALID]
    assert fake_oauth_service.factory_build_count == 0
    assert fake_oauth_service.complete_calls == []
    assert CANARY_CODE not in response.headers.get("location", "")
    assert CANARY_SELLER not in response.headers.get("location", "")


@pytest.mark.parametrize(
    "invalid_success_url",
    [
        "https://app.oauth.test/oauth/success?bad=1",
        "https://app.oauth.test/oauth/success#fragment",
        "https://evil@app.oauth.test/oauth/success",
    ],
)
def test_callback_success_redirect_invalid_falls_back_to_error_redirect(
    client,
    fake_oauth_service: FakeOAuthService,
    oauth_api_settings: AmazonSettings,
    monkeypatch: pytest.MonkeyPatch,
    invalid_success_url: str,
):
    settings = oauth_api_settings.model_copy(update={"oauth_frontend_success_url": invalid_success_url})
    monkeypatch.setattr("app.api.amazon_oauth._amazon_settings", lambda: settings)
    response = client.get(CALLBACK_URL, params=_callback_params(), follow_redirects=False)
    assert response.status_code == status.HTTP_303_SEE_OTHER
    location = response.headers["location"]
    assert location.startswith(ERROR_URL)
    assert _error_location_query(response)["error_code"] == [AMAZON_OAUTH_REDIRECT_INVALID]
    assert CANARY_STATE not in location
    assert CANARY_CODE not in location
    assert len(fake_oauth_service.complete_calls) == 1


def test_callback_error_redirect_invalid_returns_sanitized_json_500(
    client,
    fake_oauth_service: FakeOAuthService,
    oauth_api_settings: AmazonSettings,
    monkeypatch: pytest.MonkeyPatch,
):
    invalid_error_url = "https://app.oauth.test/oauth/error?bad=1"
    settings = oauth_api_settings.model_copy(update={"oauth_frontend_error_url": invalid_error_url})
    monkeypatch.setattr("app.api.amazon_oauth._amazon_settings", lambda: settings)
    fake_oauth_service.complete_error = amazon_oauth_state_invalid_error()
    response = client.get(CALLBACK_URL, params=_callback_params(), follow_redirects=False)
    assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    body = response.json()
    assert body["error_code"] == AMAZON_OAUTH_REDIRECT_INVALID
    assert body["message"] == public_message_for_amazon_error_code(AMAZON_OAUTH_REDIRECT_INVALID)
    assert "location" not in response.headers
    assert invalid_error_url not in response.text
    assert CANARY_STATE not in response.text
    assert CANARY_CODE not in response.text
    _assert_callback_security_headers(response)


def test_callback_cancelled_error_propagates(
    client,
    fake_oauth_service: FakeOAuthService,
    oauth_frontend_settings,
):
    fake_oauth_service.complete_cancelled = True
    with pytest.raises(Exception) as exc_info:
        client.get(CALLBACK_URL, params=_callback_params(), follow_redirects=False)
    assert exc_info.type.__name__ == "CancelledError"
    assert fake_oauth_service.factory_build_count == 1
    assert len(fake_oauth_service.complete_calls) == 1


def test_callback_malicious_amazon_error_code_sanitized_in_location(
    client,
    fake_oauth_service: FakeOAuthService,
    oauth_frontend_settings,
):
    fake_oauth_service.complete_error = AmazonError(
        CANARY_MESSAGE,
        error_code=MALICIOUS_ERROR_CODE,
        status_code=400,
    )
    response = client.get(CALLBACK_URL, params=_callback_params(), follow_redirects=False)
    location = response.headers["location"]
    assert response.status_code == status.HTTP_303_SEE_OTHER
    assert _error_location_query(response)["error_code"] == [AMAZON_OAUTH_REDIRECT_INVALID]
    assert "\r\n" not in location
    assert "CANARY" not in location
    assert "evil.example" not in location
    assert CANARY_MESSAGE not in location
