"""Database-backed tenant boundary tests for catalog snapshot reads."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from app.integrations.amazon.exceptions import (
    AMAZON_ACCOUNT_NOT_FOUND,
    AMAZON_LISTING_NOT_FOUND,
    AmazonError,
)
from app.models.amazon_catalog_snapshot import AmazonCatalogSnapshot
from app.models.amazon_listing import AmazonListing
from app.models.amazon_marketplace_participation import AmazonMarketplaceParticipation
from app.models.user import User
from app.services.amazon_catalog_read_service import AmazonCatalogReadService
from tests.fixtures.amazon_a32 import FAKE_A32_REFRESH_TOKEN, create_committed_account
from tests.test_amazon_catalog_enrichment_service import MARKETPLACE_ID


@dataclass(frozen=True)
class _Bundle:
    user_id: uuid.UUID
    account_id: uuid.UUID
    listing_id: uuid.UUID


@pytest.fixture
def catalog_read_bundle_factory(a32_session_factory, token_encryption_service):
    user_ids: list[uuid.UUID] = []

    def create() -> _Bundle:
        user, account = create_committed_account(
            a32_session_factory,
            token_encryption_service,
            token=FAKE_A32_REFRESH_TOKEN,
        )
        user_ids.append(user.id)
        db = a32_session_factory()
        try:
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
            now = datetime.now(UTC)
            listing = AmazonListing(
                amazon_account_id=account.id,
                marketplace_id=MARKETPLACE_ID,
                seller_sku=f"CATALOG-READ-{uuid.uuid4()}",
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
            return _Bundle(user.id, account.id, listing.id)
        finally:
            db.close()

    yield create
    db = a32_session_factory()
    try:
        db.query(User).filter(User.id.in_(user_ids)).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


def _seed_snapshot(session_factory, bundle, *, item_name: str, offset: int):
    db = session_factory()
    try:
        now = datetime(2026, 8, 17, 12, tzinfo=UTC) + timedelta(minutes=offset)
        row = AmazonCatalogSnapshot(
            amazon_listing_id=bundle.listing_id,
            content_hash=(f"{offset + 1:064x}")[-64:],
            asin="B012345678",
            marketplace_id=MARKETPLACE_ID,
            item_name=item_name,
            fetched_at=now,
            expires_at=now + timedelta(hours=24),
        )
        db.add(row)
        db.commit()
        return row.id
    finally:
        db.close()


def test_read_returns_latest_bounded_snapshot(
    a32_session_factory, catalog_read_bundle_factory
) -> None:
    bundle = catalog_read_bundle_factory()
    _seed_snapshot(a32_session_factory, bundle, item_name="Old", offset=0)
    latest_id = _seed_snapshot(a32_session_factory, bundle, item_name="Latest", offset=1)
    db = a32_session_factory()
    try:
        result = AmazonCatalogReadService(db).get_latest_for_user(
            user_id=bundle.user_id,
            account_id=bundle.account_id,
            marketplace_id=MARKETPLACE_ID,
            listing_id=bundle.listing_id,
        )
        assert result is not None
        assert result.id == latest_id
        assert result.item_name == "Latest"
        assert not hasattr(result, "content_hash")
        assert not hasattr(result, "source_request_id")
    finally:
        db.rollback()
        db.close()


def test_read_cross_tenant_is_account_not_found(
    a32_session_factory, catalog_read_bundle_factory
) -> None:
    bundle = catalog_read_bundle_factory()
    db = a32_session_factory()
    try:
        with pytest.raises(AmazonError) as exc_info:
            AmazonCatalogReadService(db).get_latest_for_user(
                user_id=uuid.uuid4(),
                account_id=bundle.account_id,
                marketplace_id=MARKETPLACE_ID,
                listing_id=bundle.listing_id,
            )
        assert exc_info.value.error_code == AMAZON_ACCOUNT_NOT_FOUND
    finally:
        db.rollback()
        db.close()


def test_read_marketplace_path_is_identity_bound(
    a32_session_factory, catalog_read_bundle_factory
) -> None:
    bundle = catalog_read_bundle_factory()
    db = a32_session_factory()
    try:
        with pytest.raises(AmazonError) as exc_info:
            AmazonCatalogReadService(db).get_latest_for_user(
                user_id=bundle.user_id,
                account_id=bundle.account_id,
                marketplace_id="A-DIFFERENT-MARKETPLACE",
                listing_id=bundle.listing_id,
            )
        assert exc_info.value.error_code == AMAZON_LISTING_NOT_FOUND
    finally:
        db.rollback()
        db.close()
