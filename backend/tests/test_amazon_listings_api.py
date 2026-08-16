"""HTTP API tests for tenant-scoped Amazon listing reads and sync triggers."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from fastapi import status

from app.api.amazon_listings_deps import get_amazon_product_sync_service_factory
from app.api.amazon_marketplaces_deps import get_amazon_account_runtime_resolver
from app.integrations.amazon.exceptions import (
    AMAZON_ACCOUNT_NOT_FOUND,
    AMAZON_MARKETPLACE_NOT_FOUND,
    AMAZON_SYNC_IN_PROGRESS,
    amazon_sync_in_progress_error,
)
from app.main import app
from app.models.amazon_account import AmazonAccount
from app.models.amazon_listing import AmazonListing
from app.models.amazon_marketplace_participation import AmazonMarketplaceParticipation
from app.services.amazon_account_service import AmazonAccountService
from app.services.amazon_product_sync_service import ProductSyncResult
from tests.fixtures.amazon_a32 import FAKE_A32_REFRESH_TOKEN, OTHER_FAKE_A32_REFRESH_TOKEN

BASE_URL = "/api/v1/amazon/accounts"
MARKETPLACE_ID = "ATVPDKIKX0DER"


def _list_url(account_id: uuid.UUID, marketplace_id: str = MARKETPLACE_ID) -> str:
    return f"{BASE_URL}/{account_id}/marketplaces/{marketplace_id}/listings"


def _sync_url(account_id: uuid.UUID, marketplace_id: str = MARKETPLACE_ID) -> str:
    return f"{_list_url(account_id, marketplace_id)}/sync"


def _seed_bundle(db, user, encryption, *, token: str, region: str = "na"):
    account_service = AmazonAccountService(db, encryption)
    summary = account_service.create_account(
        user_id=user.id,
        region=region,
        endpoint_mode="production",
        plaintext_refresh_token=token,
    )
    account = db.get(AmazonAccount, summary.id)
    assert account is not None
    account.selling_partner_id = uuid.uuid4().hex
    db.add(account)
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
    db.refresh(account)
    return account


def _seed_listing(
    db,
    account: AmazonAccount,
    *,
    sku: str,
    active: bool = True,
    updated_at: datetime | None = None,
) -> AmazonListing:
    now = updated_at or datetime.now(UTC)
    row = AmazonListing(
        amazon_account_id=account.id,
        marketplace_id=MARKETPLACE_ID,
        seller_sku=sku,
        asin="B012345678",
        status_codes=["BUYABLE"],
        product_type="PRODUCT",
        is_active=active,
        first_seen_at=now,
        last_seen_at=now,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def test_listings_empty_for_known_marketplace(
    client, user_factory, auth_header, db_session, token_encryption_service
):
    user = user_factory("amazon-listings-empty@example.com")
    account = _seed_bundle(
        db_session,
        user,
        token_encryption_service,
        token=FAKE_A32_REFRESH_TOKEN,
    )
    response = client.get(_list_url(account.id), headers=auth_header(user))
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["items"] == []
    assert data["pagination"]["total"] == 0
    assert response.headers["Cache-Control"] == "no-store"


def test_listings_public_shape_and_default_active_filter(
    client, user_factory, auth_header, db_session, token_encryption_service
):
    user = user_factory("amazon-listings-shape@example.com")
    account = _seed_bundle(
        db_session, user, token_encryption_service, token=FAKE_A32_REFRESH_TOKEN
    )
    active = _seed_listing(db_session, account, sku="SKU-A", active=True)
    _seed_listing(db_session, account, sku="SKU-INACTIVE", active=False)
    response = client.get(_list_url(account.id), headers=auth_header(user))
    items = response.json()["data"]["items"]
    assert len(items) == 1
    assert items[0]["id"] == str(active.id)
    assert items[0]["seller_sku"] == "SKU-A"
    assert set(items[0]) == {
        "id",
        "marketplace_id",
        "seller_sku",
        "asin",
        "product_id",
        "status_codes",
        "product_type",
        "upstream_created_at",
        "upstream_last_updated_at",
        "is_active",
        "first_seen_at",
        "last_seen_at",
        "created_at",
        "updated_at",
    }
    for forbidden in ("account_key", "refresh_token", "selling_partner_id", "sync_lease_id"):
        assert forbidden not in response.text


def test_listings_include_inactive_and_paginate(
    client, user_factory, auth_header, db_session, token_encryption_service
):
    user = user_factory("amazon-listings-page@example.com")
    account = _seed_bundle(
        db_session, user, token_encryption_service, token=FAKE_A32_REFRESH_TOKEN
    )
    for index in range(3):
        _seed_listing(
            db_session,
            account,
            sku=f"SKU-{index}",
            active=index != 2,
            updated_at=datetime(2026, 1, index + 1, tzinfo=UTC),
        )
    response = client.get(
        _list_url(account.id),
        params={"include_inactive": "true", "page": 2, "page_size": 2},
        headers=auth_header(user),
    )
    data = response.json()["data"]
    assert len(data["items"]) == 1
    assert data["pagination"] == {
        "page": 2,
        "page_size": 2,
        "total": 3,
        "total_pages": 2,
        "has_next": False,
        "has_previous": True,
    }


def test_listings_unknown_marketplace_is_stable_404(
    client, user_factory, auth_header, db_session, token_encryption_service
):
    user = user_factory("amazon-listings-market-missing@example.com")
    account = _seed_bundle(
        db_session, user, token_encryption_service, token=FAKE_A32_REFRESH_TOKEN
    )
    response = client.get(_list_url(account.id, "UNKNOWN"), headers=auth_header(user))
    assert response.status_code == 404
    assert response.json()["error_code"] == AMAZON_MARKETPLACE_NOT_FOUND


def test_listings_cross_tenant_is_account_not_found(
    client, user_factory, auth_header, db_session, token_encryption_service
):
    owner = user_factory("amazon-listings-owner@example.com")
    other = user_factory("amazon-listings-other@example.com")
    account = _seed_bundle(
        db_session, owner, token_encryption_service, token=FAKE_A32_REFRESH_TOKEN
    )
    response = client.get(_list_url(account.id), headers=auth_header(other))
    assert response.status_code == 404
    assert response.json()["error_code"] == AMAZON_ACCOUNT_NOT_FOUND


@pytest.mark.parametrize("method", ["get", "post"])
def test_listing_endpoints_require_auth(client, method: str):
    response = getattr(client, method)(
        _list_url(uuid.uuid4()) if method == "get" else _sync_url(uuid.uuid4())
    )
    assert response.status_code in {401, 403}


def test_sync_passes_server_owned_runtime_and_identifiers(
    client, user_factory, auth_header, db_session, token_encryption_service
):
    user = user_factory("amazon-listings-sync@example.com")
    account = _seed_bundle(
        db_session,
        user,
        token_encryption_service,
        token=FAKE_A32_REFRESH_TOKEN,
        region="eu",
    )
    user_id = user.id
    account_id = account.id
    calls = []

    class FakeSyncService:
        async def sync_product_listings(self, *, user_id, account_id, marketplace_id):
            calls.append(("sync", user_id, account_id, marketplace_id))
            return ProductSyncResult(
                account_id=account_id,
                marketplace_id=marketplace_id,
                sync_log_id=uuid.uuid4(),
                items_seen=4,
                items_written=4,
                items_deactivated=1,
                pages_seen=2,
                request_id="not-public",
            )

    def factory(region, endpoint_mode):
        calls.append(("factory", region, endpoint_mode))
        return FakeSyncService()

    app.dependency_overrides[get_amazon_product_sync_service_factory] = lambda: factory
    try:
        response = client.post(_sync_url(account_id), headers=auth_header(user))
    finally:
        app.dependency_overrides.pop(get_amazon_product_sync_service_factory, None)
    assert response.status_code == 200
    assert calls == [
        ("factory", "eu", "production"),
        ("sync", user_id, account_id, MARKETPLACE_ID),
    ]
    data = response.json()["data"]
    assert data["pages_seen"] == 2
    assert "request_id" not in data


def test_sync_cross_tenant_does_not_build_service(
    client, user_factory, auth_header, db_session, token_encryption_service
):
    owner = user_factory("amazon-listings-sync-owner@example.com")
    other = user_factory("amazon-listings-sync-other@example.com")
    account = _seed_bundle(
        db_session, owner, token_encryption_service, token=FAKE_A32_REFRESH_TOKEN
    )
    calls = 0

    def factory(_region, _mode):
        nonlocal calls
        calls += 1
        raise AssertionError

    app.dependency_overrides[get_amazon_product_sync_service_factory] = lambda: factory
    try:
        response = client.post(_sync_url(account.id), headers=auth_header(other))
    finally:
        app.dependency_overrides.pop(get_amazon_product_sync_service_factory, None)
    assert response.status_code == 404
    assert calls == 0


def test_sync_error_is_stable_and_private(
    client, user_factory, auth_header, db_session, token_encryption_service
):
    user = user_factory("amazon-listings-sync-error@example.com")
    account = _seed_bundle(
        db_session,
        user,
        token_encryption_service,
        token=OTHER_FAKE_A32_REFRESH_TOKEN,
    )

    class FailingSyncService:
        async def sync_product_listings(self, **kwargs):
            raise amazon_sync_in_progress_error()

    app.dependency_overrides[get_amazon_product_sync_service_factory] = (
        lambda: lambda _region, _mode: FailingSyncService()
    )
    try:
        response = client.post(_sync_url(account.id), headers=auth_header(user))
    finally:
        app.dependency_overrides.pop(get_amazon_product_sync_service_factory, None)
    assert response.status_code == 409
    assert response.json()["error_code"] == AMAZON_SYNC_IN_PROGRESS
    assert response.headers["Cache-Control"] == "no-store"


def test_sync_rate_limit_stops_before_fourth_factory_build(
    client, user_factory, auth_header, db_session, token_encryption_service
):
    user = user_factory(f"amazon-listings-rate-{uuid.uuid4()}@example.com")
    account = _seed_bundle(
        db_session,
        user,
        token_encryption_service,
        token=f"{FAKE_A32_REFRESH_TOKEN}-{uuid.uuid4()}",
    )
    summary = AmazonAccountService(db_session, token_encryption_service).get_account_for_user(
        user_id=user.id,
        account_id=account.id,
    )
    calls = 0

    class FakeSyncService:
        async def sync_product_listings(self, *, user_id, account_id, marketplace_id):
            return ProductSyncResult(
                account_id=account_id,
                marketplace_id=marketplace_id,
                sync_log_id=uuid.uuid4(),
                items_seen=0,
                items_written=0,
                items_deactivated=0,
                pages_seen=1,
                request_id=None,
            )

    def factory(_region, _mode):
        nonlocal calls
        calls += 1
        return FakeSyncService()

    app.dependency_overrides[get_amazon_account_runtime_resolver] = (
        lambda: lambda _user_id, _account_id: summary
    )
    app.dependency_overrides[get_amazon_product_sync_service_factory] = lambda: factory
    headers = auth_header(user)
    account_id = account.id
    try:
        responses = [client.post(_sync_url(account_id), headers=headers) for _ in range(4)]
    finally:
        app.dependency_overrides.pop(get_amazon_account_runtime_resolver, None)
        app.dependency_overrides.pop(get_amazon_product_sync_service_factory, None)
    assert [response.status_code for response in responses] == [200, 200, 200, 429]
    assert calls == 3


def test_listing_openapi_contract_is_authenticated_and_sensitive_free():
    schema = app.openapi()
    list_operation = schema["paths"][
        "/api/v1/amazon/accounts/{account_id}/marketplaces/{marketplace_id}/listings"
    ]["get"]
    sync_operation = schema["paths"][
        "/api/v1/amazon/accounts/{account_id}/marketplaces/{marketplace_id}/listings/sync"
    ]["post"]
    assert list_operation["security"] == [{"HTTPBearer": []}]
    assert sync_operation["security"] == [{"HTTPBearer": []}]
    schemas = str(schema["components"]["schemas"])
    for forbidden in ("refresh_token", "account_key", "selling_partner_id", "sync_lease_id"):
        assert forbidden not in schemas


def test_listing_pagination_validation(
    client, user_factory, auth_header, db_session, token_encryption_service
):
    user = user_factory("amazon-listings-pagination-invalid@example.com")
    account = _seed_bundle(
        db_session, user, token_encryption_service, token=FAKE_A32_REFRESH_TOKEN
    )
    response = client.get(
        _list_url(account.id),
        params={"page": 0, "page_size": 101},
        headers=auth_header(user),
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
