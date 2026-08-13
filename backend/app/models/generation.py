import uuid

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import UUID

from app.database.session import Base


class Generation(Base):

    __tablename__ = "generations"


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


    product_id = Column(
        UUID(as_uuid=True),
        ForeignKey(
            "products.id",
            ondelete="CASCADE",
        ),
        nullable=True,
    )


    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey(
            "projects.id",
            ondelete="CASCADE",
        ),
        nullable=True,
    )


    type = Column(
        String(50),
        nullable=False,
    )


    input = Column(
        JSON,
        nullable=False,
    )


    output = Column(
        JSON,
        nullable=False,
    )


    tokens_used = Column(
        Integer,
        default=0,
    )


    created_at = Column(
        DateTime,
        server_default=func.now(),
    )