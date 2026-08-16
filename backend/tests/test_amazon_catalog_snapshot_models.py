from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.amazon_account import AmazonAccount
from app.models.amazon_catalog_snapshot import AmazonCatalogSnapshot
from app.models.amazon_listing import AmazonListing
from app.services.amazon_account_service import AmazonAccountService
from tests.fixtures.amazon_a32 import FAKE_A32_REFRESH_TOKEN

MARKETPLACE_ID = "ATVPDKIKX0DER"


def _listing(db, user, encryption, *, sku: str = "CATALOG-SKU") -> AmazonListing:
    account_id = AmazonAccountService(db, encryption).create_account(
        user_id=user.id,
        region="na",
        endpoint_mode="production",
        plaintext_refresh_token=FAKE_A32_REFRESH_TOKEN,
    ).id
    account = db.get(AmazonAccount, account_id)
    assert account is not None
    now = datetime.now(UTC)
    listing = AmazonListing(
        amazon_account_id=account.id,
        marketplace_id=MARKETPLACE_ID,
        seller_sku=sku,
        asin="B012345678",
        status_codes=["BUYABLE"],
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


def _snapshot(
    listing: AmazonListing,
    *,
    content_hash: str = "a" * 64,
    asin: str = "B012345678",
    marketplace_id: str = MARKETPLACE_ID,
    fetched_at: datetime | None = None,
    expires_at: datetime | None = None,
) -> AmazonCatalogSnapshot:
    fetched = fetched_at or datetime.now(UTC)
    return AmazonCatalogSnapshot(
        amazon_listing_id=listing.id,
        content_hash=content_hash,
        asin=asin,
        marketplace_id=marketplace_id,
        item_name="Safe catalog title",
        brand="Safe brand",
        manufacturer="Safe manufacturer",
        product_type="PRODUCT",
        source_request_id="safe-request-id",
        fetched_at=fetched,
        expires_at=expires_at or fetched + timedelta(hours=24),
    )


def test_snapshot_round_trip_relationship_and_safe_repr(
    db_session, user_factory, token_encryption_service
) -> None:
    user = user_factory("catalog-snapshot-roundtrip@example.com")
    listing = _listing(db_session, user, token_encryption_service)
    snapshot = _snapshot(listing)
    db_session.add(snapshot)
    db_session.commit()
    db_session.refresh(snapshot)

    assert snapshot.amazon_listing_id == listing.id
    assert snapshot.amazon_listing.id == listing.id
    assert listing.catalog_snapshots == [snapshot]
    rendered = repr(snapshot)
    assert "Safe catalog title" not in rendered
    assert "safe-request-id" not in rendered
    assert "a" * 64 not in rendered


def test_same_content_is_unique_per_listing(
    db_session, user_factory, token_encryption_service
) -> None:
    user = user_factory("catalog-snapshot-unique@example.com")
    listing = _listing(db_session, user, token_encryption_service)
    db_session.add_all([_snapshot(listing), _snapshot(listing)])
    with pytest.raises(IntegrityError):
        db_session.commit()


@pytest.mark.parametrize(
    ("overrides"),
    [
        {"content_hash": "A" * 64},
        {"content_hash": "a" * 63},
        {"asin": "bad-asin"},
        {"marketplace_id": "   "},
    ],
)
def test_snapshot_identity_checks_enforced(
    overrides, db_session, user_factory, token_encryption_service
) -> None:
    user = user_factory(f"catalog-snapshot-check-{uuid.uuid4()}@example.com")
    listing = _listing(db_session, user, token_encryption_service)
    db_session.add(_snapshot(listing, **overrides))
    with pytest.raises(IntegrityError):
        db_session.commit()


@pytest.mark.parametrize("delta", [timedelta(0), timedelta(seconds=-1)])
def test_expiry_must_follow_fetch(
    delta, db_session, user_factory, token_encryption_service
) -> None:
    user = user_factory(f"catalog-snapshot-expiry-{uuid.uuid4()}@example.com")
    listing = _listing(db_session, user, token_encryption_service)
    fetched = datetime.now(UTC)
    db_session.add(
        _snapshot(listing, fetched_at=fetched, expires_at=fetched + delta)
    )
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_listing_delete_cascades_snapshots(
    db_session, user_factory, token_encryption_service
) -> None:
    user = user_factory("catalog-snapshot-cascade@example.com")
    listing = _listing(db_session, user, token_encryption_service)
    snapshot = _snapshot(listing)
    db_session.add(snapshot)
    db_session.commit()
    snapshot_id = snapshot.id
    db_session.delete(listing)
    db_session.commit()
    assert db_session.get(AmazonCatalogSnapshot, snapshot_id) is None
