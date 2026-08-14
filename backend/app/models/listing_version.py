import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base


class ListingVersionSource:
    MANUAL = "manual"
    AI = "ai"

    ALL = frozenset({MANUAL, AI})


class ListingVersion(Base):
    """Immutable published listing version for a product."""

    __tablename__ = "listing_versions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    bullets: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    backend_keywords: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    marketplace: Mapped[str] = mapped_column(String(50), nullable=False)
    language: Mapped[str] = mapped_column(String(20), nullable=False, server_default="en-US")
    generation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("generations.id", ondelete="SET NULL"),
        nullable=True,
    )
    parent_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("listing_versions.id", ondelete="RESTRICT"),
        nullable=True,
    )
    operation_idempotency_key: Mapped[str | None] = mapped_column(String(36), nullable=True)
    request_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    product = relationship("Product", back_populates="listing_versions", foreign_keys=[product_id])
    parent_version = relationship("ListingVersion", remote_side=[id], foreign_keys=[parent_version_id])

    __table_args__ = (
        UniqueConstraint("product_id", "version_number", name="uq_listing_versions_product_version"),
        UniqueConstraint(
            "product_id",
            "operation_idempotency_key",
            name="uq_listing_versions_product_idempotency",
        ),
        CheckConstraint("version_number >= 1", name="ck_listing_versions_version_number_nonneg"),
        CheckConstraint(
            "source IN ('manual', 'ai')",
            name="ck_listing_versions_source",
        ),
        CheckConstraint("char_length(title) >= 1", name="ck_listing_versions_title_nonempty"),
        CheckConstraint("char_length(description) >= 1", name="ck_listing_versions_description_nonempty"),
    )
