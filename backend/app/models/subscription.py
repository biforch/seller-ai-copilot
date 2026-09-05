import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.session import Base


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    plan: Mapped[str | None] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(50), default="active")
    expire_date: Mapped[datetime | None] = mapped_column(DateTime)
    provider: Mapped[str] = mapped_column(
        String(32), nullable=False, default="paddle", server_default="paddle"
    )
    provider_subscription_id: Mapped[str | None] = mapped_column(
        String(64), unique=True, nullable=True
    )
    provider_customer_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    provider_price_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    current_period_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    current_period_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancel_at_period_end: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (Index("ix_subscriptions_user_created", "user_id", "created_at"),)
