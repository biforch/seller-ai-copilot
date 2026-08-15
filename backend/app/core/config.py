from __future__ import annotations

from typing import Literal

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

    CORS_ORIGINS: str = "http://localhost:3000"

    APP_NAME: str = "SellerAI Copilot"
    DEBUG: bool = False

    AMAZON_SP_API_ENABLED: bool = False
    AMAZON_LWA_CLIENT_ID: str = ""
    AMAZON_LWA_CLIENT_SECRET: str = ""
    AMAZON_LWA_TOKEN_URL: str = "https://api.amazon.com/auth/o2/token"
    AMAZON_SP_API_REGION: Literal["na", "eu", "fe"] = "na"
    AMAZON_SP_API_ENDPOINT_MODE: Literal["mock", "sandbox", "production"] = "mock"
    AMAZON_SP_API_USER_AGENT: str = "SellerAI-Copilot/1.0.0 (Language=Python)"

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: object) -> str:
        if isinstance(value, list):
            return ",".join(str(item) for item in value)
        return str(value)

    @property
    def cors_origins_list(self) -> list[str]:
        if self.CORS_ORIGINS == "*":
            return ["*"]
        return [item.strip() for item in self.CORS_ORIGINS.split(",") if item.strip()]

    @property
    def is_dev_like(self) -> bool:
        return self.ENVIRONMENT in {"development", "testing"}

    @property
    def amazon_settings(self) -> AmazonSettings:
        return AmazonSettings(
            enabled=self.AMAZON_SP_API_ENABLED,
            lwa_client_id=self.AMAZON_LWA_CLIENT_ID,
            lwa_client_secret=self.AMAZON_LWA_CLIENT_SECRET,
            lwa_token_url=self.AMAZON_LWA_TOKEN_URL,
            sp_api_region=self.AMAZON_SP_API_REGION,
            endpoint_mode=AmazonEndpointMode(self.AMAZON_SP_API_ENDPOINT_MODE),
            user_agent=self.AMAZON_SP_API_USER_AGENT,
            environment=self.ENVIRONMENT,
        )

    @model_validator(mode="after")
    def validate_environment(self) -> Settings:
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
            if self.AMAZON_SP_API_ENDPOINT_MODE != "mock":
                raise ValueError(
                    "Testing environment requires AMAZON_SP_API_ENDPOINT_MODE=mock"
                )
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
            _ = self.amazon_settings
            return self

        if not self.JWT_SECRET_KEY or self.JWT_SECRET_KEY in WEAK_JWT_SECRETS:
            raise ValueError("JWT_SECRET_KEY must be set to a strong non-default secret")
        if len(self.JWT_SECRET_KEY) < 32:
            raise ValueError("JWT_SECRET_KEY must be at least 32 characters")
        if not self.OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY is required")
        if self.DEBUG:
            raise ValueError("DEBUG must remain false outside development/testing")
        _ = self.amazon_settings
        return self


settings = Settings()
