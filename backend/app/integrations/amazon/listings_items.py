"""Typed Listings Items API contracts and single-page search client."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from app.integrations.amazon.client import SpApiClient
from app.integrations.amazon.exceptions import (
    amazon_config_invalid_error,
    amazon_response_invalid_error,
    amazon_selling_partner_id_required_error,
)

logger = logging.getLogger(__name__)

LISTINGS_API_VERSION = "2021-08-01"
_SEARCH_LISTINGS_OPERATION = "search_listings_items"
_REQUEST_ID_HEADER = "x-amzn-requestid"

PAGE_SIZE_MIN = 1
PAGE_SIZE_MAX = 20
PAGE_TOKEN_MAX_LENGTH = 2048
MARKETPLACE_ID_MAX_LENGTH = 32
SELLER_SKU_MAX_LENGTH = 128
STATUS_CODE_MAX_COUNT = 32
STATUS_CODE_MAX_LENGTH = 64
PRODUCT_TYPE_MAX_LENGTH = 128
ASIN_MAX_LENGTH = 16
SELLING_PARTNER_ID_MAX_LENGTH = 32

INCLUDED_DATA_ALLOWLIST = frozenset(
    {
        "summaries",
        "attributes",
        "issues",
        "offers",
        "fulfillmentAvailability",
    }
)

_CONTROL_CHAR_PATTERN = re.compile(r"[\x00-\x1f\x7f]")


def _listings_items_path(seller_id: str) -> str:
    encoded = quote(seller_id, safe="")
    return f"/listings/{LISTINGS_API_VERSION}/items/{encoded}"


def _strip_required_str(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("value must be a string")
    stripped = value.strip()
    if not stripped:
        raise ValueError("value must not be empty")
    return stripped


def _sanitize_request_id(request_id: str | None) -> str | None:
    if request_id is None:
        return None
    cleaned = request_id.strip()
    if not cleaned:
        return None
    if _CONTROL_CHAR_PATTERN.search(cleaned):
        return None
    return cleaned[:64]


def _parse_upstream_datetime(value: str) -> datetime:
    normalized = value.strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        raise ValueError("datetime must be timezone-aware")
    return parsed.astimezone(UTC)


def _normalize_status_codes(raw: object) -> tuple[str, ...]:
    if not isinstance(raw, list):
        raise ValueError("status must be a list")
    if len(raw) > STATUS_CODE_MAX_COUNT:
        raise ValueError("status list exceeds maximum length")
    normalized: list[str] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, str):
            raise ValueError("status entry must be a string")
        code = item.strip()
        if not code:
            raise ValueError("status entry must not be empty")
        if len(code) > STATUS_CODE_MAX_LENGTH:
            raise ValueError("status entry exceeds maximum length")
        if code not in seen:
            seen.add(code)
            normalized.append(code)
    return tuple(normalized)


class ListingSummaryWire(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    marketplaceId: str
    asin: str | None = None
    productType: str | None = None
    status: list[str] = []
    createdDate: str | None = None
    lastUpdatedDate: str | None = None

    _strip_marketplace = field_validator("marketplaceId", mode="before")(_strip_required_str)


class SearchListingsItemWire(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    sku: str
    summaries: list[ListingSummaryWire] = []

    _strip_sku = field_validator("sku", mode="before")(_strip_required_str)


class SearchListingsPaginationWire(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    nextToken: str | None = None

    @field_validator("nextToken", mode="before")
    @classmethod
    def _validate_next_token(cls, value: object) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("nextToken must be a string")
        stripped = value.strip()
        if not stripped:
            return None
        if len(stripped) > PAGE_TOKEN_MAX_LENGTH:
            raise ValueError("nextToken exceeds maximum length")
        return stripped


class SearchListingsItemsResponseWire(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    items: list[SearchListingsItemWire] = []
    pagination: SearchListingsPaginationWire | None = None


@dataclass(frozen=True)
class SearchListingsItem:
    seller_sku: str
    marketplace_id: str
    asin: str | None
    status_codes: tuple[str, ...]
    product_type: str | None
    upstream_created_at: datetime | None
    upstream_last_updated_at: datetime | None


@dataclass(frozen=True)
class SearchListingsItemsPage:
    items: tuple[SearchListingsItem, ...]
    next_page_token: str | None
    request_id: str | None

    def __repr__(self) -> str:
        return (
            f"SearchListingsItemsPage(item_count={len(self.items)}, "
            f"has_next_page={self.next_page_token is not None}, "
            f"request_id={self.request_id!r})"
        )


def _validate_seller_sku(seller_sku: str) -> str:
    if len(seller_sku) > SELLER_SKU_MAX_LENGTH:
        raise ValueError("seller_sku exceeds maximum length")
    return seller_sku


def _normalize_marketplace_id(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("marketplace_id must be a string")
    stripped = value.strip()
    if not stripped:
        raise ValueError("marketplace_id must not be empty")
    if len(stripped) > MARKETPLACE_ID_MAX_LENGTH:
        raise ValueError("marketplace_id exceeds maximum length")
    return stripped


def _validate_marketplace_id_for_client(marketplace_id: str) -> str:
    try:
        return _normalize_marketplace_id(marketplace_id)
    except ValueError:
        raise amazon_config_invalid_error("Listings Items marketplaceId is invalid") from None


def _validate_marketplace_id_for_mapper(marketplace_id: str) -> str:
    try:
        return _normalize_marketplace_id(marketplace_id)
    except ValueError:
        logger.warning(
            "Listings Items response validation failed operation=%s category=marketplace_param",
            _SEARCH_LISTINGS_OPERATION,
        )
        raise amazon_response_invalid_error() from None


def _validate_asin(asin: str | None) -> str | None:
    if asin is None:
        return None
    stripped = asin.strip()
    if not stripped:
        return None
    if len(stripped) > ASIN_MAX_LENGTH:
        raise ValueError("asin exceeds maximum length")
    return stripped


def _validate_product_type(product_type: str | None) -> str | None:
    if product_type is None:
        return None
    stripped = product_type.strip()
    if not stripped:
        return None
    if len(stripped) > PRODUCT_TYPE_MAX_LENGTH:
        raise ValueError("product_type exceeds maximum length")
    return stripped


def _map_item_for_marketplace(
    item: SearchListingsItemWire,
    *,
    marketplace_id: str,
) -> SearchListingsItem:
    seller_sku = _validate_seller_sku(item.sku)
    matching_summaries = [
        summary for summary in item.summaries if summary.marketplaceId == marketplace_id
    ]
    if len(matching_summaries) != 1:
        raise ValueError("expected exactly one summary for requested marketplace")

    summary = matching_summaries[0]
    status_codes = _normalize_status_codes(summary.status)
    upstream_created_at = (
        _parse_upstream_datetime(summary.createdDate) if summary.createdDate else None
    )
    upstream_last_updated_at = (
        _parse_upstream_datetime(summary.lastUpdatedDate) if summary.lastUpdatedDate else None
    )
    return SearchListingsItem(
        seller_sku=seller_sku,
        marketplace_id=marketplace_id,
        asin=_validate_asin(summary.asin),
        status_codes=status_codes,
        product_type=_validate_product_type(summary.productType),
        upstream_created_at=upstream_created_at,
        upstream_last_updated_at=upstream_last_updated_at,
    )


def map_search_listings_items_page(
    payload: Any,
    *,
    marketplace_id: str,
) -> SearchListingsItemsPage:
    """Validate Listings Items wire payload and map to immutable domain objects."""
    if not isinstance(payload, dict):
        logger.warning(
            "Listings Items response validation failed operation=%s category=top_level_type",
            _SEARCH_LISTINGS_OPERATION,
        )
        raise amazon_response_invalid_error()

    try:
        wire = SearchListingsItemsResponseWire.model_validate(payload)
    except ValidationError:
        logger.warning(
            "Listings Items response validation failed operation=%s category=schema",
            _SEARCH_LISTINGS_OPERATION,
        )
        raise amazon_response_invalid_error() from None

    validated_marketplace = _validate_marketplace_id_for_mapper(marketplace_id)
    mapped_items: list[SearchListingsItem] = []
    seen_identities: set[tuple[str, str]] = set()

    for item in wire.items:
        try:
            mapped = _map_item_for_marketplace(item, marketplace_id=validated_marketplace)
        except ValueError:
            logger.warning(
                "Listings Items response validation failed operation=%s category=item_mapping",
                _SEARCH_LISTINGS_OPERATION,
            )
            raise amazon_response_invalid_error() from None

        identity = (mapped.marketplace_id, mapped.seller_sku)
        if identity in seen_identities:
            logger.warning(
                "Listings Items response validation failed operation=%s category=duplicate_identity",
                _SEARCH_LISTINGS_OPERATION,
            )
            raise amazon_response_invalid_error()
        seen_identities.add(identity)
        mapped_items.append(mapped)

    next_page_token = wire.pagination.nextToken if wire.pagination is not None else None
    return SearchListingsItemsPage(
        items=tuple(mapped_items),
        next_page_token=next_page_token,
        request_id=None,
    )


def _validate_page_size(page_size: int) -> int:
    if isinstance(page_size, bool) or not isinstance(page_size, int):
        raise amazon_config_invalid_error("Listings Items pageSize must be an integer")
    if page_size < PAGE_SIZE_MIN or page_size > PAGE_SIZE_MAX:
        raise amazon_config_invalid_error("Listings Items pageSize must be between 1 and 20")
    return page_size


def _validate_page_token(page_token: str | None) -> str | None:
    if page_token is None:
        return None
    if not isinstance(page_token, str):
        raise amazon_config_invalid_error("Listings Items pageToken must be a string")
    stripped = page_token.strip()
    if not stripped:
        raise amazon_config_invalid_error("Listings Items pageToken must not be empty")
    if len(stripped) > PAGE_TOKEN_MAX_LENGTH:
        raise amazon_config_invalid_error("Listings Items pageToken exceeds maximum length")
    return stripped


def _validate_included_data(included_data: tuple[str, ...]) -> tuple[str, ...]:
    if not included_data:
        raise amazon_config_invalid_error("Listings Items includedData must not be empty")
    normalized: list[str] = []
    seen: set[str] = set()
    for value in included_data:
        if not isinstance(value, str):
            raise amazon_config_invalid_error("Listings Items includedData entries must be strings")
        stripped = value.strip()
        if not stripped:
            raise amazon_config_invalid_error("Listings Items includedData entries must not be empty")
        if stripped not in INCLUDED_DATA_ALLOWLIST:
            raise amazon_config_invalid_error("Listings Items includedData contains unsupported value")
        if stripped not in seen:
            seen.add(stripped)
            normalized.append(stripped)
    return tuple(sorted(normalized))


def _validate_seller_id(seller_id: str) -> str:
    if not isinstance(seller_id, str):
        raise amazon_selling_partner_id_required_error()
    stripped = seller_id.strip()
    if not stripped:
        raise amazon_selling_partner_id_required_error()
    if len(stripped) > SELLING_PARTNER_ID_MAX_LENGTH:
        raise amazon_config_invalid_error("Listings Items sellerId exceeds maximum length")
    return stripped


class ListingsItemsClient:
    """Typed single-page Listings Items search client."""

    def __init__(self, sp_client: SpApiClient) -> None:
        self._sp_client = sp_client

    async def search_listings_items(
        self,
        *,
        seller_id: str,
        marketplace_id: str,
        account_key: str,
        page_size: int = PAGE_SIZE_MAX,
        page_token: str | None = None,
        included_data: tuple[str, ...] = ("summaries",),
    ) -> SearchListingsItemsPage:
        validated_seller_id = _validate_seller_id(seller_id)
        validated_marketplace = _validate_marketplace_id_for_client(marketplace_id)
        validated_page_size = _validate_page_size(page_size)
        validated_page_token = _validate_page_token(page_token)
        validated_included_data = _validate_included_data(included_data)

        params: dict[str, str] = {
            "marketplaceIds": validated_marketplace,
            "pageSize": str(validated_page_size),
            "includedData": ",".join(validated_included_data),
        }
        if validated_page_token is not None:
            params["pageToken"] = validated_page_token

        response = await self._sp_client.request(
            "GET",
            _listings_items_path(validated_seller_id),
            account_key=account_key,
            params=params,
        )
        page = map_search_listings_items_page(response.payload, marketplace_id=validated_marketplace)
        request_id = _sanitize_request_id(response.headers.get(_REQUEST_ID_HEADER))
        return SearchListingsItemsPage(
            items=page.items,
            next_page_token=page.next_page_token,
            request_id=request_id,
        )
