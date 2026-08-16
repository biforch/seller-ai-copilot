"""Amazon listings and selling_partner_id on accounts."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "1194054de91f"
down_revision = "558e1071cb88"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "amazon_accounts",
        sa.Column("selling_partner_id", sa.String(length=32), nullable=True),
    )
    op.create_index(
        "ix_amazon_accounts_selling_partner_id",
        "amazon_accounts",
        ["selling_partner_id"],
    )

    op.create_table(
        "amazon_listings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("amazon_account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("marketplace_id", sa.String(length=32), nullable=False),
        sa.Column("seller_sku", sa.String(length=128), nullable=False),
        sa.Column("asin", sa.String(length=16), nullable=True),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "status_codes",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("product_type", sa.String(length=128), nullable=True),
        sa.Column("upstream_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("upstream_last_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("last_seen_sync_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
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
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "amazon_account_id",
            "marketplace_id",
            "seller_sku",
            name="uq_amazon_listings_account_marketplace_sku",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(status_codes) = 'array'",
            name="ck_amazon_listings_status_codes_array",
        ),
        sa.CheckConstraint(
            "length(trim(marketplace_id)) > 0",
            name="ck_amazon_listings_marketplace_id_not_blank",
        ),
        sa.CheckConstraint(
            "length(trim(seller_sku)) > 0",
            name="ck_amazon_listings_seller_sku_not_blank",
        ),
    )
    op.create_index(
        "ix_amazon_listings_account_marketplace_updated",
        "amazon_listings",
        ["amazon_account_id", "marketplace_id", "updated_at", "id"],
    )
    op.create_index(
        "ix_amazon_listings_product_id",
        "amazon_listings",
        ["product_id"],
    )
    op.create_index(
        "ix_amazon_listings_account_marketplace_last_seen_sync",
        "amazon_listings",
        ["amazon_account_id", "marketplace_id", "last_seen_sync_id"],
    )
    op.create_index(
        "ix_amazon_listings_asin",
        "amazon_listings",
        ["asin"],
    )


def downgrade() -> None:
    op.drop_index("ix_amazon_listings_asin", table_name="amazon_listings")
    op.drop_index(
        "ix_amazon_listings_account_marketplace_last_seen_sync",
        table_name="amazon_listings",
    )
    op.drop_index("ix_amazon_listings_product_id", table_name="amazon_listings")
    op.drop_index(
        "ix_amazon_listings_account_marketplace_updated",
        table_name="amazon_listings",
    )
    op.drop_table("amazon_listings")

    op.drop_index("ix_amazon_accounts_selling_partner_id", table_name="amazon_accounts")
    op.drop_column("amazon_accounts", "selling_partner_id")
