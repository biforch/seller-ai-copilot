"""Seller Central OAuth authorization URL builder."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlencode

from app.integrations.amazon.exceptions import (
    amazon_config_invalid_error,
    amazon_oauth_marketplace_invalid_error,
)

SpApiRegionLiteral = Literal["na", "eu", "fe"]

AUTHORIZE_CONSENT_PATH = "/apps/authorize/consent"
APPLICATION_ID_MAX_LEN = 128
STATE_MIN_LEN = 43
STATE_MAX_LEN = 128
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f]")
_URLSAFE_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]+$")

SELLER_CENTRAL_BASE_URLS: dict[str, str] = {
    "US": "https://sellercentral.amazon.com",
    "CA": "https://sellercentral.amazon.ca",
    "MX": "https://sellercentral.amazon.com.mx",
    "BR": "https://sellercentral.amazon.com.br",
    "UK": "https://sellercentral-europe.amazon.com",
    "DE": "https://sellercentral-europe.amazon.com",
    "FR": "https://sellercentral-europe.amazon.com",
    "IT": "https://sellercentral-europe.amazon.com",
    "ES": "https://sellercentral-europe.amazon.com",
    "JP": "https://sellercentral.amazon.co.jp",
    "AU": "https://sellercentral.amazon.com.au",
}

MARKETPLACE_TO_REGION: dict[str, SpApiRegionLiteral] = {
    "US": "na",
    "CA": "na",
    "MX": "na",
    "BR": "na",
    "UK": "eu",
    "DE": "eu",
    "FR": "eu",
    "IT": "eu",
    "ES": "eu",
    "JP": "fe",
    "AU": "fe",
}

ALLOWED_OAUTH_MARKETPLACE_CODES = frozenset(SELLER_CENTRAL_BASE_URLS)
ALLOWED_OAUTH_CONSENT_VERSIONS = frozenset({"beta"})


@dataclass(frozen=True)
class OAuthAuthorizationTarget:
    authorization_url: str
    marketplace_code: str
    region: SpApiRegionLiteral


def _reject_control_characters(value: str, *, field_name: str) -> None:
    if _CONTROL_CHAR_RE.search(value):
        raise amazon_config_invalid_error(f"Amazon OAuth {field_name} contains invalid characters")


def _normalize_marketplace_code(marketplace_code: object) -> str:
    if not isinstance(marketplace_code, str):
        raise amazon_oauth_marketplace_invalid_error()
    normalized = marketplace_code.strip().upper()
    if not normalized or normalized not in ALLOWED_OAUTH_MARKETPLACE_CODES:
        raise amazon_oauth_marketplace_invalid_error()
    return normalized


def _validate_application_id(application_id: object) -> str:
    if not isinstance(application_id, str):
        raise amazon_config_invalid_error("Amazon OAuth application id is invalid")
    normalized = application_id.strip()
    if not normalized:
        raise amazon_config_invalid_error("Amazon OAuth application id is required")
    if len(normalized) > APPLICATION_ID_MAX_LEN:
        raise amazon_config_invalid_error("Amazon OAuth application id is too long")
    _reject_control_characters(normalized, field_name="application id")
    return normalized


def _validate_state(state: object) -> str:
    if not isinstance(state, str):
        raise amazon_config_invalid_error("Amazon OAuth state is invalid")
    if not state:
        raise amazon_config_invalid_error("Amazon OAuth state is required")
    if len(state) < STATE_MIN_LEN or len(state) > STATE_MAX_LEN:
        raise amazon_config_invalid_error("Amazon OAuth state length is invalid")
    _reject_control_characters(state, field_name="state")
    if not _URLSAFE_TOKEN_RE.fullmatch(state):
        raise amazon_config_invalid_error("Amazon OAuth state format is invalid")
    return state


def _validate_consent_version(consent_version: str | None) -> str | None:
    if consent_version is None:
        return None
    if not isinstance(consent_version, str):
        raise amazon_config_invalid_error("Amazon OAuth consent version is invalid")
    normalized = consent_version.strip()
    if not normalized:
        return None
    if normalized not in ALLOWED_OAUTH_CONSENT_VERSIONS:
        raise amazon_config_invalid_error("Amazon OAuth consent version is invalid")
    return normalized


def build_seller_central_authorization_url(
    *,
    marketplace_code: str,
    application_id: str,
    state: str,
    consent_version: str | None,
) -> OAuthAuthorizationTarget:
    """Build a Seller Central consent URL from allowlisted marketplace metadata."""
    normalized_marketplace = _normalize_marketplace_code(marketplace_code)
    normalized_application_id = _validate_application_id(application_id)
    normalized_state = _validate_state(state)
    normalized_consent_version = _validate_consent_version(consent_version)

    base_url = SELLER_CENTRAL_BASE_URLS[normalized_marketplace]
    region = MARKETPLACE_TO_REGION[normalized_marketplace]

    query: dict[str, str] = {
        "application_id": normalized_application_id,
        "state": normalized_state,
    }
    if normalized_consent_version == "beta":
        query["version"] = "beta"

    authorization_url = f"{base_url}{AUTHORIZE_CONSENT_PATH}?{urlencode(query)}"
    return OAuthAuthorizationTarget(
        authorization_url=authorization_url,
        marketplace_code=normalized_marketplace,
        region=region,
    )
