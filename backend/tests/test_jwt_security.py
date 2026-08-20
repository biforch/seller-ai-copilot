"""JWT authentication security regressions for cookie-internal signing only."""

from __future__ import annotations

import base64
import json
import logging
from datetime import datetime, timedelta

import pytest
from jose import jwt

from app.core.config import settings
from app.core.exceptions import AUTH_SESSION_INVALID, AppException
from app.core.security import create_access_token, decode_token

CANARY_TOKEN = "canary.jwt.token.value.must-not-leak"
TEST_SECRET = settings.JWT_SECRET_KEY
TEST_ORIGIN = "http://localhost:3000"


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _build_unsigned_token(*, algorithm: str, payload: dict) -> str:
    header = _b64url(json.dumps({"alg": algorithm, "typ": "JWT"}, separators=(",", ":")).encode())
    body = _b64url(json.dumps(payload, separators=(",", ":")).encode())
    return f"{header}.{body}."


def _swap_header_alg(token: str, new_alg: str) -> str:
    header_b64, payload_b64, signature = token.split(".")
    header = json.loads(_b64url_decode(header_b64))
    header["alg"] = new_alg
    new_header_b64 = _b64url(json.dumps(header, separators=(",", ":")).encode())
    return f"{new_header_b64}.{payload_b64}.{signature}"


def _tamper_signature_bitflip(token: str) -> str:
    header_b64, payload_b64, signature_b64 = token.split(".")
    signature_bytes = bytearray(_b64url_decode(signature_b64))
    if not signature_bytes:
        raise AssertionError("JWT signature segment must not be empty")
    signature_bytes[0] ^= 0x01
    tampered_signature_b64 = _b64url(bytes(signature_bytes))
    tampered = f"{header_b64}.{payload_b64}.{tampered_signature_b64}"
    assert tampered != token
    assert _b64url_decode(tampered_signature_b64) != _b64url_decode(signature_b64)
    assert tampered.split(".")[:2] == [header_b64, payload_b64]
    return tampered


def test_create_and_decode_access_token_round_trip() -> None:
    token = create_access_token({"sub": "user-1", "email": "user@example.com"})
    payload = decode_token(token)
    assert payload["sub"] == "user-1"
    assert payload["email"] == "user@example.com"
    assert "exp" in payload


def test_expired_token_is_rejected() -> None:
    expired = create_access_token(
        {"sub": "user-1"},
        expires_delta=timedelta(minutes=-1),
    )
    with pytest.raises(AppException) as exc_info:
        decode_token(expired)
    assert exc_info.value.code == 401
    assert exc_info.value.error_code == AUTH_SESSION_INVALID


def test_malformed_token_is_rejected() -> None:
    with pytest.raises(AppException) as exc_info:
        decode_token("not-a-valid-jwt")
    assert exc_info.value.code == 401


def test_invalid_signature_is_rejected() -> None:
    token = create_access_token({"sub": "user-1"})
    tampered = _tamper_signature_bitflip(token)
    with pytest.raises(AppException) as exc_info:
        decode_token(tampered)
    assert exc_info.value.code == 401


def test_alg_none_token_is_rejected() -> None:
    token = _build_unsigned_token(
        algorithm="none",
        payload={"sub": "attacker", "exp": int((datetime.utcnow() + timedelta(hours=1)).timestamp())},
    )
    with pytest.raises(AppException) as exc_info:
        decode_token(token)
    assert exc_info.value.code == 401


@pytest.mark.parametrize("algorithm", ["HS384", "HS512"])
def test_non_allowlisted_hmac_algorithm_is_rejected(algorithm: str) -> None:
    token = jwt.encode(
        {"sub": "attacker", "exp": datetime.utcnow() + timedelta(hours=1)},
        TEST_SECRET,
        algorithm=algorithm,
    )
    with pytest.raises(AppException) as exc_info:
        decode_token(token)
    assert exc_info.value.code == 401


@pytest.mark.parametrize("algorithm", ["RS256", "ES256"])
def test_non_allowlisted_asymmetric_algorithm_is_rejected(algorithm: str) -> None:
    valid = create_access_token({"sub": "user-1"})
    token = _swap_header_alg(valid, algorithm)
    with pytest.raises(AppException) as exc_info:
        decode_token(token)
    assert exc_info.value.code == 401


def test_header_algorithm_cannot_override_server_allowlist() -> None:
    valid = create_access_token({"sub": "user-1"})
    token = _swap_header_alg(valid, "HS512")
    with pytest.raises(AppException) as exc_info:
        decode_token(token)
    assert exc_info.value.code == 401


def test_bearer_header_does_not_authenticate(client, user_factory) -> None:
    user = user_factory("bearer-rejected@example.com")
    token = create_access_token({"sub": str(user.id), "email": user.email})
    response = client.get(
        "/api/v1/projects",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 401
    assert response.json()["error_code"] == AUTH_SESSION_INVALID
    assert "WWW-Authenticate" not in response.headers


def test_valid_bearer_with_invalid_cookie_still_fails(client, user_factory) -> None:
    user = user_factory("dual-credential@example.com")
    token = create_access_token({"sub": str(user.id), "email": user.email})
    client.cookies.set("sellerai_session", "not-a-valid-session")
    response = client.get(
        "/api/v1/projects",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 401
    assert response.json()["error_code"] == AUTH_SESSION_INVALID


def test_decode_error_response_does_not_echo_token() -> None:
    with pytest.raises(AppException) as exc_info:
        decode_token(CANARY_TOKEN)
    assert CANARY_TOKEN not in str(exc_info.value.message)


def test_decode_error_does_not_log_token(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.ERROR):
        with pytest.raises(AppException):
            decode_token(CANARY_TOKEN)
    assert CANARY_TOKEN not in caplog.text


def test_jwt_algorithm_setting_remains_hs256_only() -> None:
    assert settings.JWT_ALGORITHM == "HS256"
