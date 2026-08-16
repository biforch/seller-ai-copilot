"""Amazon SP-API configuration schema."""

from __future__ import annotations

from enum import Enum
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator, model_validator

from app.integrations.amazon.constants import (
    DEFAULT_LWA_TOKEN_URL,
    DEFAULT_USER_AGENT,
    SpApiRegion,
)

SpApiRegionLiteral = Literal["na", "eu", "fe"]
ALLOWED_LWA_HOSTS = frozenset({"api.amazon.com"})
ALLOWED_OAUTH_CONSENT_VERSIONS = frozenset({"", "beta"})
OAUTH_STATE_TTL_MIN_SECONDS = 300
OAUTH_STATE_TTL_MAX_SECONDS = 900
OAUTH_STATE_TTL_DEFAULT_SECONDS = 600
OAUTH_ACCOUNT_ENDPOINT_MODE = "production"


class AmazonEndpointMode(str, Enum):
    MOCK = "mock"
    SANDBOX = "sandbox"
    PRODUCTION = "production"


def _validate_oauth_url(
    url: str,
    *,
    field_label: str,
    environment: str,
    allow_query: bool,
) -> None:
    stripped = url.strip()
    if not stripped:
        raise ValueError(f"{field_label} is required")

    parsed = urlparse(stripped)
    if parsed.username or parsed.password:
        raise ValueError(f"{field_label} must not include userinfo")
    if parsed.fragment:
        raise ValueError(f"{field_label} must not include a fragment")
    if parsed.query and not allow_query:
        raise ValueError(f"{field_label} must not include query parameters")
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"{field_label} must be an absolute URL")

    if environment in {"staging", "production"}:
        if parsed.scheme != "https":
            raise ValueError(f"{field_label} must use HTTPS")
        return

    if environment == "testing":
        if parsed.scheme != "https":
            raise ValueError(f"{field_label} must use HTTPS")
        hostname = (parsed.hostname or "").lower()
        if not (
            hostname.endswith(".test")
            or "mock" in hostname
            or hostname.endswith(".local")
        ):
            raise ValueError(f"{field_label} must use a testing or mock HTTPS host")
        return

    if parsed.scheme not in {"http", "https"}:
        raise ValueError(f"{field_label} must use HTTP or HTTPS")


class AmazonSettings(BaseModel):
    """Runtime Amazon integration settings (built from app Settings)."""

    enabled: bool = False
    oauth_enabled: bool = False
    lwa_client_id: str = ""
    lwa_client_secret: str = Field(default="", repr=False)
    lwa_token_url: str = DEFAULT_LWA_TOKEN_URL
    sp_api_region: SpApiRegionLiteral = "na"
    endpoint_mode: AmazonEndpointMode = AmazonEndpointMode.MOCK
    user_agent: str = Field(default=DEFAULT_USER_AGENT, min_length=1, max_length=500)
    environment: str = "development"
    application_id: str = ""
    oauth_redirect_uri: str = ""
    oauth_frontend_success_url: str = ""
    oauth_frontend_error_url: str = ""
    oauth_consent_version: str = ""
    oauth_state_ttl_seconds: int = Field(
        default=OAUTH_STATE_TTL_DEFAULT_SECONDS,
        ge=OAUTH_STATE_TTL_MIN_SECONDS,
        le=OAUTH_STATE_TTL_MAX_SECONDS,
    )

    @field_validator("oauth_consent_version", mode="before")
    @classmethod
    def normalize_oauth_consent_version(cls, value: object) -> str:
        if value is None:
            return ""
        return str(value).strip()

    @model_validator(mode="after")
    def validate_amazon_settings(self) -> AmazonSettings:
        if self.environment == "testing" and self.endpoint_mode is not AmazonEndpointMode.MOCK:
            raise ValueError("Testing environment requires AMAZON_SP_API_ENDPOINT_MODE=mock")

        if self.oauth_consent_version not in ALLOWED_OAUTH_CONSENT_VERSIONS:
            raise ValueError("AMAZON_OAUTH_CONSENT_VERSION must be empty or beta")

        if self.oauth_enabled:
            if not self.enabled:
                raise ValueError("AMAZON_OAUTH_ENABLED requires AMAZON_SP_API_ENABLED=true")

            if self.environment != "testing" and self.endpoint_mode is not AmazonEndpointMode.PRODUCTION:
                raise ValueError("Amazon OAuth requires AMAZON_SP_API_ENDPOINT_MODE=production")

            oauth_missing: list[str] = []
            if not self.lwa_client_id.strip():
                oauth_missing.append("lwa_client_id")
            if not self.lwa_client_secret.strip():
                oauth_missing.append("lwa_client_secret")
            if not self.application_id.strip():
                oauth_missing.append("application_id")
            if not self.oauth_redirect_uri.strip():
                oauth_missing.append("oauth_redirect_uri")
            if not self.oauth_frontend_success_url.strip():
                oauth_missing.append("oauth_frontend_success_url")
            if not self.oauth_frontend_error_url.strip():
                oauth_missing.append("oauth_frontend_error_url")
            if oauth_missing:
                raise ValueError(
                    "Amazon OAuth enabled but missing: " + ", ".join(oauth_missing)
                )

            _validate_oauth_url(
                self.oauth_redirect_uri,
                field_label="AMAZON_OAUTH_REDIRECT_URI",
                environment=self.environment,
                allow_query=False,
            )
            _validate_oauth_url(
                self.oauth_frontend_success_url,
                field_label="AMAZON_OAUTH_FRONTEND_SUCCESS_URL",
                environment=self.environment,
                allow_query=False,
            )
            _validate_oauth_url(
                self.oauth_frontend_error_url,
                field_label="AMAZON_OAUTH_FRONTEND_ERROR_URL",
                environment=self.environment,
                allow_query=False,
            )

        if not self.enabled:
            return self

        live_modes = {AmazonEndpointMode.SANDBOX, AmazonEndpointMode.PRODUCTION}
        if self.endpoint_mode in live_modes:
            missing: list[str] = []
            if not self.lwa_client_id.strip():
                missing.append("lwa_client_id")
            if not self.lwa_client_secret.strip():
                missing.append("lwa_client_secret")
            if not self.user_agent.strip():
                missing.append("user_agent")
            if missing:
                raise ValueError(
                    "Amazon SP-API enabled for sandbox/production but missing: "
                    + ", ".join(missing)
                )

            parsed = urlparse(self.lwa_token_url)
            if parsed.scheme != "https":
                raise ValueError("AMAZON_LWA_TOKEN_URL must use HTTPS")

        if self.environment in {"staging", "production"}:
            host = urlparse(self.lwa_token_url).hostname
            if host not in ALLOWED_LWA_HOSTS:
                raise ValueError(
                    "staging/production requires official Amazon LWA host api.amazon.com"
                )

        return self

    @property
    def region(self) -> SpApiRegion:
        return self.sp_api_region

    @property
    def oauth_consent_version_for_authorize(self) -> str | None:
        if not self.oauth_consent_version:
            return None
        return self.oauth_consent_version

    @property
    def oauth_account_endpoint_mode(self) -> str:
        return OAUTH_ACCOUNT_ENDPOINT_MODE
