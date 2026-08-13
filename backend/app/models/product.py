import uuid

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    ForeignKey,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database.session import Base


class Product(Base):

    __tablename__ = "products"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # 用户
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey(
            "users.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )

    # 所属项目
    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey(
            "projects.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )

    name = Column(
        String(255),
        nullable=False,
    )

    category = Column(
        String(100),
        nullable=True,
    )

    platform = Column(
        String(50),
        default="Amazon",
        nullable=False,
    )

    market = Column(
        String(50),
        default="USA",
        nullable=False,
    )

    # 目标客户，例如 "young professionals"
    target_customer = Column(
        String(255),
        nullable=True,
    )

    # 产品卖点/优势列表，例如 ["noise cancellation", "long battery"]
    advantages = Column(
        JSON,
        nullable=True,
    )

    created_at = Column(
        DateTime,
        server_default=func.now(),
    )

    project = relationship(
        "Project",
        back_populates="products",
    )

    user = relationship(
        "User",
        back_populates="products",
    )