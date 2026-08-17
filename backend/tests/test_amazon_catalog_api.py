"""HTTP contracts for tenant-safe Amazon catalog snapshot access."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from app.api.amazon_catalog_deps import (
    get_amazon_catalog_enrichment_service_factory,
    get_amazon_catalog_read_service,
)
from app.api.amazon_marketplaces_deps import get_amazon_account_runtime_resolver
from app.integrations.amazon.exceptions import amazon_listing_not_found_error
from app.main import app
from app.services.amazon_catalog_enrichment_service import CatalogEnrichmentResult

MARKETPLACE_ID = "ATVPDKIKX0DER"


def _url(account_id: uuid.UUID, listing_id: uuid.UUID, *, refresh: bool = False) -> str:
    suffix = "/refresh" if refresh else ""
    return (
        f"/api/v1/amazon/accounts/{account_id}/marketplaces/{MARKETPLACE_ID}"
        f"/listings/{listing_id}/catalog{suffix}"
    )


@dataclass(frozen=True)
class _Snapshot:
    id: uuid.UUID
    listing_id: uuid.UUID
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
    fetched_at: datetime
    expires_at: datetime


def _snapshot(listing_id: uuid.UUID) -> _Snapshot:
    now = datetime.now(UTC)
    return _Snapshot(
        id=uuid.uuid4(),
        listing_id=listing_id,
        asin="B012345678",
        marketplace_id=MARKETPLACE_ID,
        item_name="Bounded title",
        brand="Brand",
        manufacturer=None,
        color="Blue",
        size=None,
        style=None,
        model_number=None,
        part_number=None,
        product_type="PRODUCT",
        fetched_at=now,
        expires_at=now + timedelta(hours=24),
    )


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


def test_catalog_read_is_bounded_and_does_not_build_network_stack(
    client, user_factory, auth_header
):
    user = user_factory("catalog-read-api@example.com")
    account_id = uuid.uuid4()
    listing_id = uuid.uuid4()
    calls: list[tuple] = []

    class ReadService:
        def get_latest_for_user(self, **kwargs):
            calls.append(tuple(kwargs.values()))
            return _snapshot(listing_id)

    def forbidden_factory():
        raise AssertionError("encryption/network factory must not be resolved for GET")

    app.dependency_overrides[get_amazon_catalog_read_service] = lambda: ReadService()
    app.dependency_overrides[get_amazon_catalog_enrichment_service_factory] = (
        forbidden_factory
    )
    response = client.get(_url(account_id, listing_id), headers=auth_header(user))
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    data = response.json()["data"]
    assert set(data) == {
        "id",
        "listing_id",
        "asin",
        "marketplace_id",
        "item_name",
        "brand",
        "manufacturer",
        "color",
        "size",
        "style",
        "model_number",
        "part_number",
        "product_type",
        "fetched_at",
        "expires_at",
        "cache_hit",
    }
    assert data["cache_hit"] is None
    assert "content_hash" not in response.text
    assert "source_request_id" not in response.text
    assert calls == [(user.id, account_id, MARKETPLACE_ID, listing_id)]


def test_catalog_read_without_snapshot_returns_null(client, user_factory, auth_header):
    user = user_factory("catalog-read-empty@example.com")

    class ReadService:
        def get_latest_for_user(self, **_kwargs):
            return None

    app.dependency_overrides[get_amazon_catalog_read_service] = lambda: ReadService()
    response = client.get(
        _url(uuid.uuid4(), uuid.uuid4()), headers=auth_header(user)
    )
    assert response.status_code == 200
    assert response.json()["data"] is None


def test_catalog_read_preserves_tenant_safe_error(client, user_factory, auth_header):
    user = user_factory("catalog-read-missing@example.com")

    class ReadService:
        def get_latest_for_user(self, **_kwargs):
            raise amazon_listing_not_found_error()

    app.dependency_overrides[get_amazon_catalog_read_service] = lambda: ReadService()
    response = client.get(
        _url(uuid.uuid4(), uuid.uuid4()), headers=auth_header(user)
    )
    assert response.status_code == 404
    assert response.json()["error_code"] == "AMAZON_LISTING_NOT_FOUND"
    assert response.headers["Cache-Control"] == "no-store"


def test_catalog_refresh_passes_server_runtime_and_bound_path(
    client, user_factory, auth_header
):
    user = user_factory("catalog-refresh-api@example.com")
    account_id = uuid.uuid4()
    listing_id = uuid.uuid4()
    calls: list[tuple] = []
    snapshot = _snapshot(listing_id)

    class Account:
        region = "eu"
        endpoint_mode = "production"

    class Service:
        async def enrich_listing(self, **kwargs):
            calls.append(("enrich", kwargs))
            return CatalogEnrichmentResult(
                snapshot_id=snapshot.id,
                listing_id=snapshot.listing_id,
                asin=snapshot.asin,
                marketplace_id=snapshot.marketplace_id,
                item_name=snapshot.item_name,
                brand=snapshot.brand,
                manufacturer=snapshot.manufacturer,
                color=snapshot.color,
                size=snapshot.size,
                style=snapshot.style,
                model_number=snapshot.model_number,
                part_number=snapshot.part_number,
                product_type=snapshot.product_type,
                fetched_at=snapshot.fetched_at,
                expires_at=snapshot.expires_at,
                cache_hit=False,
            )

    def resolve(user_id, resolved_account_id):
        calls.append(("resolve", user_id, resolved_account_id))
        return Account()

    def factory(region, endpoint_mode):
        calls.append(("factory", region, endpoint_mode))
        return Service()

    app.dependency_overrides[get_amazon_account_runtime_resolver] = lambda: resolve
    app.dependency_overrides[get_amazon_catalog_enrichment_service_factory] = (
        lambda: factory
    )
    response = client.post(
        _url(account_id, listing_id, refresh=True),
        params={"force_refresh": "true"},
        headers=auth_header(user),
    )
    assert response.status_code == 200
    assert response.json()["data"]["cache_hit"] is False
    assert calls == [
        ("resolve", user.id, account_id),
        ("factory", "eu", "production"),
        (
            "enrich",
            {
                "user_id": user.id,
                "account_id": account_id,
                "listing_id": listing_id,
                "marketplace_id": MARKETPLACE_ID,
                "force_refresh": True,
            },
        ),
    ]


@pytest.mark.parametrize("method", ["get", "post"])
def test_catalog_endpoints_require_auth(client, method):
    response = getattr(client, method)(
        _url(uuid.uuid4(), uuid.uuid4(), refresh=method == "post")
    )
    assert response.status_code in {401, 403}
