"""Tenant-scoped read-only Amazon account access."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.integrations.amazon.exceptions import amazon_account_not_found_error
from app.models.amazon_account import AmazonAccount


@dataclass(frozen=True)
class AmazonAccountSummary:
    id: uuid.UUID
    user_id: uuid.UUID
    region: str
    endpoint_mode: str
    status: str
    last_verified_at: datetime | None
    created_at: datetime
    updated_at: datetime


def to_account_summary(account: AmazonAccount) -> AmazonAccountSummary:
    return AmazonAccountSummary(
        id=account.id,
        user_id=account.user_id,
        region=account.region,
        endpoint_mode=account.endpoint_mode,
        status=account.status,
        last_verified_at=account.last_verified_at,
        created_at=account.created_at,
        updated_at=account.updated_at,
    )


class AmazonAccountReadService:
    """Read-only, tenant-scoped Amazon account queries (no token/crypto dependencies)."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def _get_account_row_for_user(
        self,
        *,
        user_id: uuid.UUID,
        account_id: uuid.UUID,
    ) -> AmazonAccount | None:
        return (
            self._db.query(AmazonAccount)
            .filter(
                AmazonAccount.id == account_id,
                AmazonAccount.user_id == user_id,
            )
            .one_or_none()
        )

    def get_account_for_user(
        self,
        *,
        user_id: uuid.UUID,
        account_id: uuid.UUID,
    ) -> AmazonAccountSummary:
        account = self._get_account_row_for_user(user_id=user_id, account_id=account_id)
        if account is None:
            raise amazon_account_not_found_error()
        return to_account_summary(account)

    def list_accounts_for_user(self, *, user_id: uuid.UUID) -> list[AmazonAccountSummary]:
        accounts = (
            self._db.query(AmazonAccount)
            .filter(AmazonAccount.user_id == user_id)
            .order_by(AmazonAccount.updated_at.desc(), AmazonAccount.id.desc())
            .all()
        )
        return [to_account_summary(account) for account in accounts]
