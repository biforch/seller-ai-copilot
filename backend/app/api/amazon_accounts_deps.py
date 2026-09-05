"""FastAPI dependencies for tenant-scoped Amazon account reads and mutations."""

from __future__ import annotations

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.config import settings
from app.database.session import get_db
from app.integrations.amazon.token_encryption_loader import build_token_encryption_service
from app.services.amazon_account_read_service import AmazonAccountReadService
from app.services.amazon_account_service import AmazonAccountService


def get_amazon_account_read_service(
    db: Session = Depends(get_db),
) -> AmazonAccountReadService:
    return AmazonAccountReadService(db)


def get_amazon_account_service(
    db: Session = Depends(get_db),
) -> AmazonAccountService:
    return AmazonAccountService(db, build_token_encryption_service(settings))
