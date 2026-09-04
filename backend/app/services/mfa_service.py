"""Mandatory TOTP MFA with encrypted secrets and single-use recovery codes."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import settings

_ENVELOPE_PREFIX = b"MFA1"
_NONCE_BYTES = 12
_AES_GCM_TAG_BYTES = 16
_TOTP_PERIOD_SECONDS = 30


class MfaService:
    def __init__(self, encoded_key: str | None = None) -> None:
        key = base64.b64decode(
            encoded_key if encoded_key is not None else settings.MFA_ENCRYPTION_KEY,
            validate=True,
        )
        if len(key) != 32:
            raise ValueError("MFA_ENCRYPTION_KEY must be base64-encoded 32 bytes")
        self._key = key
        self._cipher = AESGCM(key)

    @staticmethod
    def generate_secret() -> str:
        return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")

    @staticmethod
    def _aad(user_id: str) -> bytes:
        return f"sellerai:mfa-secret:v1:{user_id}".encode()

    def encrypt_secret(self, secret: str, *, user_id: str) -> bytes:
        nonce = secrets.token_bytes(_NONCE_BYTES)
        ciphertext = self._cipher.encrypt(nonce, secret.encode("ascii"), self._aad(user_id))
        return _ENVELOPE_PREFIX + nonce + ciphertext

    def decrypt_secret(self, value: bytes, *, user_id: str) -> str:
        minimum_size = _NONCE_BYTES + _AES_GCM_TAG_BYTES
        if value.startswith(_ENVELOPE_PREFIX):
            if len(value) < len(_ENVELOPE_PREFIX) + minimum_size:
                raise ValueError("Unsupported MFA secret envelope")
            nonce_start = len(_ENVELOPE_PREFIX)
            nonce_end = nonce_start + _NONCE_BYTES
            plaintext = self._cipher.decrypt(
                value[nonce_start:nonce_end], value[nonce_end:], self._aad(user_id)
            )
            return plaintext.decode("ascii")

        # Legacy Sprint 0.5 records used nonce || ciphertext and the raw user ID
        # as AAD. Keep read compatibility so existing users are not locked out;
        # successful verification rewrites the value using the MFA1 envelope.
        if len(value) < minimum_size:
            raise ValueError("Unsupported MFA secret envelope")
        plaintext = self._cipher.decrypt(
            value[:_NONCE_BYTES], value[_NONCE_BYTES:], user_id.encode()
        )
        return plaintext.decode("ascii")

    @staticmethod
    def needs_envelope_upgrade(value: bytes) -> bool:
        return not value.startswith(_ENVELOPE_PREFIX)

    @staticmethod
    def provisioning_uri(secret: str, *, email: str) -> str:
        label = quote(f"Listnara:{email}", safe="")
        return (
            f"otpauth://totp/{label}?secret={secret}&issuer=Listnara"
            "&algorithm=SHA1&digits=6&period=30"
        )

    @staticmethod
    def _totp(secret: str, counter: int) -> str:
        padded = secret + "=" * ((8 - len(secret) % 8) % 8)
        key = base64.b32decode(padded, casefold=True)
        digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
        offset = digest[-1] & 15
        value = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
        return f"{value % 1_000_000:06d}"

    def matching_totp_counter(
        self, secret: str, code: str, *, now: int | None = None
    ) -> int | None:
        if len(code) != 6 or not code.isdigit():
            return None
        counter = (now if now is not None else int(time.time())) // _TOTP_PERIOD_SECONDS
        for drift in (-1, 0, 1):
            candidate = counter + drift
            if candidate >= 0 and hmac.compare_digest(self._totp(secret, candidate), code):
                return candidate
        return None

    @staticmethod
    def generate_recovery_codes(count: int = 10) -> list[str]:
        if count < 1 or count > 20:
            raise ValueError("Recovery code count must be between 1 and 20")
        return [secrets.token_urlsafe(18) for _ in range(count)]

    def hash_recovery_code(self, code: str) -> str:
        normalized = code.strip().encode("utf-8")
        return hmac.new(
            self._key,
            b"sellerai:mfa-recovery:v1:" + normalized,
            hashlib.sha256,
        ).hexdigest()

    @staticmethod
    def hash_legacy_recovery_code(code: str) -> str:
        return hashlib.sha256(code.lower().strip().encode()).hexdigest()

    @staticmethod
    def find_recovery_hash(
        candidate: str,
        stored_hashes: list[str],
        *,
        legacy_candidate: str | None = None,
    ) -> str | None:
        for stored_hash in stored_hashes:
            if hmac.compare_digest(candidate, stored_hash) or (
                legacy_candidate is not None
                and hmac.compare_digest(legacy_candidate, stored_hash)
            ):
                return stored_hash
        return None


mfa_service = MfaService()
