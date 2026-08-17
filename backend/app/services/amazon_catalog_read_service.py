"""Tenant-scoped reads for the latest Amazon catalog snapshot."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.integrations.amazon.exceptions import (
    amazon_account_not_found_error,
    amazon_listing_not_found_error,
)
from app.models.amazon_account import AmazonAccount
from app.models.amazon_catalog_snapshot import AmazonCatalogSnapshot
from app.models.amazon_listing import AmazonListing


@dataclass(frozen=True)
class AmazonCatalogSnapshotSummary:
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


class AmazonCatalogReadService:
    def __init__(self, db: Session) -> None:
        self._db = db

    def get_latest_for_user(
        self,
        *,
        user_id: uuid.UUID,
        account_id: uuid.UUID,
        marketplace_id: str,
        listing_id: uuid.UUID,
    ) -> AmazonCatalogSnapshotSummary | None:
        account_exists = (
            self._db.query(AmazonAccount.id)
            .filter(AmazonAccount.id == account_id, AmazonAccount.user_id == user_id)
            .one_or_none()
        )
        if account_exists is None:
            raise amazon_account_not_found_error()
        listing = (
            self._db.query(AmazonListing)
            .filter(
                AmazonListing.id == listing_id,
                AmazonListing.amazon_account_id == account_id,
                AmazonListing.marketplace_id == marketplace_id,
            )
            .one_or_none()
        )
        if listing is None:
            raise amazon_listing_not_found_error()
        snapshot = (
            self._db.query(AmazonCatalogSnapshot)
            .filter(
                AmazonCatalogSnapshot.amazon_listing_id == listing_id,
                AmazonCatalogSnapshot.asin == listing.asin,
                AmazonCatalogSnapshot.marketplace_id == marketplace_id,
            )
            .order_by(
                AmazonCatalogSnapshot.fetched_at.desc(),
                AmazonCatalogSnapshot.id.desc(),
            )
            .first()
        )
        return None if snapshot is None else self._to_summary(snapshot)

    @staticmethod
    def _to_summary(snapshot: AmazonCatalogSnapshot) -> AmazonCatalogSnapshotSummary:
        return AmazonCatalogSnapshotSummary(
            id=snapshot.id,
            listing_id=snapshot.amazon_listing_id,
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
        )
