from sqlalchemy import (
    Column,
    String,
    DateTime,
    ForeignKey,
    func,
)

from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

import uuid

from app.database.session import Base


class Project(Base):

    __tablename__ = "projects"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey(
            "users.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )

    name = Column(
        String(255),
        nullable=False,
    )

    description = Column(
        String(1000),
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

    status = Column(
        String(50),
        default="active",
        nullable=False,
    )

    created_at = Column(
        DateTime,
        server_default=func.now(),
        nullable=False,
    )

    updated_at = Column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    user = relationship(
        "User",
        back_populates="projects",
    )

    products = relationship(
        "Product",
        back_populates="project",
        cascade="all, delete",
    )