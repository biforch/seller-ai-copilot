"""Amazon SP-API configuration schema."""

from __future__ import annotations

from enum import Enum
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field, model_validator

from app.integrations.amazon.constants import (
    DEFAULT_LWA_TOKEN_URL,
    DEFAULT_USER_AGENT,
    SpApiRegion,
)

SpApiRegionLiteral = Literal["na", "eu", "fe"]
ALLOWED_LWA_HOSTS = frozenset({"api.amazon.com"})


class AmazonEndpointMode(str, Enum):
    MOCK = "mock"
    SANDBOX = "sandbox"
    PRODUCTION = "production"


class AmazonSettings(BaseModel):
    """Runtime Amazon integration settings (built from app Settings)."""

    enabled: bool = False
    lwa_client_id: str = ""
    lwa_client_secret: str = ""
    lwa_token_url: str = DEFAULT_LWA_TOKEN_URL
    sp_api_region: SpApiRegionLiteral = "na"
    endpoint_mode: AmazonEndpointMode = AmazonEndpointMode.MOCK
    user_agent: str = Field(default=DEFAULT_USER_AGENT, min_length=1, max_length=500)
    environment: str = "development"

    @model_validator(mode="after")
    def validate_amazon_settings(self) -> AmazonSettings:
        if self.environment == "testing" and self.endpoint_mode is not AmazonEndpointMode.MOCK:
            raise ValueError("Testing environment requires AMAZON_SP_API_ENDPOINT_MODE=mock")

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
