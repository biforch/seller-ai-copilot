"""Administrative user-account deletion with Amazon cleanup and audit logging."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.integrations.amazon.token_encryption import TokenEncryptionService
from app.models.amazon_account import AmazonAccount
from app.models.user import User
from app.services.amazon_account_service import AmazonAccountService

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class UserAccountDeletionResult:
    user_id: uuid.UUID | None
    already_deleted: bool
    amazon_accounts_removed: int
    deleted_at: datetime | None
    request_reference: str | None


class UserAccountDeletionService:
    def __init__(self, db: Session, token_encryption: TokenEncryptionService) -> None:
        self._db = db
        self._amazon_accounts = AmazonAccountService(db, token_encryption)

    def delete_user_account(
        self,
        *,
        user_id: uuid.UUID,
        request_reference: str | None = None,
        dry_run: bool = False,
    ) -> UserAccountDeletionResult:
        user = (
            self._db.query(User)
            .filter(User.id == user_id)
            .with_for_update()
            .one_or_none()
        )
        if user is None:
            return UserAccountDeletionResult(
                user_id=user_id,
                already_deleted=True,
                amazon_accounts_removed=0,
                deleted_at=None,
                request_reference=request_reference,
            )

        account_ids = [
            row[0]
            for row in self._db.query(AmazonAccount.id)
            .filter(AmazonAccount.user_id == user_id)
            .all()
        ]

        if dry_run:
            return UserAccountDeletionResult(
                user_id=user_id,
                already_deleted=False,
                amazon_accounts_removed=len(account_ids),
                deleted_at=None,
                request_reference=request_reference,
            )

        for account_id in account_ids:
            self._amazon_accounts.disconnect_account(user_id=user_id, account_id=account_id)

        self._db.delete(user)
        self._db.commit()
        deleted_at = datetime.now(UTC)
        logger.info(
            "user_account_deleted user_id=%s amazon_accounts_removed=%s request_reference=%s",
            user_id,
            len(account_ids),
            request_reference or "unspecified",
        )
        return UserAccountDeletionResult(
            user_id=user_id,
            already_deleted=False,
            amazon_accounts_removed=len(account_ids),
            deleted_at=deleted_at,
            request_reference=request_reference,
        )

    def delete_user_by_email(
        self,
        *,
        email: str,
        request_reference: str | None = None,
        dry_run: bool = False,
    ) -> UserAccountDeletionResult:
        normalized = email.strip().lower()
        user = self._db.query(User).filter(User.email == normalized).one_or_none()
        if user is None:
            return UserAccountDeletionResult(
                user_id=None,
                already_deleted=True,
                amazon_accounts_removed=0,
                deleted_at=None,
                request_reference=request_reference,
            )
        return self.delete_user_account(
            user_id=user.id,
            request_reference=request_reference,
            dry_run=dry_run,
        )
