import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base


class AmazonCatalogSnapshot(Base):
    """Bounded normalized catalog summary; raw provider payloads are never stored."""

    __tablename__ = "amazon_catalog_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    amazon_listing_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("amazon_listings.id", ondelete="CASCADE"),
        nullable=False,
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    asin: Mapped[str] = mapped_column(String(16), nullable=False)
    marketplace_id: Mapped[str] = mapped_column(String(32), nullable=False)
    item_name: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    brand: Mapped[str | None] = mapped_column(String(256), nullable=True)
    manufacturer: Mapped[str | None] = mapped_column(String(256), nullable=True)
    color: Mapped[str | None] = mapped_column(String(256), nullable=True)
    size: Mapped[str | None] = mapped_column(String(256), nullable=True)
    style: Mapped[str | None] = mapped_column(String(256), nullable=True)
    model_number: Mapped[str | None] = mapped_column(String(256), nullable=True)
    part_number: Mapped[str | None] = mapped_column(String(256), nullable=True)
    product_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    amazon_listing = relationship("AmazonListing", back_populates="catalog_snapshots")

    __table_args__ = (
        UniqueConstraint(
            "amazon_listing_id",
            "content_hash",
            name="uq_amazon_catalog_snapshots_listing_content",
        ),
        CheckConstraint(
            "content_hash ~ '^[0-9a-f]{64}$'",
            name="ck_amazon_catalog_snapshots_content_hash_format",
        ),
        CheckConstraint(
            "asin ~ '^[A-Z0-9]{10}$'",
            name="ck_amazon_catalog_snapshots_asin_format",
        ),
        CheckConstraint(
            "length(trim(marketplace_id)) > 0",
            name="ck_amazon_catalog_snapshots_marketplace_not_blank",
        ),
        CheckConstraint(
            "expires_at > fetched_at",
            name="ck_amazon_catalog_snapshots_expires_after_fetch",
        ),
        Index(
            "ix_amazon_catalog_snapshots_listing_fetched",
            "amazon_listing_id",
            fetched_at.desc(),
            "id",
        ),
        Index("ix_amazon_catalog_snapshots_expires_at", "expires_at"),
    )

    def __repr__(self) -> str:
        return (
            f"AmazonCatalogSnapshot(id={self.id!s}, amazon_listing_id="
            f"{self.amazon_listing_id!s}, asin={self.asin!r}, "
            f"marketplace_id={self.marketplace_id!r}, fetched_at={self.fetched_at!r})"
        )
