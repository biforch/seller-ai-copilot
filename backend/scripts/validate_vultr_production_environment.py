"""Fail closed before a Vultr internal-RC migration without printing secrets."""

from __future__ import annotations

import base64
import binascii
import os
from dataclasses import dataclass
from urllib.parse import urlparse

SUCCESS_MESSAGE = "vultr production environment validation passed"
FAILURE_MESSAGE = "VULTR_PRODUCTION_ENVIRONMENT_INVALID"
EXPECTED_ORIGIN = "https://app.listnara.com"
ALLOWED_AI_BASE_URLS = frozenset(
    {"https://api.openai.com/v1", "https://openrouter.ai/api/v1"}
)


@dataclass(frozen=True)
class VultrProductionEnvironmentError(Exception):
    reason_code: str


def _require(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise VultrProductionEnvironmentError(f"MISSING:{name}")
    return value


def _is_true(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() == "true"


def _validate_mfa_encryption_key() -> None:
    encoded_key = _require("MFA_ENCRYPTION_KEY")
    try:
        decoded_key = base64.b64decode(encoded_key, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise VultrProductionEnvironmentError("MFA_KEY_INVALID_BASE64") from exc
    if len(decoded_key) != 32:
        raise VultrProductionEnvironmentError("MFA_KEY_INVALID_LENGTH")


def validate_vultr_production_environment() -> None:
    if _require("ENVIRONMENT") != "production":
        raise VultrProductionEnvironmentError("ENVIRONMENT_NOT_PRODUCTION")

    database_url = _require("DATABASE_URL")
    parsed_database = urlparse(database_url)
    database_name = parsed_database.path.removeprefix("/")
    if parsed_database.scheme not in {"postgres", "postgresql"}:
        raise VultrProductionEnvironmentError("DATABASE_NOT_POSTGRESQL")
    if (
        not parsed_database.hostname
        or parsed_database.hostname != "postgres"
        or not database_name
        or "test" in database_name.lower()
    ):
        raise VultrProductionEnvironmentError("DATABASE_TARGET_INVALID")

    if len(_require("JWT_SECRET_KEY")) < 32:
        raise VultrProductionEnvironmentError("JWT_SECRET_TOO_SHORT")
    _validate_mfa_encryption_key()
    _require("OPENAI_API_KEY")
    if _require("OPENAI_BASE_URL") not in ALLOWED_AI_BASE_URLS:
        raise VultrProductionEnvironmentError("OPENAI_BASE_URL_INVALID")
    _require("OPENAI_MODEL")
    if _is_true("OPENAI_AMAZON_DATA_ENABLED"):
        raise VultrProductionEnvironmentError("AMAZON_AI_DATA_MUST_REMAIN_DISABLED")

    if _require("CORS_ORIGINS") != EXPECTED_ORIGIN:
        raise VultrProductionEnvironmentError("CORS_ORIGIN_INVALID")
    if not _is_true("SESSION_COOKIE_SECURE"):
        raise VultrProductionEnvironmentError("SESSION_COOKIE_NOT_SECURE")
    if os.environ.get("DEBUG", "").strip().lower() != "false":
        raise VultrProductionEnvironmentError("DEBUG_NOT_FALSE")

    if _is_true("LEGACY_GENERATION_ENABLED"):
        raise VultrProductionEnvironmentError("LEGACY_GENERATION_MUST_REMAIN_DISABLED")
    if _is_true("ANALYSIS_PUBLIC_ENABLED"):
        raise VultrProductionEnvironmentError("ANALYSIS_PUBLIC_MUST_REMAIN_DISABLED")
    if _is_true("LISTING_AUDIT_INTERNAL_ENABLED"):
        raise VultrProductionEnvironmentError("LISTING_AUDIT_MUST_REMAIN_DISABLED")
    if _is_true("AMAZON_SP_API_ENABLED") or _is_true("AMAZON_OAUTH_ENABLED"):
        raise VultrProductionEnvironmentError("AMAZON_MUST_REMAIN_DISABLED")
    if _require("AMAZON_SP_API_ENDPOINT_MODE") != "mock":
        raise VultrProductionEnvironmentError("AMAZON_ENDPOINT_NOT_MOCK")


def main() -> int:
    try:
        validate_vultr_production_environment()
    except Exception:
        print(FAILURE_MESSAGE)
        return 1
    print(SUCCESS_MESSAGE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
