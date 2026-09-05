"""Paddle subscriptions and completed-audit allowances.

Revision ID: 4e5f6a7b8c9d
Revises: 3d4e5f6a7b8c
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "4e5f6a7b8c9d"
down_revision = "3d4e5f6a7b8c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "subscriptions",
        sa.Column("provider", sa.String(32), nullable=False, server_default="paddle"),
    )
    op.add_column(
        "subscriptions", sa.Column("provider_subscription_id", sa.String(64), nullable=True)
    )
    op.add_column("subscriptions", sa.Column("provider_customer_id", sa.String(64), nullable=True))
    op.add_column("subscriptions", sa.Column("provider_price_id", sa.String(64), nullable=True))
    op.add_column(
        "subscriptions",
        sa.Column("current_period_start", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "subscriptions", sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "subscriptions",
        sa.Column(
            "cancel_at_period_end",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "subscriptions",
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_unique_constraint(
        "uq_subscriptions_provider_subscription", "subscriptions", ["provider_subscription_id"]
    )
    op.create_index(
        "ix_subscriptions_provider_customer_id", "subscriptions", ["provider_customer_id"]
    )
    op.create_index("ix_subscriptions_user_created", "subscriptions", ["user_id", "created_at"])

    op.create_table(
        "audit_usage",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("attempt_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("plan", sa.String(16), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "generation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("generations.id", ondelete="SET NULL"),
            nullable=True,
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
        sa.CheckConstraint(
            "status IN ('reserved','completed','released')", name="ck_audit_usage_status"
        ),
        sa.CheckConstraint("plan IN ('free','plus','pro')", name="ck_audit_usage_plan"),
    )
    op.create_index(
        "ix_audit_usage_user_period_status",
        "audit_usage",
        ["user_id", "period_start", "period_end", "status"],
    )
    op.create_table(
        "paddle_webhook_events",
        sa.Column("event_id", sa.String(64), primary_key=True),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )


def downgrade() -> None:
    op.drop_table("paddle_webhook_events")
    op.drop_index("ix_audit_usage_user_period_status", table_name="audit_usage")
    op.drop_table("audit_usage")
    op.drop_index("ix_subscriptions_user_created", table_name="subscriptions")
    op.drop_index("ix_subscriptions_provider_customer_id", table_name="subscriptions")
    op.drop_constraint("uq_subscriptions_provider_subscription", "subscriptions", type_="unique")
    for name in (
        "updated_at",
        "cancel_at_period_end",
        "current_period_end",
        "current_period_start",
        "provider_price_id",
        "provider_customer_id",
        "provider_subscription_id",
        "provider",
    ):
        op.drop_column("subscriptions", name)
