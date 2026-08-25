import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Integer, LargeBinary, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("used_tokens >= 0", name="ck_users_used_tokens_nonneg"),
        CheckConstraint("reserved_tokens >= 0", name="ck_users_reserved_tokens_nonneg"),
        CheckConstraint(
            "failed_login_attempts >= 0 AND failed_login_attempts <= 5",
            name="ck_users_failed_login_attempts_range",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    plan: Mapped[str] = mapped_column(String(50), default="free", nullable=False)
    monthly_tokens: Mapped[int] = mapped_column(Integer, default=10000, nullable=False)
    used_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reserved_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reset_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    failed_login_attempts: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False, server_default="0"
    )
    locked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    mfa_secret_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    mfa_enabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    mfa_recovery_code_hashes: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    mfa_last_totp_counter: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.now())

    products = relationship("Product", back_populates="user", cascade="all, delete")
    projects = relationship("Project", back_populates="user", cascade="all, delete")
    amazon_accounts = relationship(
        "AmazonAccount",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
