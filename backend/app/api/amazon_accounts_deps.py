"""FastAPI dependencies for tenant-scoped Amazon account reads."""

from __future__ import annotations

from fastapi import Depends
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.services.amazon_account_read_service import AmazonAccountReadService


def get_amazon_account_read_service(
    db: Session = Depends(get_db),
) -> AmazonAccountReadService:
    return AmazonAccountReadService(db)
