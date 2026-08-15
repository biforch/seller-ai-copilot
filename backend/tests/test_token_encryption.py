from __future__ import annotations

import base64
import secrets
import uuid

import pytest

from app.integrations.amazon.exceptions import (
    AMAZON_CONFIG_INVALID,
    AMAZON_TOKEN_DECRYPTION_FAILED,
    AmazonError,
)
from app.integrations.amazon.token_encryption import (
    TokenEncryptionConfig,
    TokenEncryptionService,
    build_aad,
    decode_base64url_key,
)

FAKE_REFRESH_TOKEN = "fake-refresh-token-for-unit-test-only"
OTHER_FAKE_REFRESH_TOKEN = "other-fake-refresh-token-for-unit-test-only"


@pytest.fixture
def user_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def account_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def encryption_keys() -> tuple[bytes, bytes]:
    return secrets.token_bytes(32), secrets.token_bytes(32)


@pytest.fixture
def fingerprint_pepper() -> bytes:
    return secrets.token_bytes(32)


@pytest.fixture
def active_service(
    encryption_keys: tuple[bytes, bytes],
    fingerprint_pepper: bytes,
) -> TokenEncryptionService:
    key_v1, _key_v0 = encryption_keys
    config = TokenEncryptionConfig(
        active_key_version=1,
        keys={1: key_v1},
        fingerprint_pepper=fingerprint_pepper,
    )
    return TokenEncryptionService(config)


@pytest.fixture
def rotation_service(
    encryption_keys: tuple[bytes, bytes],
    fingerprint_pepper: bytes,
) -> TokenEncryptionService:
    key_v1, key_v0 = encryption_keys
    config = TokenEncryptionConfig(
        active_key_version=1,
        keys={0: key_v0, 1: key_v1},
        fingerprint_pepper=fingerprint_pepper,
    )
    return TokenEncryptionService(config)


def test_encrypt_decrypt_round_trip(
    active_service: TokenEncryptionService,
    user_id: uuid.UUID,
    account_id: uuid.UUID,
) -> None:
    ciphertext, version = active_service.encrypt_refresh_token(
        FAKE_REFRESH_TOKEN,
        user_id=user_id,
        account_id=account_id,
    )
    plaintext = active_service.decrypt_refresh_token(
        ciphertext,
        user_id=user_id,
        account_id=account_id,
        key_version=version,
    )
    assert plaintext == FAKE_REFRESH_TOKEN


def test_same_plaintext_produces_different_ciphertext(
    active_service: TokenEncryptionService,
    user_id: uuid.UUID,
    account_id: uuid.UUID,
) -> None:
    first, _ = active_service.encrypt_refresh_token(
        FAKE_REFRESH_TOKEN,
        user_id=user_id,
        account_id=account_id,
    )
    second, _ = active_service.encrypt_refresh_token(
        FAKE_REFRESH_TOKEN,
        user_id=user_id,
        account_id=account_id,
    )
    assert first != second


def test_fingerprint_is_stable_for_same_token(
    active_service: TokenEncryptionService,
) -> None:
    first = active_service.fingerprint_refresh_token(FAKE_REFRESH_TOKEN)
    second = active_service.fingerprint_refresh_token(FAKE_REFRESH_TOKEN)
    assert first == second
    assert len(first) == 64


def test_fingerprint_differs_for_different_tokens(
    active_service: TokenEncryptionService,
) -> None:
    first = active_service.fingerprint_refresh_token(FAKE_REFRESH_TOKEN)
    second = active_service.fingerprint_refresh_token(OTHER_FAKE_REFRESH_TOKEN)
    assert first != second


def test_decrypt_with_wrong_key_version_fails(
    rotation_service: TokenEncryptionService,
    user_id: uuid.UUID,
    account_id: uuid.UUID,
) -> None:
    ciphertext, version = rotation_service.encrypt_refresh_token(
        FAKE_REFRESH_TOKEN,
        user_id=user_id,
        account_id=account_id,
        key_version=0,
    )
    assert version == 0
    with pytest.raises(AmazonError) as exc_info:
        rotation_service.decrypt_refresh_token(
            ciphertext,
            user_id=user_id,
            account_id=account_id,
            key_version=1,
        )
    assert exc_info.value.error_code == AMAZON_TOKEN_DECRYPTION_FAILED
    assert exc_info.value.__cause__ is None


def test_decrypt_with_unknown_key_version_fails(
    active_service: TokenEncryptionService,
    user_id: uuid.UUID,
    account_id: uuid.UUID,
) -> None:
    ciphertext, _ = active_service.encrypt_refresh_token(
        FAKE_REFRESH_TOKEN,
        user_id=user_id,
        account_id=account_id,
    )
    with pytest.raises(AmazonError) as exc_info:
        active_service.decrypt_refresh_token(
            ciphertext,
            user_id=user_id,
            account_id=account_id,
            key_version=99,
        )
    assert exc_info.value.error_code == AMAZON_TOKEN_DECRYPTION_FAILED


def test_malformed_envelope_fails(
    active_service: TokenEncryptionService,
    user_id: uuid.UUID,
    account_id: uuid.UUID,
) -> None:
    with pytest.raises(AmazonError) as exc_info:
        active_service.decrypt_refresh_token(
            b"short",
            user_id=user_id,
            account_id=account_id,
            key_version=1,
        )
    assert exc_info.value.error_code == AMAZON_TOKEN_DECRYPTION_FAILED


def test_tampered_ciphertext_fails(
    active_service: TokenEncryptionService,
    user_id: uuid.UUID,
    account_id: uuid.UUID,
) -> None:
    ciphertext, version = active_service.encrypt_refresh_token(
        FAKE_REFRESH_TOKEN,
        user_id=user_id,
        account_id=account_id,
    )
    tampered = bytearray(ciphertext)
    tampered[-1] ^= 0x01
    with pytest.raises(AmazonError) as exc_info:
        active_service.decrypt_refresh_token(
            bytes(tampered),
            user_id=user_id,
            account_id=account_id,
            key_version=version,
        )
    assert exc_info.value.error_code == AMAZON_TOKEN_DECRYPTION_FAILED


def test_aad_user_mismatch_fails(
    active_service: TokenEncryptionService,
    user_id: uuid.UUID,
    account_id: uuid.UUID,
) -> None:
    ciphertext, version = active_service.encrypt_refresh_token(
        FAKE_REFRESH_TOKEN,
        user_id=user_id,
        account_id=account_id,
    )
    with pytest.raises(AmazonError) as exc_info:
        active_service.decrypt_refresh_token(
            ciphertext,
            user_id=uuid.uuid4(),
            account_id=account_id,
            key_version=version,
        )
    assert exc_info.value.error_code == AMAZON_TOKEN_DECRYPTION_FAILED


def test_aad_account_mismatch_fails(
    active_service: TokenEncryptionService,
    user_id: uuid.UUID,
    account_id: uuid.UUID,
) -> None:
    ciphertext, version = active_service.encrypt_refresh_token(
        FAKE_REFRESH_TOKEN,
        user_id=user_id,
        account_id=account_id,
    )
    with pytest.raises(AmazonError) as exc_info:
        active_service.decrypt_refresh_token(
            ciphertext,
            user_id=user_id,
            account_id=uuid.uuid4(),
            key_version=version,
        )
    assert exc_info.value.error_code == AMAZON_TOKEN_DECRYPTION_FAILED


def test_key_rotation_legacy_decrypt_and_active_encrypt(
    rotation_service: TokenEncryptionService,
    user_id: uuid.UUID,
    account_id: uuid.UUID,
) -> None:
    legacy_ciphertext, legacy_version = rotation_service.encrypt_refresh_token(
        FAKE_REFRESH_TOKEN,
        user_id=user_id,
        account_id=account_id,
        key_version=0,
    )
    assert rotation_service.decrypt_refresh_token(
        legacy_ciphertext,
        user_id=user_id,
        account_id=account_id,
        key_version=legacy_version,
    ) == FAKE_REFRESH_TOKEN

    active_ciphertext, active_version = rotation_service.encrypt_refresh_token(
        OTHER_FAKE_REFRESH_TOKEN,
        user_id=user_id,
        account_id=account_id,
    )
    assert active_version == rotation_service.active_key_version
    assert rotation_service.decrypt_refresh_token(
        active_ciphertext,
        user_id=user_id,
        account_id=account_id,
        key_version=active_version,
    ) == OTHER_FAKE_REFRESH_TOKEN


def test_decode_base64url_key_requires_32_bytes() -> None:
    encoded = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")
    assert len(decode_base64url_key(encoded)) == 32

    short = base64.urlsafe_b64encode(secrets.token_bytes(16)).decode().rstrip("=")
    with pytest.raises(ValueError, match="32 bytes"):
        decode_base64url_key(short)


def test_decode_base64url_key_rejects_empty() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        decode_base64url_key("")
    with pytest.raises(ValueError, match="must not be empty"):
        decode_base64url_key("   ")


def test_empty_refresh_token_rejected(active_service: TokenEncryptionService) -> None:
    with pytest.raises(AmazonError) as exc_info:
        active_service.encrypt_refresh_token(
            "",
            user_id=uuid.uuid4(),
            account_id=uuid.uuid4(),
        )
    assert exc_info.value.error_code == AMAZON_CONFIG_INVALID


def test_decryption_error_does_not_leak_plaintext_or_ciphertext(
    active_service: TokenEncryptionService,
    user_id: uuid.UUID,
    account_id: uuid.UUID,
    caplog: pytest.LogCaptureFixture,
) -> None:
    ciphertext, version = active_service.encrypt_refresh_token(
        FAKE_REFRESH_TOKEN,
        user_id=user_id,
        account_id=account_id,
    )
    tampered = bytearray(ciphertext)
    tampered[-1] ^= 0x01
    with caplog.at_level("ERROR"):
        with pytest.raises(AmazonError) as exc_info:
            active_service.decrypt_refresh_token(
                bytes(tampered),
                user_id=user_id,
                account_id=account_id,
                key_version=version,
            )
    combined = " ".join([str(exc_info.value), repr(exc_info.value), caplog.text])
    assert FAKE_REFRESH_TOKEN not in combined
    assert bytes(tampered).hex() not in combined


def test_build_aad_format(user_id: uuid.UUID, account_id: uuid.UUID) -> None:
    assert build_aad(user_id=user_id, account_id=account_id) == (
        f"amazon:refresh_token:v1:{user_id}:{account_id}".encode()
    )


@pytest.mark.parametrize("invalid_version", [-1, 65536])
def test_encrypt_rejects_invalid_key_version(
    active_service: TokenEncryptionService,
    user_id: uuid.UUID,
    account_id: uuid.UUID,
    invalid_version: int,
) -> None:
    with pytest.raises(AmazonError) as exc_info:
        active_service.encrypt_refresh_token(
            FAKE_REFRESH_TOKEN,
            user_id=user_id,
            account_id=account_id,
            key_version=invalid_version,
        )
    assert exc_info.value.error_code == AMAZON_CONFIG_INVALID


@pytest.mark.parametrize("invalid_version", [-1, 65536])
def test_decrypt_rejects_invalid_key_version_param(
    active_service: TokenEncryptionService,
    user_id: uuid.UUID,
    account_id: uuid.UUID,
    invalid_version: int,
) -> None:
    ciphertext, _ = active_service.encrypt_refresh_token(
        FAKE_REFRESH_TOKEN,
        user_id=user_id,
        account_id=account_id,
    )
    with pytest.raises(AmazonError) as exc_info:
        active_service.decrypt_refresh_token(
            ciphertext,
            user_id=user_id,
            account_id=account_id,
            key_version=invalid_version,
        )
    assert exc_info.value.error_code == AMAZON_TOKEN_DECRYPTION_FAILED


@pytest.mark.parametrize(
    "payload",
    [
        b"",
        bytes([1, 0, 1]),
        bytes([1, 0, 1]) + b"x" * 11,
        bytes([2, 0, 1]) + b"x" * 12 + b"tag-not-enough",
    ],
    ids=["empty", "header-only", "missing-nonce", "unsupported-format"],
)
def test_malformed_envelope_variants_fail(
    active_service: TokenEncryptionService,
    user_id: uuid.UUID,
    account_id: uuid.UUID,
    payload: bytes,
) -> None:
    with pytest.raises(AmazonError) as exc_info:
        active_service.decrypt_refresh_token(
            payload,
            user_id=user_id,
            account_id=account_id,
            key_version=1,
        )
    assert exc_info.value.error_code == AMAZON_TOKEN_DECRYPTION_FAILED


def test_token_encryption_config_rejects_empty_pepper(encryption_keys: tuple[bytes, bytes]) -> None:
    key_v1, _ = encryption_keys
    with pytest.raises(ValueError, match="pepper"):
        TokenEncryptionConfig(
            active_key_version=1,
            keys={1: key_v1},
            fingerprint_pepper=b"",
        )


def test_token_encryption_config_rejects_missing_active_key(fingerprint_pepper: bytes) -> None:
    with pytest.raises(ValueError, match="active key version"):
        TokenEncryptionConfig(
            active_key_version=1,
            keys={},
            fingerprint_pepper=fingerprint_pepper,
        )


def test_decode_base64url_key_rejects_wrong_lengths() -> None:
    thirty_one = base64.urlsafe_b64encode(secrets.token_bytes(31)).decode().rstrip("=")
    thirty_three = base64.urlsafe_b64encode(secrets.token_bytes(33)).decode().rstrip("=")
    with pytest.raises(ValueError, match="32 bytes"):
        decode_base64url_key(thirty_one)
    with pytest.raises(ValueError, match="32 bytes"):
        decode_base64url_key(thirty_three)


def test_decode_base64url_key_rejects_invalid_base64() -> None:
    with pytest.raises(ValueError, match="invalid base64url"):
        decode_base64url_key("A===")
