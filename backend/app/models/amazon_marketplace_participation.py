import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base


class AmazonMarketplaceParticipation(Base):
    __tablename__ = "amazon_marketplace_participations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    amazon_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("amazon_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    marketplace_id: Mapped[str] = mapped_column(String(32), nullable=False)
    marketplace_name: Mapped[str] = mapped_column(String(255), nullable=False)
    country_code: Mapped[str] = mapped_column(String(8), nullable=False)
    default_currency_code: Mapped[str | None] = mapped_column(String(8), nullable=True)
    default_language_code: Mapped[str | None] = mapped_column(String(16), nullable=True)
    domain_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    participating: Mapped[bool] = mapped_column(Boolean(), nullable=False)
    suspended_listings: Mapped[bool] = mapped_column(Boolean(), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean(), nullable=False, default=True)
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
        nullable=False,
    )

    amazon_account = relationship("AmazonAccount", back_populates="marketplace_participations")

    __table_args__ = (
        UniqueConstraint(
            "amazon_account_id",
            "marketplace_id",
            name="uq_amp_account_marketplace",
        ),
    )

    @property
    def sync_eligible(self) -> bool:
        # Local read-only hint from participation flags only.
        # Does not prove Listings, Orders, Reports, or write permissions.
        return self.participating and not self.suspended_listings

    def __repr__(self) -> str:
        return (
            f"AmazonMarketplaceParticipation(id={self.id!s}, "
            f"amazon_account_id={self.amazon_account_id!s}, "
            f"marketplace_id={self.marketplace_id!r}, is_active={self.is_active})"
        )
