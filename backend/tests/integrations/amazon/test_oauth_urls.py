"""Seller Central OAuth authorization URL builder unit tests."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest

from app.integrations.amazon.exceptions import (
    AMAZON_CONFIG_INVALID,
    AMAZON_OAUTH_MARKETPLACE_INVALID,
    AmazonError,
)
from app.integrations.amazon.oauth_urls import (
    ALLOWED_OAUTH_MARKETPLACE_CODES,
    MARKETPLACE_TO_REGION,
    SELLER_CENTRAL_BASE_URLS,
    OAuthAuthorizationTarget,
    build_seller_central_authorization_url,
)

VALID_STATE = "A" * 43
VALID_APPLICATION_ID = "amzn1.sp.solution.example-app-id"


@pytest.mark.parametrize("marketplace_code", sorted(ALLOWED_OAUTH_MARKETPLACE_CODES))
def test_marketplace_authorization_url_host_and_region(marketplace_code: str) -> None:
    target = build_seller_central_authorization_url(
        marketplace_code=marketplace_code,
        application_id=VALID_APPLICATION_ID,
        state=VALID_STATE,
        consent_version=None,
    )
    assert isinstance(target, OAuthAuthorizationTarget)
    assert target.marketplace_code == marketplace_code
    assert target.region == MARKETPLACE_TO_REGION[marketplace_code]

    parsed = urlparse(target.authorization_url)
    assert parsed.scheme == "https"
    assert parsed.netloc == urlparse(SELLER_CENTRAL_BASE_URLS[marketplace_code]).netloc
    assert parsed.path == "/apps/authorize/consent"


def test_marketplace_code_is_normalized() -> None:
    target = build_seller_central_authorization_url(
        marketplace_code=" us ",
        application_id=VALID_APPLICATION_ID,
        state=VALID_STATE,
        consent_version=None,
    )
    assert target.marketplace_code == "US"


def test_authorization_url_query_without_beta() -> None:
    target = build_seller_central_authorization_url(
        marketplace_code="US",
        application_id=VALID_APPLICATION_ID,
        state=VALID_STATE,
        consent_version="",
    )
    query = parse_qs(urlparse(target.authorization_url).query)
    assert query == {
        "application_id": [VALID_APPLICATION_ID],
        "state": [VALID_STATE],
    }


def test_authorization_url_query_with_beta() -> None:
    target = build_seller_central_authorization_url(
        marketplace_code="US",
        application_id=VALID_APPLICATION_ID,
        state=VALID_STATE,
        consent_version="beta",
    )
    query = parse_qs(urlparse(target.authorization_url).query)
    assert query["version"] == ["beta"]


def test_application_id_is_url_encoded() -> None:
    application_id = "app id/with+chars"
    target = build_seller_central_authorization_url(
        marketplace_code="US",
        application_id=application_id,
        state=VALID_STATE,
        consent_version=None,
    )
    assert "%2F" in target.authorization_url
    assert "%2B" in target.authorization_url
    query = parse_qs(urlparse(target.authorization_url).query)
    assert query["application_id"] == [application_id]
    assert query["state"] == [VALID_STATE]


def test_authorization_url_never_includes_sensitive_or_unrequested_params() -> None:
    target = build_seller_central_authorization_url(
        marketplace_code="DE",
        application_id=VALID_APPLICATION_ID,
        state=VALID_STATE,
        consent_version="beta",
    )
    lowered = target.authorization_url.lower()
    assert "redirect_uri" not in lowered
    assert "client_secret" not in lowered
    assert "client_id" not in lowered


def test_unknown_marketplace_is_rejected() -> None:
    with pytest.raises(AmazonError) as exc_info:
        build_seller_central_authorization_url(
            marketplace_code="ZZ",
            application_id=VALID_APPLICATION_ID,
            state=VALID_STATE,
            consent_version=None,
        )
    assert exc_info.value.error_code == AMAZON_OAUTH_MARKETPLACE_INVALID


@pytest.mark.parametrize("marketplace_code", ["", "   ", 123, None])
def test_invalid_marketplace_input_types_are_rejected(marketplace_code: object) -> None:
    with pytest.raises(AmazonError) as exc_info:
        build_seller_central_authorization_url(
            marketplace_code=marketplace_code,  # type: ignore[arg-type]
            application_id=VALID_APPLICATION_ID,
            state=VALID_STATE,
            consent_version=None,
        )
    assert exc_info.value.error_code == AMAZON_OAUTH_MARKETPLACE_INVALID


@pytest.mark.parametrize("state", ["", "A" * 42, "A" * 129, "bad/token", "bad+token"])
def test_invalid_state_values_are_rejected(state: str) -> None:
    with pytest.raises(AmazonError) as exc_info:
        build_seller_central_authorization_url(
            marketplace_code="US",
            application_id=VALID_APPLICATION_ID,
            state=state,
            consent_version=None,
        )
    assert exc_info.value.error_code == AMAZON_CONFIG_INVALID


def test_application_id_control_characters_are_rejected() -> None:
    with pytest.raises(AmazonError) as exc_info:
        build_seller_central_authorization_url(
            marketplace_code="US",
            application_id="app\u0000id",
            state=VALID_STATE,
            consent_version=None,
        )
    assert exc_info.value.error_code == AMAZON_CONFIG_INVALID


@pytest.mark.parametrize("application_id", ["", "   ", 123, None])
def test_invalid_application_id_inputs_are_rejected(application_id: object) -> None:
    with pytest.raises(AmazonError) as exc_info:
        build_seller_central_authorization_url(
            marketplace_code="US",
            application_id=application_id,  # type: ignore[arg-type]
            state=VALID_STATE,
            consent_version=None,
        )
    assert exc_info.value.error_code == AMAZON_CONFIG_INVALID


def test_invalid_consent_version_is_rejected() -> None:
    with pytest.raises(AmazonError) as exc_info:
        build_seller_central_authorization_url(
            marketplace_code="US",
            application_id=VALID_APPLICATION_ID,
            state=VALID_STATE,
            consent_version="gamma",
        )
    assert exc_info.value.error_code == AMAZON_CONFIG_INVALID


def test_authorization_url_host_always_comes_from_allowlist() -> None:
    for marketplace_code in ALLOWED_OAUTH_MARKETPLACE_CODES:
        target = build_seller_central_authorization_url(
            marketplace_code=marketplace_code,
            application_id=VALID_APPLICATION_ID,
            state=VALID_STATE,
            consent_version=None,
        )
        assert target.authorization_url.startswith(SELLER_CENTRAL_BASE_URLS[marketplace_code])
