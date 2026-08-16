"""Tenant-scoped read-only Amazon listing access."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.integrations.amazon.exceptions import amazon_marketplace_not_found_error
from app.integrations.amazon.listings_items import _validate_marketplace_id_for_client
from app.models.amazon_listing import AmazonListing
from app.models.amazon_marketplace_participation import AmazonMarketplaceParticipation
from app.services.amazon_account_read_service import AmazonAccountReadService


@dataclass(frozen=True)
class AmazonListingSummary:
    id: uuid.UUID
    marketplace_id: str
    seller_sku: str
    asin: str | None
    product_id: uuid.UUID | None
    status_codes: tuple[str, ...]
    product_type: str | None
    upstream_created_at: datetime | None
    upstream_last_updated_at: datetime | None
    is_active: bool
    first_seen_at: datetime
    last_seen_at: datetime
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, row: AmazonListing) -> AmazonListingSummary:
        return cls(
            id=row.id,
            marketplace_id=row.marketplace_id,
            seller_sku=row.seller_sku,
            asin=row.asin,
            product_id=row.product_id,
            status_codes=tuple(row.status_codes),
            product_type=row.product_type,
            upstream_created_at=row.upstream_created_at,
            upstream_last_updated_at=row.upstream_last_updated_at,
            is_active=row.is_active,
            first_seen_at=row.first_seen_at,
            last_seen_at=row.last_seen_at,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )


@dataclass(frozen=True)
class AmazonListingPage:
    items: tuple[AmazonListingSummary, ...]
    page: int
    page_size: int
    total: int


class AmazonListingReadService(AmazonAccountReadService):
    def __init__(self, db: Session) -> None:
        super().__init__(db)

    def list_listings_for_user(
        self,
        *,
        user_id: uuid.UUID,
        account_id: uuid.UUID,
        marketplace_id: str,
        page: int,
        page_size: int,
        include_inactive: bool,
    ) -> AmazonListingPage:
        normalized_marketplace_id = _validate_marketplace_id_for_client(marketplace_id)
        self.get_account_for_user(user_id=user_id, account_id=account_id)
        participation = (
            self._db.query(AmazonMarketplaceParticipation.id)
            .filter(
                AmazonMarketplaceParticipation.amazon_account_id == account_id,
                AmazonMarketplaceParticipation.marketplace_id == normalized_marketplace_id,
            )
            .one_or_none()
        )
        if participation is None:
            raise amazon_marketplace_not_found_error()

        query = self._db.query(AmazonListing).filter(
            AmazonListing.amazon_account_id == account_id,
            AmazonListing.marketplace_id == normalized_marketplace_id,
        )
        if not include_inactive:
            query = query.filter(AmazonListing.is_active.is_(True))
        total = query.count()
        rows = (
            query.order_by(AmazonListing.updated_at.desc(), AmazonListing.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return AmazonListingPage(
            items=tuple(
                AmazonListingSummary.from_model(row)
                for row in rows
            ),
            page=page,
            page_size=page_size,
            total=total,
        )
