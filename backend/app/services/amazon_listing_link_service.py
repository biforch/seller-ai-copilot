"""Explicit tenant-safe links between Amazon listings and SellerAI products."""

from __future__ import annotations

import uuid

from app.integrations.amazon.exceptions import (
    AmazonError,
    amazon_listing_not_found_error,
    amazon_product_not_found_error,
)
from app.integrations.amazon.listings_items import _validate_marketplace_id_for_client
from app.models.amazon_listing import AmazonListing
from app.models.product import Product
from app.services.amazon_account_read_service import AmazonAccountReadService
from app.services.amazon_listing_read_service import AmazonListingSummary


class AmazonListingLinkService(AmazonAccountReadService):
    """Mutate only the optional product link; Amazon snapshot fields stay untouched."""

    def link_product_for_user(
        self,
        *,
        user_id: uuid.UUID,
        account_id: uuid.UUID,
        marketplace_id: str,
        listing_id: uuid.UUID,
        product_id: uuid.UUID | None,
    ) -> AmazonListingSummary:
        normalized_marketplace_id = _validate_marketplace_id_for_client(marketplace_id)
        try:
            self.get_account_for_user(user_id=user_id, account_id=account_id)
            listing = (
                self._db.query(AmazonListing)
                .filter(
                    AmazonListing.id == listing_id,
                    AmazonListing.amazon_account_id == account_id,
                    AmazonListing.marketplace_id == normalized_marketplace_id,
                )
                .with_for_update()
                .one_or_none()
            )
            if listing is None:
                raise amazon_listing_not_found_error()

            if product_id is not None:
                product_exists = (
                    self._db.query(Product.id)
                    .filter(Product.id == product_id, Product.user_id == user_id)
                    .one_or_none()
                )
                if product_exists is None:
                    raise amazon_product_not_found_error()

            listing.product_id = product_id
            self._db.commit()
            self._db.refresh(listing)
            return AmazonListingSummary.from_model(listing)
        except AmazonError:
            self._db.rollback()
            raise
        except Exception:
            self._db.rollback()
            raise
