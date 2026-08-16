import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    LargeBinary,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base


class AmazonAccountStatus:
    ACTIVE = "active"
    REAUTHORIZATION_REQUIRED = "reauthorization_required"
    DISABLED = "disabled"
    ERROR = "error"

    ALL = frozenset({ACTIVE, REAUTHORIZATION_REQUIRED, DISABLED, ERROR})


def new_account_key() -> str:
    return str(uuid.uuid4())


class AmazonAccount(Base):
    __tablename__ = "amazon_accounts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    account_key: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
        unique=True,
        default=new_account_key,
    )
    region: Mapped[str] = mapped_column(String(2), nullable=False)
    endpoint_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=AmazonAccountStatus.ACTIVE)
    refresh_token_ciphertext: Mapped[bytes] = mapped_column(LargeBinary(), nullable=False)
    refresh_token_key_version: Mapped[int] = mapped_column(SmallInteger(), nullable=False)
    refresh_token_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    # OAuth redirect provides selling_partner_id; nullable for pre-OAuth accounts.
    # Official OpenAPI in repo does not declare maxLength — 32 is conservative.
    selling_partner_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    sync_lease_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    sync_lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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

    user = relationship("User", back_populates="amazon_accounts")
    marketplace_participations = relationship(
        "AmazonMarketplaceParticipation",
        back_populates="amazon_account",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    sync_logs = relationship(
        "AmazonSyncLog",
        back_populates="amazon_account",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    amazon_listings = relationship(
        "AmazonListing",
        back_populates="amazon_account",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        CheckConstraint("region IN ('na', 'eu', 'fe')", name="ck_amazon_accounts_region"),
        CheckConstraint(
            "endpoint_mode IN ('sandbox', 'production')",
            name="ck_amazon_accounts_endpoint_mode",
        ),
        CheckConstraint(
            "status IN ('active', 'reauthorization_required', 'disabled', 'error')",
            name="ck_amazon_accounts_status",
        ),
        CheckConstraint(
            "refresh_token_key_version >= 0",
            name="ck_amazon_accounts_key_version_nonneg",
        ),
        CheckConstraint(
            "refresh_token_key_version <= 65535",
            name="ck_amazon_accounts_key_version_max",
        ),
        UniqueConstraint(
            "user_id",
            "refresh_token_fingerprint",
            name="uq_amazon_accounts_user_fingerprint",
        ),
        Index("ix_amazon_accounts_user_id_updated_at", "user_id", "updated_at"),
    )

    def __repr__(self) -> str:
        return (
            f"AmazonAccount(id={self.id!s}, user_id={self.user_id!s}, "
            f"region={self.region!r}, status={self.status!r})"
        )
