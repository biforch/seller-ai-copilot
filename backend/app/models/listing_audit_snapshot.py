import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base


class ListingAuditSnapshot(Base):
    """Immutable, normalized input captured for one or more listing audits."""

    __tablename__ = "listing_audit_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    amazon_listing_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("amazon_listings.id", ondelete="SET NULL"), nullable=True
    )
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    marketplace: Mapped[str] = mapped_column(String(32), nullable=False)
    asin: Mapped[str | None] = mapped_column(String(16), nullable=True)
    seller_sku: Mapped[str | None] = mapped_column(String(128), nullable=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    bullets: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    specifications: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    image_urls: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    amazon_listing = relationship("AmazonListing")

    __table_args__ = (
        CheckConstraint("source IN ('amazon', 'manual')", name="ck_audit_snapshots_source"),
        CheckConstraint(
            "content_hash ~ '^[0-9a-f]{64}$'", name="ck_audit_snapshots_content_hash"
        ),
        Index("ix_audit_snapshots_user_captured", "user_id", captured_at.desc(), "id"),
        Index("ix_audit_snapshots_amazon_listing", "amazon_listing_id", captured_at.desc()),
    )
