from __future__ import annotations

import base64
import binascii
from typing import Literal
from urllib.parse import urlparse

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.integrations.amazon.config import AmazonEndpointMode, AmazonSettings

WEAK_JWT_SECRETS = frozenset(
    {
        "",
        "your-super-secret-jwt-key-change-me",
        "your-secret-key",
        "change-me",
        "secret",
        "test",
    }
)

DEV_DATABASE_URL = "postgresql://sellerai:sellerai123@localhost:5432/sellerai"
TEST_DATABASE_URL = "postgresql://sellerai:sellerai123@localhost:5432/sellerai_test"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
    )

    ENVIRONMENT: Literal["development", "testing", "staging", "production"] = "development"

    DATABASE_URL: str | None = None

    REDIS_URL: str = "redis://redis:6379"

    OPENAI_API_KEY: str = ""
    OPENAI_BASE_URL: str = "https://openrouter.ai/api/v1"
    OPENAI_MODEL: str = "openai/gpt-4o-mini"
    OPENAI_FALLBACK_MODELS: str = ""
    OPENAI_REFERER: str = "http://localhost:3000"
    OPENAI_TITLE: str = "SellerAI Copilot"
    OPENAI_TIMEOUT: float = 120.0

    JWT_SECRET_KEY: str = ""
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 1440

    SESSION_TTL_MINUTES: int = 30
    SESSION_COOKIE_SECURE: bool | None = None
    AUTH_TESTING_ALLOW_MISSING_ORIGIN: bool = False
    MFA_ENCRYPTION_KEY: str = ""

    CORS_ORIGINS: str = "http://localhost:3000"

    APP_NAME: str = "SellerAI Copilot"
    DEBUG: bool = False

    # Frozen product capabilities. Public Analysis requires a future B3 source
    # change; it cannot be enabled by deployment configuration alone.
    LEGACY_GENERATION_ENABLED: bool = False
    ANALYSIS_PUBLIC_ENABLED: bool = False
    LISTING_AUDIT_INTERNAL_ENABLED: bool = False

    AMAZON_SP_API_ENABLED: bool = False
    AMAZON_LWA_CLIENT_ID: str = ""
    AMAZON_LWA_CLIENT_SECRET: str = ""
    AMAZON_LWA_TOKEN_URL: str = "https://api.amazon.com/auth/o2/token"
    AMAZON_SP_API_REGION: Literal["na", "eu", "fe"] = "na"
    AMAZON_SP_API_ENDPOINT_MODE: Literal["mock", "sandbox", "production"] = "mock"
    AMAZON_SP_API_USER_AGENT: str = "SellerAI-Copilot/1.0.0 (Language=Python)"

    AMAZON_TOKEN_ACTIVE_KEY_VERSION: int = 0
    AMAZON_TOKEN_KEY_V1: str = ""
    AMAZON_TOKEN_KEY_V0: str = ""
    AMAZON_TOKEN_FINGERPRINT_PEPPER: str = ""

    AMAZON_SP_API_APPLICATION_ID: str = ""
    AMAZON_OAUTH_ENABLED: bool = False
    AMAZON_OAUTH_REDIRECT_URI: str = ""
    AMAZON_OAUTH_FRONTEND_SUCCESS_URL: str = ""
    AMAZON_OAUTH_FRONTEND_ERROR_URL: str = ""
    AMAZON_OAUTH_CONSENT_VERSION: str = ""
    AMAZON_OAUTH_STATE_TTL_SECONDS: int = 600

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: object) -> str:
        if isinstance(value, list):
            return ",".join(str(item) for item in value)
        return str(value)

    @field_validator("SESSION_TTL_MINUTES")
    @classmethod
    def validate_session_ttl_minutes(cls, value: int) -> int:
        if value < 5 or value > 60:
            raise ValueError("SESSION_TTL_MINUTES must be between 5 and 60")
        return value

    @property
    def cors_origins_list(self) -> list[str]:
        if self.CORS_ORIGINS == "*":
            return ["*"]
        return [item.strip() for item in self.CORS_ORIGINS.split(",") if item.strip()]

    @property
    def cors_origins_are_loopback_http(self) -> bool:
        origins = self.cors_origins_list
        if not origins or origins == ["*"]:
            return False
        for origin in origins:
            parsed = urlparse(origin)
            if parsed.scheme != "http":
                return False
            if parsed.username or parsed.password or parsed.query or parsed.fragment:
                return False
            if parsed.path not in {"", "/"}:
                return False
            host = (parsed.hostname or "").lower()
            if host not in {"127.0.0.1", "localhost", "::1"}:
                return False
        return True

    @property
    def is_dev_like(self) -> bool:
        return self.ENVIRONMENT in {"development", "testing"}

    @property
    def resolved_session_cookie_secure(self) -> bool:
        if self.SESSION_COOKIE_SECURE is not None:
            return self.SESSION_COOKIE_SECURE
        return self.ENVIRONMENT in {"staging", "production"}

    @property
    def api_docs_enabled(self) -> bool:
        return self.is_dev_like

    @property
    def amazon_settings(self) -> AmazonSettings:
        return AmazonSettings(
            enabled=self.AMAZON_SP_API_ENABLED,
            oauth_enabled=self.AMAZON_OAUTH_ENABLED,
            lwa_client_id=self.AMAZON_LWA_CLIENT_ID,
            lwa_client_secret=self.AMAZON_LWA_CLIENT_SECRET,
            lwa_token_url=self.AMAZON_LWA_TOKEN_URL,
            sp_api_region=self.AMAZON_SP_API_REGION,
            endpoint_mode=AmazonEndpointMode(self.AMAZON_SP_API_ENDPOINT_MODE),
            user_agent=self.AMAZON_SP_API_USER_AGENT,
            environment=self.ENVIRONMENT,
            application_id=self.AMAZON_SP_API_APPLICATION_ID,
            oauth_redirect_uri=self.AMAZON_OAUTH_REDIRECT_URI,
            oauth_frontend_success_url=self.AMAZON_OAUTH_FRONTEND_SUCCESS_URL,
            oauth_frontend_error_url=self.AMAZON_OAUTH_FRONTEND_ERROR_URL,
            oauth_consent_version=self.AMAZON_OAUTH_CONSENT_VERSION,
            oauth_state_ttl_seconds=self.AMAZON_OAUTH_STATE_TTL_SECONDS,
        )

    @model_validator(mode="after")
    def validate_environment(self) -> Settings:
        if self.ANALYSIS_PUBLIC_ENABLED:
            raise ValueError(
                "ANALYSIS_PUBLIC_ENABLED must remain false before the B3 go/no-go"
            )

        if self.ENVIRONMENT == "testing":
            if not self.DATABASE_URL:
                self.DATABASE_URL = TEST_DATABASE_URL
            db_name = self.DATABASE_URL.rsplit("/", 1)[-1]
            if "_test" not in db_name and not db_name.endswith("test"):
                raise ValueError(
                    "Testing requires a dedicated test database name containing '_test'"
                )
            if not self.JWT_SECRET_KEY:
                self.JWT_SECRET_KEY = "pytest-jwt-secret-key-min-32-chars-long"
            if not self.OPENAI_API_KEY:
                self.OPENAI_API_KEY = "test-openai-key-not-used"
            if not self.MFA_ENCRYPTION_KEY:
                self.MFA_ENCRYPTION_KEY = (
                    "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="
                )
            self._validate_mfa_key()
            if self.AMAZON_SP_API_ENDPOINT_MODE != "mock":
                raise ValueError("Testing environment requires AMAZON_SP_API_ENDPOINT_MODE=mock")
            _ = self.amazon_settings
            return self

        if not self.DATABASE_URL:
            if self.ENVIRONMENT == "development":
                self.DATABASE_URL = DEV_DATABASE_URL
            else:
                raise ValueError("DATABASE_URL is required outside development/testing")

        if self.ENVIRONMENT == "development":
            if not self.JWT_SECRET_KEY:
                self.JWT_SECRET_KEY = "dev-only-jwt-secret-key-min-32-chars"
            if not self.OPENAI_API_KEY:
                raise ValueError("OPENAI_API_KEY is required in development")
            if not self.MFA_ENCRYPTION_KEY:
                self.MFA_ENCRYPTION_KEY = (
                    "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="
                )
            self._validate_mfa_key()
            _ = self.amazon_settings
            return self

        if not self.JWT_SECRET_KEY or self.JWT_SECRET_KEY in WEAK_JWT_SECRETS:
            raise ValueError("JWT_SECRET_KEY must be set to a strong non-default secret")
        if len(self.JWT_SECRET_KEY) < 32:
            raise ValueError("JWT_SECRET_KEY must be at least 32 characters")
        if not self.OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY is required")
        self._validate_mfa_key()
        if self.DEBUG:
            raise ValueError("DEBUG must remain false outside development/testing")
        if "*" in self.cors_origins_list:
            raise ValueError("CORS_ORIGINS must not contain a wildcard outside development/testing")
        if self.SESSION_COOKIE_SECURE is False:
            if self.ENVIRONMENT == "production":
                raise ValueError("SESSION_COOKIE_SECURE must not be false in staging or production")
            if self.ENVIRONMENT == "staging" and not self.cors_origins_are_loopback_http:
                raise ValueError("SESSION_COOKIE_SECURE must not be false in staging or production")
        _ = self.amazon_settings
        return self

    def _validate_mfa_key(self) -> None:
        if not self.MFA_ENCRYPTION_KEY:
            raise ValueError("MFA_ENCRYPTION_KEY is required")
        try:
            key = base64.b64decode(self.MFA_ENCRYPTION_KEY, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("MFA_ENCRYPTION_KEY must be valid base64") from exc
        if len(key) != 32:
            raise ValueError("MFA_ENCRYPTION_KEY must encode exactly 32 bytes")


settings = Settings()
