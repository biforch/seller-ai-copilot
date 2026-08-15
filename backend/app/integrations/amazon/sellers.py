"""Typed Sellers API contracts and read-only marketplace capability detection."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from app.integrations.amazon.client import SpApiClient
from app.integrations.amazon.exceptions import amazon_response_invalid_error

logger = logging.getLogger(__name__)

MARKETPLACE_PARTICIPATIONS_PATH = "/sellers/v1/marketplaceParticipations"
_SELLERS_OPERATION = "get_marketplace_participations"


def _strip_required_str(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("value must be a string")
    stripped = value.strip()
    if not stripped:
        raise ValueError("value must not be empty")
    return stripped


class MarketplaceWire(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    id: str
    countryCode: str
    name: str
    defaultCurrencyCode: str
    defaultLanguageCode: str
    domainName: str

    _strip_strings = field_validator(
        "id",
        "countryCode",
        "name",
        "defaultCurrencyCode",
        "defaultLanguageCode",
        "domainName",
        mode="before",
    )(_strip_required_str)


class ParticipationWire(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    isParticipating: bool
    hasSuspendedListings: bool


class MarketplaceParticipationItemWire(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    marketplace: MarketplaceWire
    participation: ParticipationWire


class MarketplaceParticipationsResponseWire(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    payload: list[MarketplaceParticipationItemWire]


@dataclass(frozen=True)
class SellerMarketplaceParticipation:
    """Read-only Sellers marketplace participation snapshot."""

    marketplace_id: str
    country_code: str
    name: str
    default_currency_code: str
    default_language_code: str
    domain_name: str
    participating: bool
    suspended_listings: bool

    @property
    def sync_eligible(self) -> bool:
        # Local read-only hint from participation flags only.
        # Does not prove Listings, Orders, Reports, or write permissions.
        return self.participating and not self.suspended_listings


def _validate_marketplace_participations_wire(
    payload: dict[str, Any],
) -> MarketplaceParticipationsResponseWire | None:
    try:
        return MarketplaceParticipationsResponseWire.model_validate(payload)
    except ValidationError:
        return None


def map_marketplace_participations(payload: Any) -> tuple[SellerMarketplaceParticipation, ...]:
    """Validate Sellers wire payload and map to immutable domain objects."""
    if not isinstance(payload, dict):
        logger.warning(
            "Sellers response validation failed operation=%s category=top_level_type",
            _SELLERS_OPERATION,
        )
        raise amazon_response_invalid_error()

    wire = _validate_marketplace_participations_wire(payload)
    if wire is None:
        logger.warning(
            "Sellers response validation failed operation=%s category=schema",
            _SELLERS_OPERATION,
        )
        raise amazon_response_invalid_error()

    participations: list[SellerMarketplaceParticipation] = []
    for item in wire.payload:
        participations.append(
            SellerMarketplaceParticipation(
                marketplace_id=item.marketplace.id,
                country_code=item.marketplace.countryCode,
                name=item.marketplace.name,
                default_currency_code=item.marketplace.defaultCurrencyCode,
                default_language_code=item.marketplace.defaultLanguageCode,
                domain_name=item.marketplace.domainName,
                participating=item.participation.isParticipating,
                suspended_listings=item.participation.hasSuspendedListings,
            )
        )
    return tuple(participations)


class SellersClient:
    """Typed read-only Sellers API client."""

    def __init__(self, sp_client: SpApiClient) -> None:
        self._sp_client = sp_client

    async def get_marketplace_participations(
        self,
        *,
        account_key: str,
    ) -> tuple[SellerMarketplaceParticipation, ...]:
        response = await self._sp_client.request(
            "GET",
            MARKETPLACE_PARTICIPATIONS_PATH,
            account_key=account_key,
        )
        return map_marketplace_participations(response.payload)
