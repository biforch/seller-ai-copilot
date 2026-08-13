"""Idempotency key validation and canonical request hashing."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from fastapi import status

from app.core.exceptions import AppException

IDEMPOTENCY_KEY_HEADER = "Idempotency-Key"
IDEMPOTENCY_KEY_MAX_LENGTH = 36
UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


class MissingIdempotencyKey(AppException):
    def __init__(self) -> None:
        super().__init__(
            message="Idempotency-Key header is required",
            code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Provide a UUID in the {IDEMPOTENCY_KEY_HEADER} header",
        )


def require_idempotency_key(raw: str | None) -> str:
    """Validate required Idempotency-Key header (UUID format)."""
    if raw is None:
        raise MissingIdempotencyKey()

    key = raw.strip()
    if not key:
        raise MissingIdempotencyKey()

    if len(key) > IDEMPOTENCY_KEY_MAX_LENGTH:
        raise AppException(
            message="Invalid Idempotency-Key",
            code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Idempotency-Key must be at most {IDEMPOTENCY_KEY_MAX_LENGTH} characters",
        )

    if not UUID_PATTERN.match(key):
        raise AppException(
            message="Invalid Idempotency-Key",
            code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Idempotency-Key must be a UUID",
        )

    return key.lower()


def canonical_request_hash(payload: dict[str, Any]) -> str:
    """Hash normalized business input; excludes unstable/request metadata."""
    normalized = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
