"""Amazon accounts, marketplace participations, and sync logs."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "558e1071cb88"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "amazon_accounts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("account_key", sa.String(length=36), nullable=False),
        sa.Column("region", sa.String(length=2), nullable=False),
        sa.Column("endpoint_mode", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("refresh_token_ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("refresh_token_key_version", sa.SmallInteger(), nullable=False),
        sa.Column("refresh_token_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("sync_lease_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("sync_lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("account_key", name="uq_amazon_accounts_account_key"),
        sa.CheckConstraint("region IN ('na', 'eu', 'fe')", name="ck_amazon_accounts_region"),
        sa.CheckConstraint(
            "endpoint_mode IN ('sandbox', 'production')",
            name="ck_amazon_accounts_endpoint_mode",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'reauthorization_required', 'disabled', 'error')",
            name="ck_amazon_accounts_status",
        ),
        sa.CheckConstraint(
            "refresh_token_key_version >= 0",
            name="ck_amazon_accounts_key_version_nonneg",
        ),
        sa.CheckConstraint(
            "refresh_token_key_version <= 65535",
            name="ck_amazon_accounts_key_version_max",
        ),
        sa.UniqueConstraint(
            "user_id",
            "refresh_token_fingerprint",
            name="uq_amazon_accounts_user_fingerprint",
        ),
    )
    op.create_index(
        "ix_amazon_accounts_user_id_updated_at",
        "amazon_accounts",
        ["user_id", "updated_at"],
    )
    op.create_index(
        "ix_amazon_accounts_sync_lease_expires_at",
        "amazon_accounts",
        ["sync_lease_expires_at"],
    )

    op.create_table(
        "amazon_marketplace_participations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("amazon_account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("marketplace_id", sa.String(length=32), nullable=False),
        sa.Column("marketplace_name", sa.String(length=255), nullable=False),
        sa.Column("country_code", sa.String(length=8), nullable=False),
        sa.Column("default_currency_code", sa.String(length=8), nullable=True),
        sa.Column("default_language_code", sa.String(length=16), nullable=True),
        sa.Column("domain_name", sa.String(length=255), nullable=True),
        sa.Column("participating", sa.Boolean(), nullable=False),
        sa.Column("suspended_listings", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["amazon_account_id"],
            ["amazon_accounts.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "amazon_account_id",
            "marketplace_id",
            name="uq_amp_account_marketplace",
        ),
    )
    op.create_index(
        "ix_amp_amazon_account_id",
        "amazon_marketplace_participations",
        ["amazon_account_id"],
    )
    op.create_index(
        "ix_amp_account_active",
        "amazon_marketplace_participations",
        ["amazon_account_id", "is_active"],
    )

    op.create_table(
        "amazon_sync_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("amazon_account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("operation", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column("items_seen", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("items_written", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("items_deactivated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("safe_detail", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["amazon_account_id"],
            ["amazon_accounts.id"],
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "operation IN ('verify_account', 'marketplace_refresh', 'product_sync')",
            name="ck_amazon_sync_logs_operation",
        ),
        sa.CheckConstraint(
            "status IN ('processing', 'succeeded', 'failed')",
            name="ck_amazon_sync_logs_status",
        ),
        sa.CheckConstraint("items_seen >= 0", name="ck_amazon_sync_logs_items_seen_nonneg"),
        sa.CheckConstraint(
            "items_written >= 0",
            name="ck_amazon_sync_logs_items_written_nonneg",
        ),
        sa.CheckConstraint(
            "items_deactivated >= 0",
            name="ck_amazon_sync_logs_items_deactivated_nonneg",
        ),
    )
    op.create_index(
        "ix_amazon_sync_logs_account_started",
        "amazon_sync_logs",
        ["amazon_account_id", "started_at"],
    )
    op.create_index(
        "ix_amazon_sync_logs_account_operation_status",
        "amazon_sync_logs",
        ["amazon_account_id", "operation", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_amazon_sync_logs_account_operation_status", table_name="amazon_sync_logs")
    op.drop_index("ix_amazon_sync_logs_account_started", table_name="amazon_sync_logs")
    op.drop_table("amazon_sync_logs")

    op.drop_index("ix_amp_account_active", table_name="amazon_marketplace_participations")
    op.drop_index("ix_amp_amazon_account_id", table_name="amazon_marketplace_participations")
    op.drop_table("amazon_marketplace_participations")

    op.drop_index("ix_amazon_accounts_sync_lease_expires_at", table_name="amazon_accounts")
    op.drop_index("ix_amazon_accounts_user_id_updated_at", table_name="amazon_accounts")
    op.drop_table("amazon_accounts")
