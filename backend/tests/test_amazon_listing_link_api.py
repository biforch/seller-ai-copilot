"""A5a explicit Amazon listing-to-product link API tests."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from app.integrations.amazon.exceptions import (
    AMAZON_ACCOUNT_NOT_FOUND,
    AMAZON_LISTING_NOT_FOUND,
    AMAZON_PRODUCT_NOT_FOUND,
)
from app.models.amazon_account import AmazonAccount
from app.models.amazon_listing import AmazonListing
from app.models.amazon_marketplace_participation import AmazonMarketplaceParticipation
from app.services.amazon_account_service import AmazonAccountService
from tests.fixtures.amazon_a32 import FAKE_A32_REFRESH_TOKEN, OTHER_FAKE_A32_REFRESH_TOKEN

MARKETPLACE_ID = "ATVPDKIKX0DER"


def _seed_account(db, user, encryption, *, token: str) -> AmazonAccount:
    summary = AmazonAccountService(db, encryption).create_account(
        user_id=user.id,
        region="na",
        endpoint_mode="production",
        plaintext_refresh_token=token,
    )
    account = db.get(AmazonAccount, summary.id)
    assert account is not None
    db.add(
        AmazonMarketplaceParticipation(
            amazon_account_id=account.id,
            marketplace_id=MARKETPLACE_ID,
            marketplace_name="Amazon.com",
            country_code="US",
            participating=True,
            suspended_listings=False,
            is_active=True,
        )
    )
    db.commit()
    return account


def _seed_listing(db, account: AmazonAccount, *, sku: str = "LINK-SKU") -> AmazonListing:
    now = datetime.now(UTC)
    listing = AmazonListing(
        amazon_account_id=account.id,
        marketplace_id=MARKETPLACE_ID,
        seller_sku=sku,
        asin="B012345678",
        status_codes=["BUYABLE"],
        product_type="PRODUCT",
        is_active=True,
        first_seen_at=now,
        last_seen_at=now,
        created_at=now,
        updated_at=now,
    )
    db.add(listing)
    db.commit()
    db.refresh(listing)
    return listing


def _url(account_id: uuid.UUID, listing_id: uuid.UUID, marketplace_id: str = MARKETPLACE_ID) -> str:
    return (
        f"/api/v1/amazon/accounts/{account_id}/marketplaces/{marketplace_id}"
        f"/listings/{listing_id}/product-link"
    )


def test_link_and_unlink_owned_product(
    client, db_session, tenant_bundle, auth_header, token_encryption_service
):
    tenant = tenant_bundle("amazon-link-owned")
    user = tenant["user"]
    product = tenant["product"]
    account = _seed_account(
        db_session, user, token_encryption_service, token=FAKE_A32_REFRESH_TOKEN
    )
    listing = _seed_listing(db_session, account)

    linked = client.patch(
        _url(account.id, listing.id),
        json={"product_id": str(product.id)},
        headers=auth_header(user),
    )
    assert linked.status_code == 200
    assert linked.json()["data"]["product_id"] == str(product.id)
    assert linked.headers["Cache-Control"] == "no-store"
    db_session.refresh(listing)
    assert listing.product_id == product.id

    unlinked = client.patch(
        _url(account.id, listing.id),
        json={"product_id": None},
        headers=auth_header(user),
    )
    assert unlinked.status_code == 200
    assert unlinked.json()["data"]["product_id"] is None
    db_session.refresh(listing)
    assert listing.product_id is None


def test_link_changes_only_product_id(
    client, db_session, tenant_bundle, auth_header, token_encryption_service
):
    tenant = tenant_bundle("amazon-link-snapshot")
    user = tenant["user"]
    product = tenant["product"]
    account = _seed_account(
        db_session, user, token_encryption_service, token=FAKE_A32_REFRESH_TOKEN
    )
    listing = _seed_listing(db_session, account, sku="IMMUTABLE-SNAPSHOT")
    before = (listing.seller_sku, listing.asin, list(listing.status_codes), listing.is_active)

    response = client.patch(
        _url(account.id, listing.id),
        json={"product_id": str(product.id)},
        headers=auth_header(user),
    )
    assert response.status_code == 200
    db_session.refresh(listing)
    assert (listing.seller_sku, listing.asin, listing.status_codes, listing.is_active) == before


def test_cross_tenant_account_is_tenant_safe_not_found(
    client, db_session, tenant_bundle, auth_header, token_encryption_service
):
    owner = tenant_bundle("amazon-link-account-owner")
    other = tenant_bundle("amazon-link-account-other")
    account = _seed_account(
        db_session,
        owner["user"],
        token_encryption_service,
        token=FAKE_A32_REFRESH_TOKEN,
    )
    listing = _seed_listing(db_session, account)
    account_id = account.id
    listing_id = listing.id
    other_product_id = other["product"].id
    response = client.patch(
        _url(account_id, listing_id),
        json={"product_id": str(other_product_id)},
        headers=auth_header(other["user"]),
    )
    assert response.status_code == 404
    assert response.json()["error_code"] == AMAZON_ACCOUNT_NOT_FOUND


@pytest.mark.parametrize("scope", ["account", "marketplace", "listing"])
def test_listing_must_belong_to_scoped_account_and_marketplace(
    scope,
    client, db_session, tenant_bundle, auth_header, token_encryption_service
):
    tenant = tenant_bundle("amazon-link-listing-scope")
    user = tenant["user"]
    first = _seed_account(
        db_session, user, token_encryption_service, token=FAKE_A32_REFRESH_TOKEN
    )
    listing = _seed_listing(db_session, first)
    account_id = first.id
    listing_id = listing.id
    product_id = tenant["product"].id
    marketplace_id = MARKETPLACE_ID
    if scope == "account":
        second = _seed_account(
            db_session,
            user,
            token_encryption_service,
            token=OTHER_FAKE_A32_REFRESH_TOKEN,
        )
        account_id = second.id
    elif scope == "marketplace":
        marketplace_id = "A1F83G8C2ARO7P"
    else:
        listing_id = uuid.uuid4()

    response = client.patch(
        _url(account_id, listing_id, marketplace_id),
        json={"product_id": str(product_id)},
        headers=auth_header(user),
    )
    assert response.status_code == 404
    assert response.json()["error_code"] == AMAZON_LISTING_NOT_FOUND


@pytest.mark.parametrize("product_scope", ["cross_tenant", "unknown"])
def test_cross_tenant_and_unknown_product_share_safe_error(
    product_scope,
    client, db_session, tenant_bundle, auth_header, token_encryption_service
):
    owner = tenant_bundle("amazon-link-product-owner")
    other = tenant_bundle("amazon-link-product-other")
    user = owner["user"]
    account = _seed_account(
        db_session, user, token_encryption_service, token=FAKE_A32_REFRESH_TOKEN
    )
    listing = _seed_listing(db_session, account)
    account_id = account.id
    listing_id = listing.id
    product_id = other["product"].id if product_scope == "cross_tenant" else uuid.uuid4()

    response = client.patch(
        _url(account_id, listing_id),
        json={"product_id": str(product_id)},
        headers=auth_header(user),
    )
    assert response.status_code == 404
    assert response.json()["error_code"] == AMAZON_PRODUCT_NOT_FOUND
    assert response.json()["message"] == "Amazon product operation failed."


def test_link_contract_rejects_extra_or_missing_body_fields(
    client, db_session, tenant_bundle, auth_header, token_encryption_service
):
    tenant = tenant_bundle("amazon-link-contract")
    user = tenant["user"]
    account = _seed_account(
        db_session, user, token_encryption_service, token=FAKE_A32_REFRESH_TOKEN
    )
    listing = _seed_listing(db_session, account)

    for body in ({}, {"product_id": None, "seller_sku": "override"}):
        response = client.patch(
            _url(account.id, listing.id), json=body, headers=auth_header(user)
        )
        assert response.status_code == 422
    db_session.refresh(listing)
    assert listing.product_id is None


def test_link_requires_authentication(client):
    response = client.patch(
        _url(uuid.uuid4(), uuid.uuid4()), json={"product_id": None}
    )
    assert response.status_code in {401, 403}
