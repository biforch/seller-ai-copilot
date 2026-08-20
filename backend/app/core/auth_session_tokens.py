"""Auth session token hashing and cookie helpers."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import Response
from jose import jwt

from app.core.auth_session_constants import CSRF_COOKIE_NAME, CSRF_HEADER_NAME, SESSION_COOKIE_NAME
from app.core.config import settings


@dataclass(frozen=True)
class CreatedSessionTokens:
    jti: str
    jwt_token: str
    csrf_token: str
    expires_at: datetime
    max_age_seconds: int


def hash_session_secret(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def generate_jti() -> str:
    return uuid.uuid4().hex


def generate_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def secrets_equal(left: str, right: str) -> bool:
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


def session_expires_at(*, now: datetime | None = None) -> tuple[datetime, int]:
    reference = now or datetime.now(UTC)
    ttl = timedelta(minutes=settings.SESSION_TTL_MINUTES)
    expires_at = reference + ttl
    max_age_seconds = int(ttl.total_seconds())
    return expires_at, max_age_seconds


def encode_session_jwt(*, user_id: str, email: str, jti: str, expires_at: datetime) -> str:
    exp = int(expires_at.timestamp())
    payload = {
        "sub": user_id,
        "email": email,
        "jti": jti,
        "exp": exp,
        "typ": "session",
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def build_created_session(*, user_id: str, email: str) -> CreatedSessionTokens:
    jti = generate_jti()
    csrf_token = generate_csrf_token()
    expires_at, max_age_seconds = session_expires_at()
    jwt_token = encode_session_jwt(
        user_id=user_id,
        email=email,
        jti=jti,
        expires_at=expires_at,
    )
    return CreatedSessionTokens(
        jti=jti,
        jwt_token=jwt_token,
        csrf_token=csrf_token,
        expires_at=expires_at,
        max_age_seconds=max_age_seconds,
    )


def apply_session_cookies(response: Response, created: CreatedSessionTokens) -> None:
    secure = settings.resolved_session_cookie_secure
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=created.jwt_token,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
        max_age=created.max_age_seconds,
    )
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=created.csrf_token,
        httponly=False,
        secure=secure,
        samesite="lax",
        path="/",
        max_age=created.max_age_seconds,
    )


def clear_session_cookies(response: Response) -> None:
    secure = settings.resolved_session_cookie_secure
    response.delete_cookie(
        key=SESSION_COOKIE_NAME, path="/", secure=secure, httponly=True, samesite="lax"
    )
    response.delete_cookie(
        key=CSRF_COOKIE_NAME, path="/", secure=secure, httponly=False, samesite="lax"
    )


def csrf_header_name() -> str:
    return CSRF_HEADER_NAME


def csrf_cookie_name() -> str:
    return CSRF_COOKIE_NAME


def session_cookie_name() -> str:
    return SESSION_COOKIE_NAME
