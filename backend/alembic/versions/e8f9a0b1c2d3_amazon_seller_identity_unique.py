"""Amazon selling_partner_id global unique identity."""

import sqlalchemy as sa

from alembic import op

revision = "e8f9a0b1c2d3"
down_revision = "d7e8f9a0b1c2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    duplicates = connection.execute(
        sa.text(
            """
            SELECT selling_partner_id, COUNT(*) AS row_count
            FROM amazon_accounts
            WHERE selling_partner_id IS NOT NULL
            GROUP BY selling_partner_id
            HAVING COUNT(*) > 1
            """
        )
    ).fetchall()
    if duplicates:
        raise RuntimeError(
            "Cannot add uq_amazon_accounts_selling_partner_id: "
            "duplicate non-null selling_partner_id values exist"
        )

    op.create_check_constraint(
        "ck_amazon_accounts_selling_partner_id_format",
        "amazon_accounts",
        "selling_partner_id IS NULL OR selling_partner_id ~ '^[A-Za-z0-9]{1,32}$'",
    )
    op.drop_index("ix_amazon_accounts_selling_partner_id", table_name="amazon_accounts")
    op.create_unique_constraint(
        "uq_amazon_accounts_selling_partner_id",
        "amazon_accounts",
        ["selling_partner_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_amazon_accounts_selling_partner_id",
        "amazon_accounts",
        type_="unique",
    )
    op.drop_constraint(
        "ck_amazon_accounts_selling_partner_id_format",
        "amazon_accounts",
        type_="check",
    )
    op.create_index(
        "ix_amazon_accounts_selling_partner_id",
        "amazon_accounts",
        ["selling_partner_id"],
    )
