"""Load token encryption configuration from application settings."""

from __future__ import annotations

from typing import Protocol

from app.integrations.amazon.exceptions import amazon_config_invalid_error
from app.integrations.amazon.token_encryption import (
    TokenEncryptionConfig,
    TokenEncryptionService,
    decode_base64url_key,
)


class TokenEncryptionSettings(Protocol):
    AMAZON_TOKEN_ACTIVE_KEY_VERSION: int
    AMAZON_TOKEN_KEY_V1: str
    AMAZON_TOKEN_KEY_V0: str
    AMAZON_TOKEN_FINGERPRINT_PEPPER: str


def load_token_encryption_config(settings: TokenEncryptionSettings) -> TokenEncryptionConfig:
    """Build encryption config from settings. Fail closed on invalid configuration."""
    try:
        active_version = settings.AMAZON_TOKEN_ACTIVE_KEY_VERSION
        if active_version < 1:
            raise ValueError("active key version must be configured")

        keys: dict[int, bytes] = {}
        if settings.AMAZON_TOKEN_KEY_V1.strip():
            keys[1] = decode_base64url_key(settings.AMAZON_TOKEN_KEY_V1)
        if settings.AMAZON_TOKEN_KEY_V0.strip():
            keys[0] = decode_base64url_key(settings.AMAZON_TOKEN_KEY_V0)

        pepper_raw = settings.AMAZON_TOKEN_FINGERPRINT_PEPPER.strip()
        if not pepper_raw:
            raise ValueError("fingerprint pepper must be configured")
        pepper = decode_base64url_key(pepper_raw)

        return TokenEncryptionConfig(
            active_key_version=active_version,
            keys=keys,
            fingerprint_pepper=pepper,
        )
    except ValueError as exc:
        raise amazon_config_invalid_error("Amazon token encryption is not configured") from exc


def build_token_encryption_service(settings: TokenEncryptionSettings) -> TokenEncryptionService:
    return TokenEncryptionService(load_token_encryption_config(settings))
