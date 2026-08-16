"""Amazon OAuth configuration and error contract unit tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.integrations.amazon.config import (
    OAUTH_ACCOUNT_ENDPOINT_MODE,
    OAUTH_STATE_TTL_DEFAULT_SECONDS,
    OAUTH_STATE_TTL_MAX_SECONDS,
    OAUTH_STATE_TTL_MIN_SECONDS,
    AmazonEndpointMode,
    AmazonSettings,
)
from app.integrations.amazon.exceptions import (
    AMAZON_OAUTH_ACCOUNT_PERSIST_FAILED,
    AMAZON_OAUTH_DISABLED,
    AMAZON_OAUTH_INTENT_INVALID,
    AMAZON_OAUTH_MARKETPLACE_INVALID,
    AMAZON_OAUTH_REDIRECT_INVALID,
    AMAZON_OAUTH_SELLER_ALREADY_LINKED,
    AMAZON_OAUTH_SELLER_INVALID,
    AMAZON_OAUTH_SELLER_MISMATCH,
    AMAZON_OAUTH_STATE_EXPIRED,
    AMAZON_OAUTH_STATE_INVALID,
    AMAZON_OAUTH_STATE_REPLAY,
    AMAZON_OAUTH_TOKEN_EXCHANGE_FAILED,
    AMAZON_OAUTH_USER_NOT_FOUND,
    AmazonError,
    amazon_oauth_account_persist_failed_error,
    amazon_oauth_disabled_error,
    amazon_oauth_intent_invalid_error,
    amazon_oauth_marketplace_invalid_error,
    amazon_oauth_redirect_invalid_error,
    amazon_oauth_seller_already_linked_error,
    amazon_oauth_seller_invalid_error,
    amazon_oauth_seller_mismatch_error,
    amazon_oauth_state_expired_error,
    amazon_oauth_state_invalid_error,
    amazon_oauth_state_replay_error,
    amazon_oauth_token_exchange_failed_error,
    amazon_oauth_user_not_found_error,
)

CANARY = "CANARY_SECRET_PAYLOAD_MARKER_XYZ"
CANARY_SECRET = f"secret-{CANARY}-value"


def _live_oauth_kwargs(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "enabled": True,
        "oauth_enabled": True,
        "endpoint_mode": AmazonEndpointMode.PRODUCTION,
        "lwa_client_id": "amzn1.application-oa2-client.example",
        "lwa_client_secret": "lwa-secret-placeholder",
        "user_agent": "SellerAI-Copilot/1.0.0 (Language=Python)",
        "lwa_token_url": "https://api.amazon.com/auth/o2/token",
        "application_id": "amzn1.sp.solution.example",
        "oauth_redirect_uri": "https://api.example.com/api/v1/amazon/oauth/callback",
        "oauth_frontend_success_url": "https://app.example.com/oauth/success",
        "oauth_frontend_error_url": "https://app.example.com/oauth/error",
        "environment": "staging",
    }
    base.update(overrides)
    return base


def _sp_api_live_kwargs(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "enabled": True,
        "oauth_enabled": False,
        "lwa_client_id": "amzn1.application-oa2-client.example",
        "lwa_client_secret": "lwa-secret-placeholder",
        "user_agent": "SellerAI-Copilot/1.0.0 (Language=Python)",
        "lwa_token_url": "https://api.amazon.com/auth/o2/token",
        "environment": "development",
    }
    base.update(overrides)
    return base


@pytest.mark.parametrize(
    ("factory", "expected_code", "expected_status"),
    [
        (amazon_oauth_disabled_error, AMAZON_OAUTH_DISABLED, 503),
        (amazon_oauth_state_invalid_error, AMAZON_OAUTH_STATE_INVALID, 400),
        (amazon_oauth_state_expired_error, AMAZON_OAUTH_STATE_EXPIRED, 400),
        (amazon_oauth_state_replay_error, AMAZON_OAUTH_STATE_REPLAY, 409),
        (amazon_oauth_redirect_invalid_error, AMAZON_OAUTH_REDIRECT_INVALID, 400),
        (amazon_oauth_marketplace_invalid_error, AMAZON_OAUTH_MARKETPLACE_INVALID, 400),
        (amazon_oauth_seller_invalid_error, AMAZON_OAUTH_SELLER_INVALID, 400),
        (amazon_oauth_seller_mismatch_error, AMAZON_OAUTH_SELLER_MISMATCH, 409),
        (amazon_oauth_seller_already_linked_error, AMAZON_OAUTH_SELLER_ALREADY_LINKED, 409),
        (amazon_oauth_token_exchange_failed_error, AMAZON_OAUTH_TOKEN_EXCHANGE_FAILED, 502),
        (amazon_oauth_user_not_found_error, AMAZON_OAUTH_USER_NOT_FOUND, 401),
        (amazon_oauth_account_persist_failed_error, AMAZON_OAUTH_ACCOUNT_PERSIST_FAILED, 500),
        (amazon_oauth_intent_invalid_error, AMAZON_OAUTH_INTENT_INVALID, 400),
    ],
)
def test_oauth_error_helpers(
    factory,
    expected_code: str,
    expected_status: int,
) -> None:
    exc = factory()
    assert isinstance(exc, AmazonError)
    assert exc.error_code == expected_code
    assert exc.status_code == expected_status
    assert CANARY not in exc.message
    assert CANARY not in str(exc)
    assert CANARY not in repr(exc)


def test_default_settings_disabled_and_mock() -> None:
    app_settings = Settings(
        _env_file=None,
        ENVIRONMENT="development",
        DATABASE_URL="postgresql://localhost:5432/sellerai",
        JWT_SECRET_KEY="dev-only-jwt-secret-key-min-32-chars",
        OPENAI_API_KEY="test-openai-key",
    )
    assert app_settings.AMAZON_SP_API_ENABLED is False
    assert app_settings.AMAZON_OAUTH_ENABLED is False
    assert app_settings.AMAZON_SP_API_ENDPOINT_MODE == "mock"
    assert app_settings.AMAZON_OAUTH_STATE_TTL_SECONDS == OAUTH_STATE_TTL_DEFAULT_SECONDS
    amazon = app_settings.amazon_settings
    assert amazon.oauth_enabled is False
    assert amazon.oauth_account_endpoint_mode == OAUTH_ACCOUNT_ENDPOINT_MODE


def test_sp_api_sandbox_succeeds_without_oauth_fields() -> None:
    settings = AmazonSettings(
        **_sp_api_live_kwargs(endpoint_mode=AmazonEndpointMode.SANDBOX),
    )
    assert settings.oauth_enabled is False
    assert settings.application_id == ""


def test_sp_api_production_succeeds_without_oauth_fields() -> None:
    settings = AmazonSettings(
        **_sp_api_live_kwargs(endpoint_mode=AmazonEndpointMode.PRODUCTION),
    )
    assert settings.oauth_enabled is False
    assert settings.oauth_redirect_uri == ""


def test_oauth_enabled_requires_sp_api_enabled() -> None:
    with pytest.raises(ValidationError, match="AMAZON_SP_API_ENABLED"):
        AmazonSettings(
            enabled=False,
            oauth_enabled=True,
            endpoint_mode=AmazonEndpointMode.PRODUCTION,
            environment="staging",
        )


def test_oauth_enabled_rejects_non_production_outside_testing() -> None:
    with pytest.raises(ValidationError, match="production"):
        AmazonSettings(
            **_live_oauth_kwargs(
                environment="development",
                endpoint_mode=AmazonEndpointMode.SANDBOX,
            )
        )


def test_oauth_enabled_production_requires_each_oauth_field() -> None:
    required_fields = (
        "lwa_client_id",
        "lwa_client_secret",
        "application_id",
        "oauth_redirect_uri",
        "oauth_frontend_success_url",
        "oauth_frontend_error_url",
    )
    for field in required_fields:
        kwargs = _live_oauth_kwargs(**{field: ""})
        with pytest.raises(ValidationError, match=field):
            AmazonSettings(**kwargs)


def test_testing_oauth_enabled_with_mock_and_test_urls_succeeds() -> None:
    settings = AmazonSettings(
        enabled=True,
        oauth_enabled=True,
        endpoint_mode=AmazonEndpointMode.MOCK,
        environment="testing",
        lwa_client_id="client-id",
        lwa_client_secret="client-secret",
        application_id="app-id",
        oauth_redirect_uri="https://api.oauth.test/api/v1/amazon/oauth/callback",
        oauth_frontend_success_url="https://app.oauth.test/oauth/success",
        oauth_frontend_error_url="https://app.oauth.test/oauth/error",
    )
    assert settings.oauth_enabled is True
    assert settings.endpoint_mode is AmazonEndpointMode.MOCK


def test_testing_oauth_enabled_rejects_non_test_hosts() -> None:
    with pytest.raises(ValidationError, match="testing or mock"):
        AmazonSettings(
            enabled=True,
            oauth_enabled=True,
            endpoint_mode=AmazonEndpointMode.MOCK,
            environment="testing",
            lwa_client_id="client-id",
            lwa_client_secret="client-secret",
            application_id="app-id",
            oauth_redirect_uri="https://api.example.com/api/v1/amazon/oauth/callback",
            oauth_frontend_success_url="https://app.oauth.test/oauth/success",
            oauth_frontend_error_url="https://app.oauth.test/oauth/error",
        )


def test_oauth_disabled_ignores_empty_oauth_urls_for_sp_api_config() -> None:
    settings = AmazonSettings(
        **_sp_api_live_kwargs(
            endpoint_mode=AmazonEndpointMode.SANDBOX,
            oauth_redirect_uri="",
            oauth_frontend_success_url="",
            oauth_frontend_error_url="",
            application_id="",
        )
    )
    assert settings.oauth_enabled is False
    assert settings.enabled is True


def test_live_oauth_validation_error_does_not_echo_client_secret() -> None:
    with pytest.raises(ValidationError) as exc_info:
        AmazonSettings(**_live_oauth_kwargs(application_id="", lwa_client_secret=CANARY_SECRET))
    rendered = str(exc_info.value)
    assert "application_id" in rendered
    assert CANARY not in rendered


def test_amazon_settings_repr_hides_client_secret() -> None:
    settings = AmazonSettings(**_live_oauth_kwargs(lwa_client_secret=CANARY_SECRET))
    rendered = repr(settings)
    assert CANARY not in rendered


@pytest.mark.parametrize(
    ("url_field", "url_value", "match"),
    [
        ("oauth_redirect_uri", "http://api.example.com/callback", "HTTPS"),
        ("oauth_frontend_success_url", "http://app.example.com/success", "HTTPS"),
        ("oauth_frontend_error_url", "http://app.example.com/error", "HTTPS"),
    ],
)
def test_staging_production_rejects_http_oauth_urls(
    url_field: str,
    url_value: str,
    match: str,
) -> None:
    with pytest.raises(ValidationError, match=match):
        AmazonSettings(**_live_oauth_kwargs(**{url_field: url_value}))


@pytest.mark.parametrize(
    ("url_field", "url_value", "match"),
    [
        ("oauth_redirect_uri", "https://user:pass@api.example.com/callback", "userinfo"),
        ("oauth_redirect_uri", "https://api.example.com/callback#frag", "fragment"),
        ("oauth_redirect_uri", "https://api.example.com/callback?x=1", "query"),
        ("oauth_frontend_success_url", "https://app.example.com/success?x=1", "query"),
    ],
)
def test_live_oauth_rejects_unsafe_url_shapes(
    url_field: str,
    url_value: str,
    match: str,
) -> None:
    with pytest.raises(ValidationError, match=match):
        AmazonSettings(**_live_oauth_kwargs(**{url_field: url_value}))


def test_oauth_consent_version_rejects_unknown_values() -> None:
    with pytest.raises(ValidationError, match="beta"):
        AmazonSettings(**_live_oauth_kwargs(oauth_consent_version="gamma"))


@pytest.mark.parametrize("consent_version", ["", "beta"])
def test_oauth_consent_version_accepts_empty_and_beta(consent_version: str) -> None:
    settings = AmazonSettings(**_live_oauth_kwargs(oauth_consent_version=consent_version))
    if consent_version:
        assert settings.oauth_consent_version_for_authorize == "beta"
    else:
        assert settings.oauth_consent_version_for_authorize is None


@pytest.mark.parametrize(
    ("ttl", "should_fail"),
    [
        (299, True),
        (300, False),
        (600, False),
        (900, False),
        (901, True),
    ],
)
def test_oauth_state_ttl_boundaries(ttl: int, should_fail: bool) -> None:
    if should_fail:
        with pytest.raises(ValidationError):
            AmazonSettings(**_live_oauth_kwargs(oauth_state_ttl_seconds=ttl))
    else:
        settings = AmazonSettings(**_live_oauth_kwargs(oauth_state_ttl_seconds=ttl))
        assert settings.oauth_state_ttl_seconds == ttl


def test_testing_oauth_url_validation_allows_mock_hosts() -> None:
    from app.integrations.amazon.config import _validate_oauth_url

    _validate_oauth_url(
        "https://api.oauth.test/api/v1/amazon/oauth/callback",
        field_label="AMAZON_OAUTH_REDIRECT_URI",
        environment="testing",
        allow_query=False,
    )


def test_testing_oauth_url_validation_rejects_non_mock_hosts() -> None:
    from app.integrations.amazon.config import _validate_oauth_url

    with pytest.raises(ValueError, match="testing or mock"):
        _validate_oauth_url(
            "https://api.example.com/api/v1/amazon/oauth/callback",
            field_label="AMAZON_OAUTH_REDIRECT_URI",
            environment="testing",
            allow_query=False,
        )


def test_settings_exposes_oauth_fields_on_amazon_settings() -> None:
    app_settings = Settings(
        _env_file=None,
        ENVIRONMENT="development",
        DATABASE_URL="postgresql://localhost:5432/sellerai",
        JWT_SECRET_KEY="dev-only-jwt-secret-key-min-32-chars",
        OPENAI_API_KEY="test-openai-key",
        AMAZON_SP_API_ENABLED=True,
        AMAZON_OAUTH_ENABLED=True,
        AMAZON_LWA_CLIENT_ID="APP_CLIENT_ID",
        AMAZON_LWA_CLIENT_SECRET="APP_CLIENT_SECRET",
        AMAZON_SP_API_ENDPOINT_MODE="production",
        AMAZON_SP_API_APPLICATION_ID="APP_ID",
        AMAZON_OAUTH_REDIRECT_URI="http://localhost:8000/api/v1/amazon/oauth/callback",
        AMAZON_OAUTH_FRONTEND_SUCCESS_URL="http://localhost:3000/oauth/success",
        AMAZON_OAUTH_FRONTEND_ERROR_URL="http://localhost:3000/oauth/error",
        AMAZON_OAUTH_CONSENT_VERSION="beta",
        AMAZON_OAUTH_STATE_TTL_SECONDS=OAUTH_STATE_TTL_MAX_SECONDS,
    )
    amazon = app_settings.amazon_settings
    assert amazon.oauth_enabled is True
    assert amazon.application_id == "APP_ID"
    assert amazon.oauth_consent_version == "beta"
    assert amazon.oauth_state_ttl_seconds == OAUTH_STATE_TTL_MAX_SECONDS
    assert amazon.oauth_state_ttl_seconds >= OAUTH_STATE_TTL_MIN_SECONDS
