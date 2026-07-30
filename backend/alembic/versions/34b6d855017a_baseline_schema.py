"""baseline: users, projects, products, generations, subscriptions

这不是一次"新的"schema变更 —— 项目一直是靠
Base.metadata.create_all() 建表 + 手动 ALTER TABLE 迭代的，
从来没有被 Alembic 追踪过。

这个 revision 把当前(2026-07)线上/本地 DB 的实际结构原样描述出来，
作为 Alembic 的起点：

    - users / subscriptions：从项目最初就有，没变过
    - projects：Step 1 加了 description / status / updated_at
    - products：Step 3 加了 target_customer / advantages
    - generations：没变过

因为这些表在你的 DB 里已经存在了，不要用 `alembic upgrade head`
（会尝试重新 CREATE TABLE 然后报错"already exists"）。
第一次要用：

    alembic stamp head

这只是把 DB 标记为"已经在这个 revision"，不会真的执行任何 SQL。
之后新的 schema 变更就正常用
`alembic revision --autogenerate -m "..."` + `alembic upgrade head`。

Revision ID: 34b6d855017a
Revises:
Create Date: 2026-07-29
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "34b6d855017a"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False, unique=True, index=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("plan", sa.String(50), nullable=False, server_default="free"),
        sa.Column("monthly_tokens", sa.Integer(), nullable=False, server_default="10000"),
        sa.Column("used_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reset_date", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()")),
    )

    op.create_table(
        "projects",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.String(1000), nullable=True),
        sa.Column("platform", sa.String(50), nullable=False, server_default="Amazon"),
        sa.Column("market", sa.String(50), nullable=False, server_default="USA"),
        sa.Column("status", sa.String(50), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "products",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("category", sa.String(100), nullable=True),
        sa.Column("platform", sa.String(50), nullable=False, server_default="Amazon"),
        sa.Column("market", sa.String(50), nullable=False, server_default="USA"),
        sa.Column("target_customer", sa.String(255), nullable=True),
        sa.Column("advantages", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()")),
    )

    op.create_table(
        "generations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "product_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("products.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("type", sa.String(50), nullable=False),
        sa.Column("input", sa.JSON(), nullable=False),
        sa.Column("output", sa.JSON(), nullable=False),
        sa.Column("tokens_used", sa.Integer(), server_default="0"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()")),
    )

    op.create_table(
        "subscriptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("plan", sa.String(50), nullable=True),
        sa.Column("status", sa.String(50), server_default="active"),
        sa.Column("expire_date", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()")),
    )


def downgrade() -> None:

    op.drop_table("subscriptions")
    op.drop_table("generations")
    op.drop_table("products")
    op.drop_table("projects")
    op.drop_table("users")
