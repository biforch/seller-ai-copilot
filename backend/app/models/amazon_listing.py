import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base

# Keep in sync with listings_items.SELLER_SKU_MAX_LENGTH (integration contract).
SELLER_SKU_MAX_LENGTH = 128
ASIN_MAX_LENGTH = 16


def _empty_status_codes() -> list[str]:
    return []


class AmazonListing(Base):
    __tablename__ = "amazon_listings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    amazon_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("amazon_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    marketplace_id: Mapped[str] = mapped_column(String(32), nullable=False)
    seller_sku: Mapped[str] = mapped_column(String(SELLER_SKU_MAX_LENGTH), nullable=False)
    asin: Mapped[str | None] = mapped_column(String(ASIN_MAX_LENGTH), nullable=True)
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("products.id", ondelete="SET NULL"),
        nullable=True,
    )
    status_codes: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=_empty_status_codes,
    )
    product_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    upstream_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    upstream_last_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    is_active: Mapped[bool] = mapped_column(Boolean(), nullable=False, default=True)
    last_seen_sync_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    amazon_account = relationship("AmazonAccount", back_populates="amazon_listings")
    product = relationship("Product", back_populates="amazon_listings")

    __table_args__ = (
        UniqueConstraint(
            "amazon_account_id",
            "marketplace_id",
            "seller_sku",
            name="uq_amazon_listings_account_marketplace_sku",
        ),
        CheckConstraint(
            "jsonb_typeof(status_codes) = 'array'",
            name="ck_amazon_listings_status_codes_array",
        ),
        CheckConstraint(
            "length(trim(marketplace_id)) > 0",
            name="ck_amazon_listings_marketplace_id_not_blank",
        ),
        CheckConstraint(
            "length(trim(seller_sku)) > 0",
            name="ck_amazon_listings_seller_sku_not_blank",
        ),
        Index(
            "ix_amazon_listings_account_marketplace_updated",
            "amazon_account_id",
            "marketplace_id",
            "updated_at",
            "id",
        ),
        Index("ix_amazon_listings_product_id", "product_id"),
        Index(
            "ix_amazon_listings_account_marketplace_last_seen_sync",
            "amazon_account_id",
            "marketplace_id",
            "last_seen_sync_id",
        ),
        Index("ix_amazon_listings_asin", "asin"),
    )

    def __repr__(self) -> str:
        return (
            f"AmazonListing(id={self.id!s}, amazon_account_id={self.amazon_account_id!s}, "
            f"marketplace_id={self.marketplace_id!r}, seller_sku={self.seller_sku!r}, "
            f"is_active={self.is_active})"
        )
