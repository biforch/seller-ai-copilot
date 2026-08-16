import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.session import Base


class OAuthStateIntent:
    CONNECT = "connect"
    REAUTHORIZE = "reauthorize"

    ALL = frozenset({CONNECT, REAUTHORIZE})


class OAuthStateStatus:
    PENDING = "pending"
    CONSUMED = "consumed"

    ALL = frozenset({PENDING, CONSUMED})


STATE_TOKEN_HASH_UNIQUE_CONSTRAINT = "uq_amazon_oauth_states_state_token_hash"


class AmazonOAuthState(Base):
    __tablename__ = "amazon_oauth_states"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    state_token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    marketplace_code: Mapped[str] = mapped_column(String(8), nullable=False)
    region: Mapped[str] = mapped_column(String(2), nullable=False)
    intent: Mapped[str] = mapped_column(String(16), nullable=False)
    target_account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("amazon_accounts.id", ondelete="CASCADE"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=OAuthStateStatus.PENDING,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint(
            "state_token_hash ~ '^[0-9a-f]{64}$'",
            name="ck_amazon_oauth_states_state_token_hash_format",
        ),
        CheckConstraint("region IN ('na', 'eu', 'fe')", name="ck_amazon_oauth_states_region"),
        CheckConstraint(
            "intent IN ('connect', 'reauthorize')",
            name="ck_amazon_oauth_states_intent",
        ),
        CheckConstraint(
            "status IN ('pending', 'consumed')",
            name="ck_amazon_oauth_states_status",
        ),
        CheckConstraint(
            "(intent = 'connect' AND target_account_id IS NULL) OR "
            "(intent = 'reauthorize' AND target_account_id IS NOT NULL)",
            name="ck_amazon_oauth_states_intent_target_account",
        ),
        CheckConstraint(
            "(status = 'pending' AND consumed_at IS NULL) OR "
            "(status = 'consumed' AND consumed_at IS NOT NULL)",
            name="ck_amazon_oauth_states_status_consumed_at",
        ),
        CheckConstraint(
            "expires_at > created_at",
            name="ck_amazon_oauth_states_expires_after_created",
        ),
        UniqueConstraint("state_token_hash", name=STATE_TOKEN_HASH_UNIQUE_CONSTRAINT),
        Index("ix_amazon_oauth_states_status_expires_at", "status", "expires_at"),
        Index("ix_amazon_oauth_states_user_id_created_at", "user_id", "created_at"),
        Index("ix_amazon_oauth_states_target_account_id", "target_account_id"),
    )

    def __repr__(self) -> str:
        return (
            f"AmazonOAuthState(id={self.id!s}, user_id={self.user_id!s}, "
            f"intent={self.intent!r}, status={self.status!r})"
        )
