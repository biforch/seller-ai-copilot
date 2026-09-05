"""Immutable listing audit snapshots.

Revision ID: 2c3d4e5f6a7b
Revises: 1b2c3d4e5f6a
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "2c3d4e5f6a7b"
down_revision = "1b2c3d4e5f6a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "listing_audit_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("amazon_listing_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("marketplace", sa.String(length=32), nullable=False),
        sa.Column("asin", sa.String(length=16), nullable=True),
        sa.Column("seller_sku", sa.String(length=128), nullable=True),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("bullets", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("specifications", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("image_urls", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("source_request_id", sa.String(length=64), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("source IN ('amazon', 'manual')", name="ck_audit_snapshots_source"),
        sa.CheckConstraint("content_hash ~ '^[0-9a-f]{64}$'", name="ck_audit_snapshots_content_hash"),
        sa.ForeignKeyConstraint(["amazon_listing_id"], ["amazon_listings.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_audit_snapshots_user_captured",
        "listing_audit_snapshots",
        ["user_id", sa.text("captured_at DESC"), "id"],
    )
    op.create_index(
        "ix_audit_snapshots_amazon_listing",
        "listing_audit_snapshots",
        ["amazon_listing_id", sa.text("captured_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_audit_snapshots_amazon_listing", table_name="listing_audit_snapshots")
    op.drop_index("ix_audit_snapshots_user_captured", table_name="listing_audit_snapshots")
    op.drop_table("listing_audit_snapshots")
