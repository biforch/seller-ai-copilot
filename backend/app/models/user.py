from sqlalchemy import Column, String, DateTime, Integer, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import uuid

from app.database.session import Base


class User(Base):
    __tablename__ = "users"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )

    email = Column(
        String(255),
        unique=True,
        nullable=False,
        index=True
    )

    password_hash = Column(
        String(255),
        nullable=False
    )

    # 用户套餐
    plan = Column(
        String(50),
        default="free",
        nullable=False
    )

    # 每月token额度
    monthly_tokens = Column(
        Integer,
        default=10000,
        nullable=False
    )

    # 已使用token
    used_tokens = Column(
        Integer,
        default=0,
        nullable=False
    )

    # 下次额度重置时间
    reset_date = Column(
        DateTime,
        nullable=True
    )

    created_at = Column(
        DateTime,
        server_default=func.now()
    )

    products = relationship(
        "Product",
        back_populates="user",
        cascade="all, delete",
    )

    projects = relationship(
        "Project",
        back_populates="user",
        cascade="all, delete",
    )