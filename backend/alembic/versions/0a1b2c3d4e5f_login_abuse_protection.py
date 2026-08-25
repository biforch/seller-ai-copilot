"""Add persistent login abuse protection state.

Revision ID: 0a1b2c3d4e5f
Revises: a0b1c2d3e4f6
"""

import sqlalchemy as sa

from alembic import op

revision = "0a1b2c3d4e5f"
down_revision = "a0b1c2d3e4f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("failed_login_attempts", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "users",
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_users_failed_login_attempts_range",
        "users",
        "failed_login_attempts >= 0 AND failed_login_attempts <= 5",
    )


def downgrade() -> None:
    op.drop_constraint("ck_users_failed_login_attempts_range", "users", type_="check")
    op.drop_column("users", "locked_until")
    op.drop_column("users", "failed_login_attempts")
