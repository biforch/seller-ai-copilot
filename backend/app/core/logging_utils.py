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
_AMZ_ACCESS_TOKEN_HEADER_RE = re.compile(
    r"(?i)x-amz-access-token\s*[:=]\s*\S+"
)
_AMAZON_LWA_ATZA_RE = re.compile(r"Atza\|[^\s\"'&]+")
_AMAZON_LWA_ATZR_RE = re.compile(r"Atzr\|[^\s\"'&]+")
_JSON_TOKEN_RE = re.compile(
    r'(?i)"(access_token|refresh_token|client_secret)"\s*:\s*"[^"]*"'
)
_URL_CREDENTIALS_RE = re.compile(r"://[^:@/\s]+:[^@/\s]+@")
_OAUTH_QUERY_RE = re.compile(
    r"(?i)([?&](?:code|authorization_code|spapi_oauth_code|state|selling_partner_id)=)[^&#\s]*"
)


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
    redacted = _AMZ_ACCESS_TOKEN_HEADER_RE.sub("x-amz-access-token=[REDACTED]", redacted)
    redacted = _AMAZON_LWA_ATZA_RE.sub("Atza|[REDACTED]", redacted)
    redacted = _AMAZON_LWA_ATZR_RE.sub("Atzr|[REDACTED]", redacted)
    redacted = _OAUTH_QUERY_RE.sub(r"\1[REDACTED]", redacted)
    return _URL_CREDENTIALS_RE.sub("://[REDACTED]:[REDACTED]@", redacted)


def redact_amazon_detail(text: str, *, max_len: int = 500) -> str:
    """Redact Amazon/LWA/SP-API sensitive fragments, then clip the redacted text."""
    redacted = redact_sensitive_text(text)
    redacted = _JSON_TOKEN_RE.sub(r'"\1":"[REDACTED]"', redacted)
    return redacted[:max_len]
