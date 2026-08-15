import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base


class AmazonSyncOperation:
    VERIFY_ACCOUNT = "verify_account"
    MARKETPLACE_REFRESH = "marketplace_refresh"
    PRODUCT_SYNC = "product_sync"

    ALL = frozenset({VERIFY_ACCOUNT, MARKETPLACE_REFRESH, PRODUCT_SYNC})


class AmazonSyncStatus:
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"

    ALL = frozenset({PROCESSING, SUCCEEDED, FAILED})


class AmazonSyncLog(Base):
    __tablename__ = "amazon_sync_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    amazon_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("amazon_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    operation: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    items_seen: Mapped[int] = mapped_column(Integer(), nullable=False, default=0)
    items_written: Mapped[int] = mapped_column(Integer(), nullable=False, default=0)
    items_deactivated: Mapped[int] = mapped_column(Integer(), nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # A3.2: validate safe_detail UTF-8 JSON serialized byte length (max 512 bytes), not char count.
    safe_detail: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    amazon_account = relationship("AmazonAccount", back_populates="sync_logs")

    __table_args__ = (
        CheckConstraint(
            "operation IN ('verify_account', 'marketplace_refresh', 'product_sync')",
            name="ck_amazon_sync_logs_operation",
        ),
        CheckConstraint(
            "status IN ('processing', 'succeeded', 'failed')",
            name="ck_amazon_sync_logs_status",
        ),
        CheckConstraint("items_seen >= 0", name="ck_amazon_sync_logs_items_seen_nonneg"),
        CheckConstraint("items_written >= 0", name="ck_amazon_sync_logs_items_written_nonneg"),
        CheckConstraint(
            "items_deactivated >= 0",
            name="ck_amazon_sync_logs_items_deactivated_nonneg",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"AmazonSyncLog(id={self.id!s}, amazon_account_id={self.amazon_account_id!s}, "
            f"operation={self.operation!r}, status={self.status!r})"
        )
