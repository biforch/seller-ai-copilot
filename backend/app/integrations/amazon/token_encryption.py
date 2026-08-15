"""Application-layer encryption for Amazon refresh tokens."""

from __future__ import annotations

import base64
import binascii
import hmac
import os
import uuid
from dataclasses import dataclass

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.integrations.amazon.exceptions import (
    amazon_config_invalid_error,
    amazon_token_decryption_failed_error,
)

_FORMAT_VERSION = 1
_NONCE_SIZE = 12
_KEY_SIZE = 32
_GCM_TAG_SIZE = 16
_MIN_ENVELOPE_SIZE = 1 + 2 + _NONCE_SIZE + _GCM_TAG_SIZE
_MAX_KEY_VERSION = 65535
_AAD_PREFIX = "amazon:refresh_token:v1"


def _validate_key_version(version: int) -> None:
    if version < 0 or version > _MAX_KEY_VERSION:
        raise ValueError("key version out of range")


@dataclass(frozen=True)
class TokenEncryptionConfig:
    active_key_version: int
    keys: dict[int, bytes]
    fingerprint_pepper: bytes

    def __post_init__(self) -> None:
        if self.active_key_version < 1:
            raise ValueError("active_key_version must be >= 1")
        if self.active_key_version not in self.keys:
            raise ValueError("active key version must exist in keys")
        for version, key in self.keys.items():
            _validate_key_version(version)
            if len(key) != _KEY_SIZE:
                raise ValueError("encryption keys must be 32 bytes")
        if not self.fingerprint_pepper:
            raise ValueError("fingerprint pepper must not be empty")


def decode_base64url_key(value: str) -> bytes:
    stripped = value.strip()
    if not stripped:
        raise ValueError("key must not be empty")
    padding = "=" * (-len(stripped) % 4)
    try:
        raw = base64.urlsafe_b64decode(stripped + padding)
    except binascii.Error as exc:
        raise ValueError("invalid base64url key") from exc
    if len(raw) != _KEY_SIZE:
        raise ValueError("key must decode to exactly 32 bytes")
    return raw


def build_aad(*, user_id: uuid.UUID, account_id: uuid.UUID) -> bytes:
    return f"{_AAD_PREFIX}:{user_id}:{account_id}".encode()


class TokenEncryptionService:
    """Encrypt and decrypt Amazon refresh tokens with AES-256-GCM."""

    def __init__(self, config: TokenEncryptionConfig) -> None:
        self._config = config

    @property
    def active_key_version(self) -> int:
        return self._config.active_key_version

    def fingerprint_refresh_token(self, plaintext_refresh_token: str) -> str:
        if not plaintext_refresh_token:
            raise amazon_config_invalid_error("Refresh token is required")
        digest = hmac.new(
            self._config.fingerprint_pepper,
            plaintext_refresh_token.encode("utf-8"),
            digestmod="sha256",
        )
        return digest.hexdigest()

    def encrypt_refresh_token(
        self,
        plaintext_refresh_token: str,
        *,
        user_id: uuid.UUID,
        account_id: uuid.UUID,
        key_version: int | None = None,
    ) -> tuple[bytes, int]:
        if not plaintext_refresh_token:
            raise amazon_config_invalid_error("Refresh token is required")
        version = key_version if key_version is not None else self._config.active_key_version
        try:
            _validate_key_version(version)
        except ValueError as exc:
            raise amazon_config_invalid_error("Encryption key version is invalid") from exc
        key = self._config.keys.get(version)
        if key is None:
            raise amazon_config_invalid_error("Encryption key version is not configured")

        nonce = os.urandom(_NONCE_SIZE)
        aad = build_aad(user_id=user_id, account_id=account_id)
        ciphertext = AESGCM(key).encrypt(
            nonce,
            plaintext_refresh_token.encode("utf-8"),
            aad,
        )
        envelope = (
            bytes([_FORMAT_VERSION])
            + version.to_bytes(2, byteorder="big")
            + nonce
            + ciphertext
        )
        return envelope, version

    def decrypt_refresh_token(
        self,
        refresh_token_ciphertext: bytes,
        *,
        user_id: uuid.UUID,
        account_id: uuid.UUID,
        key_version: int,
    ) -> str:
        try:
            _validate_key_version(key_version)
            plaintext = self._decrypt_refresh_token_impl(
                refresh_token_ciphertext,
                user_id=user_id,
                account_id=account_id,
                key_version=key_version,
            )
        except Exception:
            raise amazon_token_decryption_failed_error() from None
        return plaintext

    def _decrypt_refresh_token_impl(
        self,
        refresh_token_ciphertext: bytes,
        *,
        user_id: uuid.UUID,
        account_id: uuid.UUID,
        key_version: int,
    ) -> str:
        if len(refresh_token_ciphertext) < _MIN_ENVELOPE_SIZE:
            raise ValueError("ciphertext envelope is too short")

        format_version = refresh_token_ciphertext[0]
        if format_version != _FORMAT_VERSION:
            raise ValueError("unsupported envelope format version")

        envelope_key_version = int.from_bytes(refresh_token_ciphertext[1:3], byteorder="big")
        _validate_key_version(envelope_key_version)
        if envelope_key_version != key_version:
            raise ValueError("envelope key version mismatch")

        key = self._config.keys.get(envelope_key_version)
        if key is None:
            raise ValueError("encryption key version is not configured")

        nonce = refresh_token_ciphertext[3 : 3 + _NONCE_SIZE]
        ciphertext = refresh_token_ciphertext[3 + _NONCE_SIZE :]
        if len(ciphertext) < _GCM_TAG_SIZE:
            raise ValueError("ciphertext missing authentication tag")
        aad = build_aad(user_id=user_id, account_id=account_id)
        plaintext_bytes = AESGCM(key).decrypt(nonce, ciphertext, aad)
        return plaintext_bytes.decode("utf-8")
