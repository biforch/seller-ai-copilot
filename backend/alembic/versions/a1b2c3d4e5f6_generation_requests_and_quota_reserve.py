"""Alembic migration: generation_requests table and user reserved_tokens."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "a1b2c3d4e5f6"
down_revision = "34b6d855017a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("reserved_tokens", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_check_constraint(
        "ck_users_used_tokens_nonneg",
        "users",
        "used_tokens >= 0",
    )
    op.create_check_constraint(
        "ck_users_reserved_tokens_nonneg",
        "users",
        "reserved_tokens >= 0",
    )

    op.create_table(
        "generation_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("request_type", sa.String(length=50), nullable=False),
        sa.Column("idempotency_key", sa.String(length=36), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "product_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("products.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("input", postgresql.JSON(astext_type=sa.Text()), nullable=False),
        sa.Column("response_payload", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "generation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("generations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("model", sa.String(length=100), nullable=True),
        sa.Column("prompt_version", sa.String(length=50), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reserved_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("estimated_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=50), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'succeeded', 'failed')",
            name="ck_generation_requests_status",
        ),
        sa.CheckConstraint("reserved_tokens >= 0", name="ck_generation_requests_reserved_nonneg"),
        sa.CheckConstraint("tokens_used >= 0", name="ck_generation_requests_tokens_used_nonneg"),
        sa.UniqueConstraint(
            "user_id",
            "request_type",
            "idempotency_key",
            name="uq_generation_requests_idempotency",
        ),
    )
    op.create_index(
        "ix_generation_requests_user_id",
        "generation_requests",
        ["user_id"],
    )
    op.create_index(
        "ix_generation_requests_status_started_at",
        "generation_requests",
        ["status", "started_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_generation_requests_status_started_at", table_name="generation_requests")
    op.drop_index("ix_generation_requests_user_id", table_name="generation_requests")
    op.drop_table("generation_requests")

    op.drop_constraint("ck_users_reserved_tokens_nonneg", "users", type_="check")
    op.drop_constraint("ck_users_used_tokens_nonneg", "users", type_="check")
    op.drop_column("users", "reserved_tokens")
