"""Amazon account persistence and tenant-scoped access."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.integrations.amazon.exceptions import (
    AMAZON_ACCOUNT_DISABLED,
    amazon_account_already_exists_error,
    amazon_account_not_found_error,
    amazon_config_invalid_error,
)
from app.integrations.amazon.token_encryption import TokenEncryptionService
from app.models.amazon_account import AmazonAccount, AmazonAccountStatus
from app.models.amazon_sync_log import AmazonSyncLog, AmazonSyncStatus
from app.services.amazon_sync_log_service import AmazonSyncLogService

VALID_REGIONS = frozenset({"na", "eu", "fe"})
VALID_ENDPOINT_MODES = frozenset({"sandbox", "production"})
FINGERPRINT_UNIQUE_CONSTRAINT = "uq_amazon_accounts_user_fingerprint"


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


def _to_summary(account: AmazonAccount) -> AmazonAccountSummary:
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


def _is_fingerprint_unique_violation(exc: IntegrityError) -> bool:
    orig = exc.orig
    if orig is None:
        return FINGERPRINT_UNIQUE_CONSTRAINT in str(exc)
    diag = getattr(orig, "diag", None)
    constraint_name = getattr(diag, "constraint_name", None) if diag is not None else None
    if constraint_name == FINGERPRINT_UNIQUE_CONSTRAINT:
        return True
    return FINGERPRINT_UNIQUE_CONSTRAINT in str(orig)


class AmazonAccountService:
    def __init__(
        self,
        db: Session,
        encryption_service: TokenEncryptionService,
    ) -> None:
        self._db = db
        self._encryption = encryption_service

    @staticmethod
    def _validate_region_endpoint(*, region: str, endpoint_mode: str) -> None:
        if region not in VALID_REGIONS or endpoint_mode not in VALID_ENDPOINT_MODES:
            raise amazon_config_invalid_error("Amazon account region or endpoint mode is invalid")

    def create_account(
        self,
        *,
        user_id: uuid.UUID,
        region: str,
        endpoint_mode: str,
        plaintext_refresh_token: str,
    ) -> AmazonAccountSummary:
        self._validate_region_endpoint(region=region, endpoint_mode=endpoint_mode)
        if not plaintext_refresh_token.strip():
            raise amazon_config_invalid_error("Refresh token is required")

        account_id = uuid.uuid4()
        fingerprint = self._encryption.fingerprint_refresh_token(plaintext_refresh_token)
        ciphertext, key_version = self._encryption.encrypt_refresh_token(
            plaintext_refresh_token,
            user_id=user_id,
            account_id=account_id,
        )

        account = AmazonAccount(
            id=account_id,
            user_id=user_id,
            region=region,
            endpoint_mode=endpoint_mode,
            status=AmazonAccountStatus.ACTIVE,
            refresh_token_ciphertext=ciphertext,
            refresh_token_key_version=key_version,
            refresh_token_fingerprint=fingerprint,
        )
        self._db.add(account)
        try:
            self._db.commit()
        except IntegrityError as exc:
            self._db.rollback()
            if _is_fingerprint_unique_violation(exc):
                raise amazon_account_already_exists_error() from None
            raise
        self._db.refresh(account)
        return _to_summary(account)

    def get_account_for_user(
        self,
        *,
        user_id: uuid.UUID,
        account_id: uuid.UUID,
    ) -> AmazonAccountSummary:
        account = (
            self._db.query(AmazonAccount)
            .filter(
                AmazonAccount.id == account_id,
                AmazonAccount.user_id == user_id,
            )
            .one_or_none()
        )
        if account is None:
            raise amazon_account_not_found_error()
        return _to_summary(account)

    def get_account_model_for_user(
        self,
        *,
        user_id: uuid.UUID,
        account_id: uuid.UUID,
    ) -> AmazonAccount:
        account = (
            self._db.query(AmazonAccount)
            .filter(
                AmazonAccount.id == account_id,
                AmazonAccount.user_id == user_id,
            )
            .one_or_none()
        )
        if account is None:
            raise amazon_account_not_found_error()
        return account

    def list_accounts_for_user(self, *, user_id: uuid.UUID) -> list[AmazonAccountSummary]:
        accounts = (
            self._db.query(AmazonAccount)
            .filter(AmazonAccount.user_id == user_id)
            .order_by(AmazonAccount.updated_at.desc(), AmazonAccount.id.desc())
            .all()
        )
        return [_to_summary(account) for account in accounts]

    def disable_account(
        self,
        *,
        user_id: uuid.UUID,
        account_id: uuid.UUID,
    ) -> AmazonAccountSummary:
        account = (
            self._db.query(AmazonAccount)
            .filter(
                AmazonAccount.id == account_id,
                AmazonAccount.user_id == user_id,
            )
            .with_for_update()
            .one_or_none()
        )
        if account is None:
            raise amazon_account_not_found_error()

        if account.status == AmazonAccountStatus.DISABLED:
            return _to_summary(account)

        now = datetime.now(UTC)
        processing_logs = (
            self._db.query(AmazonSyncLog)
            .filter(
                AmazonSyncLog.amazon_account_id == account_id,
                AmazonSyncLog.status == AmazonSyncStatus.PROCESSING,
            )
            .with_for_update()
            .all()
        )
        for sync_log in processing_logs:
            AmazonSyncLogService.finalize_failed(
                self._db,
                account_id=account_id,
                sync_log_id=sync_log.id,
                error_code=AMAZON_ACCOUNT_DISABLED,
                finished_at=now,
            )

        account.status = AmazonAccountStatus.DISABLED
        account.sync_lease_id = None
        account.sync_lease_expires_at = None
        self._db.add(account)
        self._db.commit()
        self._db.refresh(account)
        return _to_summary(account)
