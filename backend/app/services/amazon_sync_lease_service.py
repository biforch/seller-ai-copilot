"""Database-backed sync lease acquisition and ownership."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, or_, update
from sqlalchemy.orm import Session

from app.integrations.amazon.exceptions import (
    AMAZON_SYNC_LEASE_EXPIRED,
    amazon_account_disabled_error,
    amazon_account_not_found_error,
    amazon_config_invalid_error,
    amazon_sync_in_progress_error,
    amazon_sync_lease_lost_error,
)
from app.models.amazon_account import AmazonAccount, AmazonAccountStatus
from app.models.amazon_sync_log import AmazonSyncLog, AmazonSyncOperation, AmazonSyncStatus
from app.services.amazon_sync_log_service import AmazonSyncLogService

DEFAULT_MIN_LEASE_SECONDS = 30
DEFAULT_MAX_LEASE_SECONDS = 3600


@dataclass(frozen=True)
class SyncLeaseContext:
    account_id: uuid.UUID
    user_id: uuid.UUID
    lease_id: uuid.UUID
    sync_log_id: uuid.UUID
    expires_at: datetime
    operation: str


Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(UTC)


class AmazonSyncLeaseService:
    def __init__(
        self,
        db: Session,
        *,
        min_lease_seconds: int = DEFAULT_MIN_LEASE_SECONDS,
        max_lease_seconds: int = DEFAULT_MAX_LEASE_SECONDS,
        clock: Clock | None = None,
    ) -> None:
        self._db = db
        self._min_lease_seconds = min_lease_seconds
        self._max_lease_seconds = max_lease_seconds
        self._clock = clock or _utc_now

    def _now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None:
            return now.replace(tzinfo=UTC)
        return now

    @staticmethod
    def _valid_owner_conditions(
        *,
        account_id: uuid.UUID,
        lease_id: uuid.UUID,
        now: datetime,
    ):
        return and_(
            AmazonAccount.id == account_id,
            AmazonAccount.sync_lease_id == lease_id,
            AmazonAccount.sync_lease_expires_at.isnot(None),
            AmazonAccount.sync_lease_expires_at > now,
            AmazonAccount.status != AmazonAccountStatus.DISABLED,
        )

    def _validate_duration(self, lease_duration: timedelta) -> None:
        seconds = lease_duration.total_seconds()
        if seconds < self._min_lease_seconds or seconds > self._max_lease_seconds:
            raise amazon_config_invalid_error("Lease duration is invalid")

    def acquire(
        self,
        *,
        user_id: uuid.UUID,
        account_id: uuid.UUID,
        operation: str,
        lease_duration: timedelta,
    ) -> SyncLeaseContext:
        if operation not in AmazonSyncOperation.ALL:
            raise amazon_config_invalid_error("Sync operation is invalid")
        self._validate_duration(lease_duration)

        now = self._now()
        lease_id = uuid.uuid4()
        expires_at = now + lease_duration

        updated = (
            self._db.execute(
                update(AmazonAccount)
                .where(
                    AmazonAccount.id == account_id,
                    AmazonAccount.user_id == user_id,
                    AmazonAccount.status != AmazonAccountStatus.DISABLED,
                    or_(
                        AmazonAccount.sync_lease_id.is_(None),
                        AmazonAccount.sync_lease_expires_at.is_(None),
                        AmazonAccount.sync_lease_expires_at <= now,
                    ),
                )
                .values(sync_lease_id=lease_id, sync_lease_expires_at=expires_at)
                .returning(AmazonAccount.id)
            )
            .scalar_one_or_none()
        )

        if updated is None:
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
            if account.status == AmazonAccountStatus.DISABLED:
                raise amazon_account_disabled_error()
            if (
                account.sync_lease_id is not None
                and account.sync_lease_expires_at is not None
                and account.sync_lease_expires_at > now
            ):
                raise amazon_sync_in_progress_error()
            raise amazon_account_not_found_error()

        stale_logs = (
            self._db.query(AmazonSyncLog)
            .filter(
                AmazonSyncLog.amazon_account_id == account_id,
                AmazonSyncLog.status == AmazonSyncStatus.PROCESSING,
            )
            .with_for_update()
            .all()
        )
        for stale_log in stale_logs:
            AmazonSyncLogService.finalize_failed(
                self._db,
                account_id=account_id,
                sync_log_id=stale_log.id,
                error_code=AMAZON_SYNC_LEASE_EXPIRED,
                finished_at=now,
            )

        sync_log = AmazonSyncLog(
            amazon_account_id=account_id,
            operation=operation,
            status=AmazonSyncStatus.PROCESSING,
            started_at=now,
        )
        self._db.add(sync_log)
        try:
            self._db.flush()
            self._db.commit()
        except Exception:
            self._db.rollback()
            raise
        self._db.refresh(sync_log)

        return SyncLeaseContext(
            account_id=account_id,
            user_id=user_id,
            lease_id=lease_id,
            sync_log_id=sync_log.id,
            expires_at=expires_at,
            operation=operation,
        )

    def assert_lease_owner(
        self,
        *,
        account_id: uuid.UUID,
        lease_id: uuid.UUID,
    ) -> None:
        now = self._now()
        owned = (
            self._db.query(AmazonAccount.id)
            .filter(self._valid_owner_conditions(account_id=account_id, lease_id=lease_id, now=now))
            .one_or_none()
        )
        if owned is None:
            raise amazon_sync_lease_lost_error()

    def clear_lease_if_owner(
        self,
        *,
        account_id: uuid.UUID,
        lease_id: uuid.UUID,
    ) -> None:
        now = self._now()
        cleared = (
            self._db.execute(
                update(AmazonAccount)
                .where(self._valid_owner_conditions(account_id=account_id, lease_id=lease_id, now=now))
                .values(sync_lease_id=None, sync_lease_expires_at=None)
                .returning(AmazonAccount.id)
            )
            .scalar_one_or_none()
        )
        if cleared is None:
            raise amazon_sync_lease_lost_error()
