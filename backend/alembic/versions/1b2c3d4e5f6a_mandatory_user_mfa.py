"""Add mandatory user MFA state.

Revision ID: 1b2c3d4e5f6a
Revises: 0a1b2c3d4e5f
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "1b2c3d4e5f6a"
down_revision = "0a1b2c3d4e5f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("mfa_secret_ciphertext", sa.LargeBinary(), nullable=True))
    op.add_column("users", sa.Column("mfa_enabled_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("mfa_recovery_code_hashes", postgresql.JSONB(), nullable=True))
    op.add_column("users", sa.Column("mfa_last_totp_counter", sa.BigInteger(), nullable=True))
    op.add_column("auth_sessions", sa.Column("mfa_verified_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "auth_sessions",
        sa.Column("mfa_failed_attempts", sa.Integer(), server_default="0", nullable=False),
    )
    op.create_check_constraint(
        "ck_auth_sessions_mfa_failed_attempts_range",
        "auth_sessions",
        "mfa_failed_attempts >= 0 AND mfa_failed_attempts <= 5",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_auth_sessions_mfa_failed_attempts_range", "auth_sessions", type_="check"
    )
    op.drop_column("auth_sessions", "mfa_failed_attempts")
    op.drop_column("auth_sessions", "mfa_verified_at")
    op.drop_column("users", "mfa_last_totp_counter")
    op.drop_column("users", "mfa_recovery_code_hashes")
    op.drop_column("users", "mfa_enabled_at")
    op.drop_column("users", "mfa_secret_ciphertext")
