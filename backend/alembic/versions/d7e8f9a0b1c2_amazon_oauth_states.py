"""Amazon OAuth state persistence."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "d7e8f9a0b1c2"
down_revision = "1194054de91f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "amazon_oauth_states",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("state_token_hash", sa.String(length=64), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("marketplace_code", sa.String(length=8), nullable=False),
        sa.Column("region", sa.String(length=2), nullable=False),
        sa.Column("intent", sa.String(length=16), nullable=False),
        sa.Column("target_account_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_account_id"], ["amazon_accounts.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("state_token_hash", name="uq_amazon_oauth_states_state_token_hash"),
        sa.CheckConstraint(
            "state_token_hash ~ '^[0-9a-f]{64}$'",
            name="ck_amazon_oauth_states_state_token_hash_format",
        ),
        sa.CheckConstraint("region IN ('na', 'eu', 'fe')", name="ck_amazon_oauth_states_region"),
        sa.CheckConstraint(
            "intent IN ('connect', 'reauthorize')",
            name="ck_amazon_oauth_states_intent",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'consumed')",
            name="ck_amazon_oauth_states_status",
        ),
        sa.CheckConstraint(
            "(intent = 'connect' AND target_account_id IS NULL) OR "
            "(intent = 'reauthorize' AND target_account_id IS NOT NULL)",
            name="ck_amazon_oauth_states_intent_target_account",
        ),
        sa.CheckConstraint(
            "(status = 'pending' AND consumed_at IS NULL) OR "
            "(status = 'consumed' AND consumed_at IS NOT NULL)",
            name="ck_amazon_oauth_states_status_consumed_at",
        ),
        sa.CheckConstraint(
            "expires_at > created_at",
            name="ck_amazon_oauth_states_expires_after_created",
        ),
    )
    op.create_index(
        "ix_amazon_oauth_states_status_expires_at",
        "amazon_oauth_states",
        ["status", "expires_at"],
    )
    op.create_index(
        "ix_amazon_oauth_states_user_id_created_at",
        "amazon_oauth_states",
        ["user_id", "created_at"],
    )
    op.create_index(
        "ix_amazon_oauth_states_target_account_id",
        "amazon_oauth_states",
        ["target_account_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_amazon_oauth_states_target_account_id", table_name="amazon_oauth_states")
    op.drop_index("ix_amazon_oauth_states_user_id_created_at", table_name="amazon_oauth_states")
    op.drop_index("ix_amazon_oauth_states_status_expires_at", table_name="amazon_oauth_states")
    op.drop_table("amazon_oauth_states")
