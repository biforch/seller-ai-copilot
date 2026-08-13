"""Small helpers for safe structured logging."""

from __future__ import annotations

import re
from typing import Any
from uuid import UUID

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_BEARER_RE = re.compile(r"Bearer\s+\S+", re.IGNORECASE)
_API_KEY_RE = re.compile(r"(sk-[A-Za-z0-9_-]{8,})", re.IGNORECASE)
_JWT_RE = re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")
_TOKEN_KV_RE = re.compile(
    r"(?i)\b(access_token|refresh_token|client_secret|api_key)\s*[:=]\s*\S+"
)
_URL_CREDENTIALS_RE = re.compile(r"://[^:@/\s]+:[^@/\s]+@")


def user_log_ref(user_id: Any) -> str:
    """Stable user reference for logs without PII."""
    if isinstance(user_id, UUID):
        return f"user_id={user_id}"
    return f"user_id={user_id}"


def redact_email(email: str) -> str:
    """Mask an email address for logs."""
    if not email or not _EMAIL_RE.match(email):
        return "***"
    local, domain = email.split("@", 1)
    if not local:
        return f"***@{domain}"
    return f"{local[0]}***@{domain}"


def redact_sensitive_text(text: str) -> str:
    """Remove common secret patterns from free-form text."""
    if not text:
        return text
    redacted = _BEARER_RE.sub("Bearer [REDACTED]", text)
    redacted = _API_KEY_RE.sub("sk-[REDACTED]", redacted)
    redacted = _JWT_RE.sub("jwt:[REDACTED]", redacted)
    redacted = _TOKEN_KV_RE.sub(r"\1=[REDACTED]", redacted)
    return _URL_CREDENTIALS_RE.sub("://[REDACTED]:[REDACTED]@", redacted)
