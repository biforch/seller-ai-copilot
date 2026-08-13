"""SQLAlchemy attribute helpers for mypy-safe ORM access."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, TypeVar

T = TypeVar("T")


def orm_str(value: object) -> str:
    return str(value)


def orm_int(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    return int(str(value))


def orm_uuid(value: object) -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))


def orm_optional_str(value: object | None) -> str | None:
    if value is None:
        return None
    return str(value)


def orm_dict(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def orm_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    raise TypeError("Expected datetime")
