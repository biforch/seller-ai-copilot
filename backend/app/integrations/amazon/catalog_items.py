"""Typed Catalog Items API v2022-04-01 summary client."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.integrations.amazon.client import SpApiClient
from app.integrations.amazon.exceptions import (
    amazon_config_invalid_error,
    amazon_response_invalid_error,
)
from app.integrations.amazon.listings_items import _validate_marketplace_id_for_client

logger = logging.getLogger(__name__)

CATALOG_API_VERSION = "2022-04-01"
ASIN_PATTERN = re.compile(r"^[A-Z0-9]{10}$")
_CONTROL_CHAR_PATTERN = re.compile(r"[\x00-\x1f\x7f]")
_REQUEST_ID_HEADER = "x-amzn-requestid"
_OPERATION = "get_catalog_item"

SUMMARY_TEXT_MAX_LENGTH = 2000
SUMMARY_SHORT_TEXT_MAX_LENGTH = 256
PRODUCT_TYPE_MAX_LENGTH = 128
INCLUDED_DATA_ALLOWLIST = frozenset({"summaries", "productTypes"})


def _strip_required_str(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("value must be a string")
    stripped = value.strip()
    if not stripped:
        raise ValueError("value must not be empty")
    return stripped


def _catalog_item_path(asin: str) -> str:
    return f"/catalog/{CATALOG_API_VERSION}/items/{quote(asin, safe='')}"


def _normalize_asin(value: object, *, response: bool) -> str:
    if not isinstance(value, str):
        raise ValueError("asin must be a string")
    asin = value.strip()
    if not ASIN_PATTERN.fullmatch(asin):
        raise ValueError("asin format is invalid")
    return asin


def _validate_asin_for_client(value: object) -> str:
    try:
        return _normalize_asin(value, response=False)
    except ValueError:
        raise amazon_config_invalid_error("Catalog Items ASIN is invalid") from None


def _normalize_optional_text(value: str | None, *, max_length: int) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if len(normalized) > max_length or _CONTROL_CHAR_PATTERN.search(normalized):
        raise ValueError("catalog summary text is invalid")
    return normalized


def _sanitize_request_id(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized or _CONTROL_CHAR_PATTERN.search(normalized):
        return None
    return normalized[:64]


class CatalogSummaryWire(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    marketplaceId: str
    itemName: str | None = None
    brand: str | None = None
    manufacturer: str | None = None
    color: str | None = None
    size: str | None = None
    style: str | None = None
    modelNumber: str | None = None
    partNumber: str | None = None

    _strip_marketplace = field_validator("marketplaceId", mode="before")(_strip_required_str)


class CatalogProductTypeWire(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    marketplaceId: str | None = None
    productType: str | None = None


class CatalogItemWire(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    asin: str
    summaries: list[CatalogSummaryWire] = Field(default_factory=list)
    productTypes: list[CatalogProductTypeWire] = Field(default_factory=list)

    _strip_asin = field_validator("asin", mode="before")(_strip_required_str)


@dataclass(frozen=True)
class CatalogItemSummary:
    asin: str
    marketplace_id: str
    item_name: str | None
    brand: str | None
    manufacturer: str | None
    color: str | None
    size: str | None
    style: str | None
    model_number: str | None
    part_number: str | None
    product_type: str | None
    request_id: str | None = None

    def __repr__(self) -> str:
        return (
            f"CatalogItemSummary(asin={self.asin!r}, marketplace_id={self.marketplace_id!r}, "
            f"has_item_name={self.item_name is not None}, product_type={self.product_type!r}, "
            f"request_id={self.request_id!r})"
        )


def _map_catalog_item(
    payload: Any,
    *,
    expected_asin: str,
    marketplace_id: str,
) -> CatalogItemSummary:
    if not isinstance(payload, dict):
        logger.warning(
            "Catalog Items response validation failed operation=%s category=top_level_type",
            _OPERATION,
        )
        raise amazon_response_invalid_error()
    try:
        wire = CatalogItemWire.model_validate(payload)
        asin = _normalize_asin(wire.asin, response=True)
        if asin != expected_asin:
            raise ValueError("response asin mismatch")
        summaries = [item for item in wire.summaries if item.marketplaceId == marketplace_id]
        if len(summaries) != 1:
            raise ValueError("expected exactly one marketplace summary")
        summary = summaries[0]
        matching_types = [
            item
            for item in wire.productTypes
            if item.marketplaceId in {None, marketplace_id}
            and _normalize_optional_text(item.productType, max_length=PRODUCT_TYPE_MAX_LENGTH)
            is not None
        ]
        if len(matching_types) > 1:
            raise ValueError("ambiguous marketplace product type")
        product_type = (
            _normalize_optional_text(
                matching_types[0].productType,
                max_length=PRODUCT_TYPE_MAX_LENGTH,
            )
            if matching_types
            else None
        )
        return CatalogItemSummary(
            asin=asin,
            marketplace_id=marketplace_id,
            item_name=_normalize_optional_text(
                summary.itemName, max_length=SUMMARY_TEXT_MAX_LENGTH
            ),
            brand=_normalize_optional_text(
                summary.brand, max_length=SUMMARY_SHORT_TEXT_MAX_LENGTH
            ),
            manufacturer=_normalize_optional_text(
                summary.manufacturer, max_length=SUMMARY_SHORT_TEXT_MAX_LENGTH
            ),
            color=_normalize_optional_text(
                summary.color, max_length=SUMMARY_SHORT_TEXT_MAX_LENGTH
            ),
            size=_normalize_optional_text(
                summary.size, max_length=SUMMARY_SHORT_TEXT_MAX_LENGTH
            ),
            style=_normalize_optional_text(
                summary.style, max_length=SUMMARY_SHORT_TEXT_MAX_LENGTH
            ),
            model_number=_normalize_optional_text(
                summary.modelNumber, max_length=SUMMARY_SHORT_TEXT_MAX_LENGTH
            ),
            part_number=_normalize_optional_text(
                summary.partNumber, max_length=SUMMARY_SHORT_TEXT_MAX_LENGTH
            ),
            product_type=product_type,
        )
    except (ValidationError, ValueError):
        logger.warning(
            "Catalog Items response validation failed operation=%s category=schema",
            _OPERATION,
        )
        raise amazon_response_invalid_error() from None


def _validate_included_data(values: tuple[str, ...]) -> tuple[str, ...]:
    if not values:
        raise amazon_config_invalid_error("Catalog Items includedData must not be empty")
    normalized: set[str] = set()
    for value in values:
        if not isinstance(value, str) or value not in INCLUDED_DATA_ALLOWLIST:
            raise amazon_config_invalid_error(
                "Catalog Items includedData contains unsupported value"
            )
        normalized.add(value)
    if "summaries" not in normalized:
        raise amazon_config_invalid_error("Catalog Items summaries are required")
    return tuple(sorted(normalized))


class CatalogItemsClient:
    """Retrieve one bounded, marketplace-specific public catalog summary."""

    def __init__(self, sp_client: SpApiClient) -> None:
        self._sp_client = sp_client

    async def get_catalog_item(
        self,
        *,
        asin: str,
        marketplace_id: str,
        account_key: str,
        included_data: tuple[str, ...] = ("summaries", "productTypes"),
    ) -> CatalogItemSummary:
        normalized_asin = _validate_asin_for_client(asin)
        normalized_marketplace = _validate_marketplace_id_for_client(marketplace_id)
        normalized_included_data = _validate_included_data(included_data)
        response = await self._sp_client.request(
            "GET",
            _catalog_item_path(normalized_asin),
            account_key=account_key,
            params={
                "marketplaceIds": normalized_marketplace,
                "includedData": ",".join(normalized_included_data),
            },
        )
        mapped = _map_catalog_item(
            response.payload,
            expected_asin=normalized_asin,
            marketplace_id=normalized_marketplace,
        )
        return CatalogItemSummary(
            asin=mapped.asin,
            marketplace_id=mapped.marketplace_id,
            item_name=mapped.item_name,
            brand=mapped.brand,
            manufacturer=mapped.manufacturer,
            color=mapped.color,
            size=mapped.size,
            style=mapped.style,
            model_number=mapped.model_number,
            part_number=mapped.part_number,
            product_type=mapped.product_type,
            request_id=_sanitize_request_id(response.headers.get(_REQUEST_ID_HEADER)),
        )
