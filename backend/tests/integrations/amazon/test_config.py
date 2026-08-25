from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.integrations.amazon.config import AmazonEndpointMode, AmazonSettings

MFA_TEST_KEY = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="


def test_default_settings_disabled_and_mock():
    app_settings = Settings(
        _env_file=None,
        ENVIRONMENT="development",
        DATABASE_URL="postgresql://localhost:5432/sellerai",
        JWT_SECRET_KEY="dev-only-jwt-secret-key-min-32-chars",
        OPENAI_API_KEY="test-openai-key",
    )
    assert app_settings.AMAZON_SP_API_ENABLED is False
    assert app_settings.AMAZON_SP_API_ENDPOINT_MODE == "mock"


def test_amazon_settings_requires_credentials_for_sandbox():
    with pytest.raises(ValidationError, match="lwa_client_id"):
        AmazonSettings(
            enabled=True,
            endpoint_mode=AmazonEndpointMode.SANDBOX,
            lwa_client_secret="secret",
            user_agent="ua",
            lwa_token_url="https://api.amazon.com/auth/o2/token",
        )


def test_amazon_settings_requires_https_token_url_for_sandbox():
    with pytest.raises(ValidationError, match="HTTPS"):
        AmazonSettings(
            enabled=True,
            lwa_client_id="id",
            lwa_client_secret="secret",
            user_agent="ua",
            endpoint_mode=AmazonEndpointMode.SANDBOX,
            lwa_token_url="http://api.amazon.com/auth/o2/token",
        )


def test_testing_environment_rejects_sandbox_endpoint_mode():
    with pytest.raises(ValueError, match="mock"):
        Settings(
            _env_file=None,
            ENVIRONMENT="testing",
            DATABASE_URL="postgresql://localhost:5432/sellerai_test",
            AMAZON_SP_API_ENDPOINT_MODE="sandbox",
        )


def test_production_rejects_non_amazon_lwa_host():
    with pytest.raises(ValidationError, match="api.amazon.com"):
        Settings(
            _env_file=None,
            ENVIRONMENT="production",
            DATABASE_URL="postgresql://example.com:5432/sellerai_prod",
            JWT_SECRET_KEY="x" * 32,
            OPENAI_API_KEY="test-openai-key",
            MFA_ENCRYPTION_KEY=MFA_TEST_KEY,
            AMAZON_SP_API_ENABLED=True,
            AMAZON_LWA_CLIENT_ID="id",
            AMAZON_LWA_CLIENT_SECRET="secret",
            AMAZON_SP_API_ENDPOINT_MODE="production",
            AMAZON_LWA_TOKEN_URL="https://mock.lwa.local/auth/o2/token",
        )


def test_settings_has_no_aws_credential_fields():
    fields = Settings.model_fields
    assert "AWS_ACCESS_KEY_ID" not in fields
    assert "AWS_SECRET_ACCESS_KEY" not in fields


def test_settings_exposes_amazon_settings_property():
    app_settings = Settings(
        _env_file=None,
        ENVIRONMENT="development",
        DATABASE_URL="postgresql://localhost:5432/sellerai",
        JWT_SECRET_KEY="dev-only-jwt-secret-key-min-32-chars",
        OPENAI_API_KEY="test-openai-key",
        AMAZON_SP_API_ENABLED=True,
        AMAZON_LWA_CLIENT_ID="APP_CLIENT_ID",
        AMAZON_LWA_CLIENT_SECRET="APP_CLIENT_SECRET",
    )
    amazon = app_settings.amazon_settings
    assert amazon.enabled is True
    assert amazon.lwa_client_id == "APP_CLIENT_ID"
