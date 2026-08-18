"""Resolve server-owned Amazon catalog context for AI listing generation."""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.integrations.amazon.exceptions import (
    amazon_catalog_snapshot_not_found_error,
    amazon_listing_not_found_error,
)
from app.models.amazon_account import AmazonAccount
from app.models.amazon_catalog_snapshot import AmazonCatalogSnapshot
from app.models.amazon_listing import AmazonListing
from app.models.product import Product


@dataclass(frozen=True)
class AmazonCatalogAIContext:
    snapshot_id: uuid.UUID
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

    def to_audit_dict(self) -> dict[str, str | None]:
        values = asdict(self)
        values["snapshot_id"] = str(self.snapshot_id)
        values["listing_id"] = str(self.listing_id)
        return values

    def to_prompt_dict(self) -> dict[str, str | None]:
        values = self.to_audit_dict()
        values.pop("snapshot_id")
        values.pop("listing_id")
        return values


class AmazonCatalogAIContextService:
    def __init__(self, db: Session) -> None:
        self._db = db

    def resolve_for_generation(
        self,
        *,
        user_id: uuid.UUID,
        product_id: uuid.UUID,
        listing_id: uuid.UUID,
    ) -> AmazonCatalogAIContext:
        listing = (
            self._db.query(AmazonListing)
            .join(AmazonAccount, AmazonAccount.id == AmazonListing.amazon_account_id)
            .join(Product, Product.id == AmazonListing.product_id)
            .filter(
                AmazonListing.id == listing_id,
                AmazonListing.product_id == product_id,
                AmazonAccount.user_id == user_id,
                Product.user_id == user_id,
            )
            .one_or_none()
        )
        if listing is None:
            raise amazon_listing_not_found_error()
        snapshot = (
            self._db.query(AmazonCatalogSnapshot)
            .filter(
                AmazonCatalogSnapshot.amazon_listing_id == listing.id,
                AmazonCatalogSnapshot.asin == listing.asin,
                AmazonCatalogSnapshot.marketplace_id == listing.marketplace_id,
                AmazonCatalogSnapshot.expires_at > func.now(),
            )
            .order_by(
                AmazonCatalogSnapshot.fetched_at.desc(),
                AmazonCatalogSnapshot.id.desc(),
            )
            .first()
        )
        if snapshot is None:
            raise amazon_catalog_snapshot_not_found_error()
        return AmazonCatalogAIContext(
            snapshot_id=snapshot.id,
            listing_id=listing.id,
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
        )
