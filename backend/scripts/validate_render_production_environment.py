"""Fail closed before a Render internal RC start without printing secrets."""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse

SUCCESS_MESSAGE = "render production environment validation passed"
FAILURE_MESSAGE = "RENDER_PRODUCTION_ENVIRONMENT_INVALID"
EXPECTED_ORIGIN = "https://app.listnara.com"


@dataclass(frozen=True)
class RenderProductionEnvironmentError(Exception):
    reason_code: str


def _require(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise RenderProductionEnvironmentError(f"MISSING:{name}")
    return value


def _is_true(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() == "true"


def validate_render_production_environment() -> None:
    if _require("ENVIRONMENT") != "production":
        raise RenderProductionEnvironmentError("ENVIRONMENT_NOT_PRODUCTION")

    database_url = _require("DATABASE_URL")
    parsed_database = urlparse(database_url)
    if parsed_database.scheme not in {"postgres", "postgresql"}:
        raise RenderProductionEnvironmentError("DATABASE_NOT_POSTGRESQL")
    database_name = parsed_database.path.removeprefix("/")
    if not parsed_database.hostname or not database_name or "test" in database_name.lower():
        raise RenderProductionEnvironmentError("DATABASE_TARGET_INVALID")

    if len(_require("JWT_SECRET_KEY")) < 32:
        raise RenderProductionEnvironmentError("JWT_SECRET_TOO_SHORT")
    _require("OPENAI_API_KEY")
    if _require("OPENAI_BASE_URL") != "https://api.openai.com/v1":
        raise RenderProductionEnvironmentError("OPENAI_BASE_URL_INVALID")
    if _is_true("OPENAI_AMAZON_DATA_ENABLED"):
        raise RenderProductionEnvironmentError("AMAZON_AI_DATA_MUST_REMAIN_DISABLED")

    if _require("CORS_ORIGINS") != EXPECTED_ORIGIN:
        raise RenderProductionEnvironmentError("CORS_ORIGIN_INVALID")
    if not _is_true("SESSION_COOKIE_SECURE"):
        raise RenderProductionEnvironmentError("SESSION_COOKIE_NOT_SECURE")
    if os.environ.get("DEBUG", "").strip().lower() != "false":
        raise RenderProductionEnvironmentError("DEBUG_NOT_FALSE")
    if _require("PORT") != "8000":
        raise RenderProductionEnvironmentError("BACKEND_PORT_INVALID")
    if _is_true("ANALYSIS_PUBLIC_ENABLED"):
        raise RenderProductionEnvironmentError("ANALYSIS_PUBLIC_MUST_REMAIN_DISABLED")
    if _is_true("LISTING_AUDIT_INTERNAL_ENABLED"):
        raise RenderProductionEnvironmentError("LISTING_AUDIT_MUST_REMAIN_DISABLED")

    if _is_true("AMAZON_SP_API_ENABLED") or _is_true("AMAZON_OAUTH_ENABLED"):
        raise RenderProductionEnvironmentError("AMAZON_MUST_REMAIN_DISABLED")
    if _require("AMAZON_SP_API_ENDPOINT_MODE") != "mock":
        raise RenderProductionEnvironmentError("AMAZON_ENDPOINT_NOT_MOCK")


def main() -> int:
    try:
        validate_render_production_environment()
    except Exception:
        print(FAILURE_MESSAGE)
        return 1
    print(SUCCESS_MESSAGE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
