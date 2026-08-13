"""Shared Pydantic field helpers and validation limits."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from pydantic import BeforeValidator, Field, PlainSerializer

# Amazon-oriented limits aligned with DB columns and listing constraints.
NAME_MAX = 255
DESCRIPTION_MAX = 1000
CATEGORY_MAX = 100
TARGET_CUSTOMER_MAX = 255
ADVANTAGE_ITEM_MAX = 200
ADVANTAGES_MAX_COUNT = 20
LISTING_TITLE_MAX = 230
LISTING_DESCRIPTION_MAX = 10000
LISTING_BULLET_MAX = 500
LISTING_BULLETS_COUNT = 5
LISTING_KEYWORDS_COUNT = 10
KEYWORDS_OUTPUT_COUNT = 15
ANALYZE_POINTS_COUNT = 3
PLATFORM_MAX = 50
MARKET_MAX = 50


def _strip_required(value: Any) -> str:
    if not isinstance(value, str):
        raise TypeError("string required")
    stripped = value.strip()
    if not stripped:
        raise ValueError("must not be blank")
    return stripped


def _strip_optional(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("string required")
    stripped = value.strip()
    if not stripped:
        raise ValueError("must not be blank")
    return stripped


def _validate_uuid(value: Any) -> str:
    if isinstance(value, uuid.UUID):
        return str(value)
    if not isinstance(value, str):
        raise TypeError("UUID string required")
    stripped = value.strip()
    try:
        parsed = uuid.UUID(stripped)
    except ValueError as exc:
        raise ValueError("invalid UUID format") from exc
    return str(parsed)


RequiredStr = Annotated[str, BeforeValidator(_strip_required)]
OptionalStr = Annotated[str | None, BeforeValidator(_strip_optional)]
UuidStr = Annotated[str, BeforeValidator(_validate_uuid), PlainSerializer(lambda v: v, return_type=str)]

NameField = Annotated[RequiredStr, Field(max_length=NAME_MAX)]
CategoryField = Annotated[RequiredStr, Field(max_length=CATEGORY_MAX)]
OptionalCategoryField = Annotated[OptionalStr, Field(default=None, max_length=CATEGORY_MAX)]
DescriptionField = Annotated[OptionalStr, Field(default=None, max_length=DESCRIPTION_MAX)]
TargetCustomerField = Annotated[OptionalStr, Field(default=None, max_length=TARGET_CUSTOMER_MAX)]
PlatformField = Annotated[str, Field(default="Amazon", max_length=PLATFORM_MAX)]
MarketField = Annotated[str, Field(default="USA", max_length=MARKET_MAX)]
ProjectIdField = UuidStr
ProductIdField = UuidStr
ListingTitleField = Annotated[RequiredStr, Field(max_length=LISTING_TITLE_MAX)]
ListingDescriptionField = Annotated[str, Field(max_length=LISTING_DESCRIPTION_MAX)]
AnalyzeDescriptionField = Annotated[str, Field(max_length=LISTING_DESCRIPTION_MAX)]
