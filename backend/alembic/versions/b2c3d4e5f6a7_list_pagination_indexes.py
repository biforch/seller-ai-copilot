"""Add indexes for paginated project/product list queries."""

from alembic import op

revision = "b2c3d4e5f6a7"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_projects_user_id_updated_at_created_at_id",
        "projects",
        ["user_id", "updated_at", "created_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_products_project_id_created_at_id",
        "products",
        ["project_id", "created_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_generations_product_id",
        "generations",
        ["product_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_generations_product_id", table_name="generations")
    op.drop_index("ix_products_project_id_created_at_id", table_name="products")
    op.drop_index("ix_projects_user_id_updated_at_created_at_id", table_name="projects")
