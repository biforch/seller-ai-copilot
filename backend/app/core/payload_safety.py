"""Sanitize and bound generation request payloads before persistence."""

from __future__ import annotations

import json
from typing import Any

MAX_CANONICAL_INPUT_BYTES = 16_384
MAX_RESPONSE_PAYLOAD_BYTES = 65_536

_SENSITIVE_KEYS = frozenset(
    {
        "authorization",
        "api_key",
        "apikey",
        "access_token",
        "refresh_token",
        "password",
        "secret",
        "client_secret",
        "jwt",
        "bearer",
    }
)


def _scrub_value(key: str, value: Any) -> Any:
    if isinstance(key, str) and key.lower() in _SENSITIVE_KEYS:
        return "[REDACTED]"
    if isinstance(value, dict):
        return sanitize_payload(value)
    if isinstance(value, list):
        return [sanitize_payload(item) if isinstance(item, dict) else item for item in value]
    return value


def sanitize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in payload.items():
        cleaned[key] = _scrub_value(str(key), value)
    return cleaned


def enforce_payload_size(payload: dict[str, Any], *, max_bytes: int) -> None:
    encoded = json.dumps(payload, separators=(",", ":"), default=str)
    if len(encoded.encode("utf-8")) > max_bytes:
        raise ValueError(f"Payload exceeds {max_bytes} bytes")


def prepare_request_input(payload: dict[str, Any]) -> dict[str, Any]:
    sanitized = sanitize_payload(payload)
    enforce_payload_size(sanitized, max_bytes=MAX_CANONICAL_INPUT_BYTES)
    return sanitized


def prepare_response_payload(payload: dict[str, Any]) -> dict[str, Any]:
    sanitized = sanitize_payload(payload)
    enforce_payload_size(sanitized, max_bytes=MAX_RESPONSE_PAYLOAD_BYTES)
    return sanitized
