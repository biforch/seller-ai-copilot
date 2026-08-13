from __future__ import annotations

from typing import Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

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
            return self

        if not self.JWT_SECRET_KEY or self.JWT_SECRET_KEY in WEAK_JWT_SECRETS:
            raise ValueError("JWT_SECRET_KEY must be set to a strong non-default secret")
        if len(self.JWT_SECRET_KEY) < 32:
            raise ValueError("JWT_SECRET_KEY must be at least 32 characters")
        if not self.OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY is required")
        if self.DEBUG:
            raise ValueError("DEBUG must remain false outside development/testing")
        return self


settings = Settings()
