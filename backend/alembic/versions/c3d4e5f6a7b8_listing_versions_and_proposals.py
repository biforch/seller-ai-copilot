"""Listing versions, proposals, product current pointer, and immutability trigger."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "c3d4e5f6a7b8"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None

LISTING_VERSION_IMMUTABILITY_FUNCTION = """
CREATE OR REPLACE FUNCTION prevent_listing_version_mutation()
RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        IF OLD.product_id IS DISTINCT FROM NEW.product_id
            OR OLD.version_number IS DISTINCT FROM NEW.version_number
            OR OLD.source IS DISTINCT FROM NEW.source
            OR OLD.title IS DISTINCT FROM NEW.title
            OR OLD.bullets IS DISTINCT FROM NEW.bullets
            OR OLD.description IS DISTINCT FROM NEW.description
            OR OLD.backend_keywords IS DISTINCT FROM NEW.backend_keywords
            OR OLD.marketplace IS DISTINCT FROM NEW.marketplace
            OR OLD.language IS DISTINCT FROM NEW.language
            OR OLD.parent_version_id IS DISTINCT FROM NEW.parent_version_id
            OR OLD.operation_idempotency_key IS DISTINCT FROM NEW.operation_idempotency_key
            OR OLD.request_hash IS DISTINCT FROM NEW.request_hash
            OR OLD.created_at IS DISTINCT FROM NEW.created_at
        THEN
            RAISE EXCEPTION 'listing_versions rows are immutable';
        END IF;

        IF OLD.generation_id IS DISTINCT FROM NEW.generation_id THEN
            IF NOT (OLD.generation_id IS NOT NULL AND NEW.generation_id IS NULL) THEN
                RAISE EXCEPTION 'listing_versions generation_id cannot be changed except to NULL';
            END IF;
        END IF;

        IF OLD.created_by IS DISTINCT FROM NEW.created_by THEN
            IF NOT (OLD.created_by IS NOT NULL AND NEW.created_by IS NULL) THEN
                RAISE EXCEPTION 'listing_versions created_by cannot be changed except to NULL';
            END IF;
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

LISTING_VERSION_IMMUTABILITY_TRIGGER = """
CREATE TRIGGER trg_listing_versions_immutable
BEFORE UPDATE ON listing_versions
FOR EACH ROW
EXECUTE FUNCTION prevent_listing_version_mutation();
"""


def upgrade() -> None:
    op.create_table(
        "listing_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("bullets", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("backend_keywords", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("marketplace", sa.String(length=50), nullable=False),
        sa.Column(
            "language",
            sa.String(length=20),
            nullable=False,
            server_default="en-US",
        ),
        sa.Column("generation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("parent_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("operation_idempotency_key", sa.String(length=36), nullable=True),
        sa.Column("request_hash", sa.String(length=64), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["generation_id"], ["generations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["parent_version_id"],
            ["listing_versions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint(
            "product_id",
            "version_number",
            name="uq_listing_versions_product_version",
        ),
        sa.UniqueConstraint(
            "product_id",
            "operation_idempotency_key",
            name="uq_listing_versions_product_idempotency",
        ),
        sa.CheckConstraint("version_number >= 1", name="ck_listing_versions_version_number_nonneg"),
        sa.CheckConstraint(
            "source IN ('manual', 'ai')",
            name="ck_listing_versions_source",
        ),
        sa.CheckConstraint("char_length(title) >= 1", name="ck_listing_versions_title_nonempty"),
        sa.CheckConstraint(
            "char_length(description) >= 1",
            name="ck_listing_versions_description_nonempty",
        ),
    )

    op.create_table(
        "listing_proposals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("base_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("candidate_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("field_decisions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="reviewing"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("generation_request_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("approved_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reviewed_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["base_version_id"],
            ["listing_versions.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["generation_request_id"],
            ["generation_requests.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["approved_version_id"],
            ["listing_versions.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "status IN ('reviewing', 'approved', 'rejected', 'superseded')",
            name="ck_listing_proposals_status",
        ),
        sa.CheckConstraint("revision >= 1", name="ck_listing_proposals_revision_nonneg"),
    )

    op.add_column(
        "products",
        sa.Column("current_listing_version_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_products_current_listing_version_id_listing_versions",
        "products",
        "listing_versions",
        ["current_listing_version_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_index(
        "ix_listing_versions_product_id_created_at",
        "listing_versions",
        ["product_id", sa.text("created_at DESC")],
        unique=False,
    )
    op.create_index(
        "ix_listing_proposals_product_id_status",
        "listing_proposals",
        ["product_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_listing_proposals_product_id_created_at",
        "listing_proposals",
        ["product_id", sa.text("created_at DESC")],
        unique=False,
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_listing_proposals_generation_request_id
        ON listing_proposals (generation_request_id)
        WHERE generation_request_id IS NOT NULL
        """
    )

    op.execute(LISTING_VERSION_IMMUTABILITY_FUNCTION)
    op.execute(LISTING_VERSION_IMMUTABILITY_TRIGGER)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_listing_versions_immutable ON listing_versions")
    op.execute("DROP FUNCTION IF EXISTS prevent_listing_version_mutation()")

    op.drop_index("uq_listing_proposals_generation_request_id", table_name="listing_proposals")
    op.drop_index("ix_listing_proposals_product_id_created_at", table_name="listing_proposals")
    op.drop_index("ix_listing_proposals_product_id_status", table_name="listing_proposals")
    op.drop_index("ix_listing_versions_product_id_created_at", table_name="listing_versions")

    op.drop_constraint(
        "fk_products_current_listing_version_id_listing_versions",
        "products",
        type_="foreignkey",
    )
    op.drop_column("products", "current_listing_version_id")

    op.drop_table("listing_proposals")
    op.drop_table("listing_versions")
