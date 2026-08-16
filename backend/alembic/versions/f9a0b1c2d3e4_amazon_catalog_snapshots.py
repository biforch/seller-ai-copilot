"""Amazon catalog normalized content snapshots.

Revision ID: f9a0b1c2d3e4
Revises: e8f9a0b1c2d3
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "f9a0b1c2d3e4"
down_revision = "e8f9a0b1c2d3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "amazon_catalog_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("amazon_listing_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("asin", sa.String(length=16), nullable=False),
        sa.Column("marketplace_id", sa.String(length=32), nullable=False),
        sa.Column("item_name", sa.String(length=2000), nullable=True),
        sa.Column("brand", sa.String(length=256), nullable=True),
        sa.Column("manufacturer", sa.String(length=256), nullable=True),
        sa.Column("color", sa.String(length=256), nullable=True),
        sa.Column("size", sa.String(length=256), nullable=True),
        sa.Column("style", sa.String(length=256), nullable=True),
        sa.Column("model_number", sa.String(length=256), nullable=True),
        sa.Column("part_number", sa.String(length=256), nullable=True),
        sa.Column("product_type", sa.String(length=128), nullable=True),
        sa.Column("source_request_id", sa.String(length=64), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
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
        sa.CheckConstraint(
            "content_hash ~ '^[0-9a-f]{64}$'",
            name="ck_amazon_catalog_snapshots_content_hash_format",
        ),
        sa.CheckConstraint(
            "asin ~ '^[A-Z0-9]{10}$'",
            name="ck_amazon_catalog_snapshots_asin_format",
        ),
        sa.CheckConstraint(
            "length(trim(marketplace_id)) > 0",
            name="ck_amazon_catalog_snapshots_marketplace_not_blank",
        ),
        sa.CheckConstraint(
            "expires_at > fetched_at",
            name="ck_amazon_catalog_snapshots_expires_after_fetch",
        ),
        sa.ForeignKeyConstraint(
            ["amazon_listing_id"],
            ["amazon_listings.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "amazon_listing_id",
            "content_hash",
            name="uq_amazon_catalog_snapshots_listing_content",
        ),
    )
    op.create_index(
        "ix_amazon_catalog_snapshots_listing_fetched",
        "amazon_catalog_snapshots",
        ["amazon_listing_id", sa.text("fetched_at DESC"), "id"],
    )
    op.create_index(
        "ix_amazon_catalog_snapshots_expires_at",
        "amazon_catalog_snapshots",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_amazon_catalog_snapshots_expires_at",
        table_name="amazon_catalog_snapshots",
    )
    op.drop_index(
        "ix_amazon_catalog_snapshots_listing_fetched",
        table_name="amazon_catalog_snapshots",
    )
    op.drop_table("amazon_catalog_snapshots")
