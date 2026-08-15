"""Amazon SP-API region, endpoint, and marketplace constants."""

from __future__ import annotations

from typing import Literal

SpApiRegion = Literal["na", "eu", "fe"]
EndpointMode = Literal["mock", "sandbox", "production"]

SP_API_BASE_URLS: dict[SpApiRegion, dict[EndpointMode, str]] = {
    "na": {
        "production": "https://sellingpartnerapi-na.amazon.com",
        "sandbox": "https://sandbox.sellingpartnerapi-na.amazon.com",
        "mock": "https://mock.sp-api.local",
    },
    "eu": {
        "production": "https://sellingpartnerapi-eu.amazon.com",
        "sandbox": "https://sandbox.sellingpartnerapi-eu.amazon.com",
        "mock": "https://mock.sp-api.local",
    },
    "fe": {
        "production": "https://sellingpartnerapi-fe.amazon.com",
        "sandbox": "https://sandbox.sellingpartnerapi-fe.amazon.com",
        "mock": "https://mock.sp-api.local",
    },
}

# Common marketplace country codes → Amazon marketplaceId (NA-focused defaults).
MARKETPLACE_IDS: dict[str, str] = {
    "US": "ATVPDKIKX0DER",
    "CA": "A2EUQ1WTGCTBG2",
    "MX": "A1AM78C64UM0Y8",
    "BR": "A2Q3Y263D00KWC",
    "UK": "A1F83G8C2ARO7P",
    "DE": "A1PA6795UKMFR9",
    "FR": "A13V1IB3VIYZZH",
    "IT": "APJ6JRA9NG5V4",
    "ES": "A1RKKUPIHCS9HS",
    "JP": "A1VC38T7YXB528",
    "AU": "A39IBJ37TRP1C6",
}

DEFAULT_LWA_TOKEN_URL = "https://api.amazon.com/auth/o2/token"
DEFAULT_USER_AGENT = "SellerAI-Copilot/1.0.0 (Language=Python)"


def resolve_sp_api_base_url(*, region: SpApiRegion, endpoint_mode: EndpointMode) -> str:
    return SP_API_BASE_URLS[region][endpoint_mode]


def resolve_marketplace_id(country_code: str) -> str:
    normalized = country_code.strip().upper()
    marketplace_id = MARKETPLACE_IDS.get(normalized)
    if marketplace_id is None:
        raise KeyError(f"Unknown marketplace country code: {country_code}")
    return marketplace_id
