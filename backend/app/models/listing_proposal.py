import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base


class ListingProposalStatus:
    REVIEWING = "reviewing"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"

    ALL = frozenset({REVIEWING, APPROVED, REJECTED, SUPERSEDED})


class ListingProposal(Base):
    """Reviewable AI/manual candidate before it becomes an immutable version."""

    __tablename__ = "listing_proposals"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
    )
    base_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("listing_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    candidate_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    field_decisions: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=ListingProposalStatus.REVIEWING)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    generation_request_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("generation_requests.id", ondelete="SET NULL"),
        nullable=True,
    )
    approved_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("listing_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    product = relationship("Product", back_populates="listing_proposals", foreign_keys=[product_id])
    base_version = relationship("ListingVersion", foreign_keys=[base_version_id])
    approved_version = relationship("ListingVersion", foreign_keys=[approved_version_id])

    __table_args__ = (
        CheckConstraint(
            "status IN ('reviewing', 'approved', 'rejected', 'superseded')",
            name="ck_listing_proposals_status",
        ),
        CheckConstraint("revision >= 1", name="ck_listing_proposals_revision_nonneg"),
    )
