from __future__ import annotations

import pytest

from app.integrations.amazon.exceptions import AMAZON_CONFIG_INVALID, AmazonError
from app.integrations.amazon.token_encryption_loader import (
    build_token_encryption_service,
    load_token_encryption_config,
)
from tests.fixtures.amazon_a32 import EncryptionSettingsStub, _b64_key


def test_load_token_encryption_config_from_explicit_settings(
    test_encryption_settings: EncryptionSettingsStub,
) -> None:
    config = load_token_encryption_config(test_encryption_settings)
    assert config.active_key_version == 1
    assert 1 in config.keys
    assert len(config.fingerprint_pepper) == 32


def test_load_token_encryption_config_fail_closed_on_empty_key(
    fingerprint_pepper_bytes: bytes,
) -> None:
    settings = EncryptionSettingsStub(
        AMAZON_TOKEN_ACTIVE_KEY_VERSION=1,
        AMAZON_TOKEN_KEY_V1="",
        AMAZON_TOKEN_KEY_V0="",
        AMAZON_TOKEN_FINGERPRINT_PEPPER=_b64_key(fingerprint_pepper_bytes),
    )
    with pytest.raises(AmazonError) as exc_info:
        load_token_encryption_config(settings)
    assert exc_info.value.error_code == AMAZON_CONFIG_INVALID
    assert "AMAZON_TOKEN" not in str(exc_info.value)


def test_build_token_encryption_service(test_encryption_settings: EncryptionSettingsStub) -> None:
    service = build_token_encryption_service(test_encryption_settings)
    assert service.active_key_version == 1
