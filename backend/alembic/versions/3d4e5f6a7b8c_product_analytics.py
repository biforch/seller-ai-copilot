"""Add privacy-minimal product analytics events and admin access.

Revision ID: 3d4e5f6a7b8c
Revises: 2c3d4e5f6a7b
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "3d4e5f6a7b8c"
down_revision = "2c3d4e5f6a7b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("is_admin", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.create_table(
        "product_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "event_type IN ('registration_completed','audit_started','audit_completed','audit_failed','amazon_connect_started','amazon_connected')",
            name="ck_product_events_type",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_product_events_occurred_type", "product_events", [sa.text("occurred_at DESC"), "event_type"])
    op.create_index("ix_product_events_user_occurred", "product_events", ["user_id", sa.text("occurred_at DESC")])


def downgrade() -> None:
    op.drop_index("ix_product_events_user_occurred", table_name="product_events")
    op.drop_index("ix_product_events_occurred_type", table_name="product_events")
    op.drop_table("product_events")
    op.drop_column("users", "is_admin")
