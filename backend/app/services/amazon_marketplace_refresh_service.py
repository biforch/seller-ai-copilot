"""Marketplace participation refresh orchestration."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.database.session import SessionLocal
from app.integrations.amazon.exceptions import (
    AMAZON_LWA_TOKEN_INVALID,
    AMAZON_SP_API_FORBIDDEN,
    AMAZON_SP_API_UNAUTHORIZED,
    AMAZON_SYNC_FINALIZE_FAILED,
    AMAZON_SYNC_LEASE_LOST,
    AmazonError,
    amazon_response_invalid_error,
    amazon_sync_finalize_failed_error,
    amazon_sync_lease_lost_error,
)
from app.integrations.amazon.sellers import SellerMarketplaceParticipation, SellersClient
from app.integrations.amazon.token_encryption import TokenEncryptionService
from app.models.amazon_account import AmazonAccount, AmazonAccountStatus
from app.models.amazon_marketplace_participation import AmazonMarketplaceParticipation
from app.models.amazon_sync_log import AmazonSyncOperation
from app.services.amazon_sync_lease_service import (
    AmazonSyncLeaseService,
    SyncLeaseContext,
    _utc_now,
)
from app.services.amazon_sync_log_service import AmazonSyncLogService

logger = logging.getLogger(__name__)

SellersClientFactory = Callable[[str], SellersClient]

REAUTHORIZATION_ERROR_CODES = frozenset(
    {
        AMAZON_LWA_TOKEN_INVALID,
        AMAZON_SP_API_UNAUTHORIZED,
        AMAZON_SP_API_FORBIDDEN,
    }
)


@dataclass(frozen=True)
class MarketplaceRefreshResult:
    account_id: uuid.UUID
    sync_log_id: uuid.UUID
    items_seen: int
    items_written: int
    items_deactivated: int
    request_id: str | None


@dataclass(frozen=True)
class EncryptedAccountToken:
    account_key: str
    refresh_token_ciphertext: bytes
    refresh_token_key_version: int


class AmazonMarketplaceRefreshService:
    def __init__(
        self,
        *,
        session_factory: Callable[[], Session] | None = None,
        encryption_service: TokenEncryptionService,
        sellers_client_factory: SellersClientFactory,
        min_lease_seconds: int = 30,
        max_lease_seconds: int = 3600,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._session_factory = session_factory or SessionLocal
        self._encryption = encryption_service
        self._sellers_client_factory = sellers_client_factory
        self._min_lease_seconds = min_lease_seconds
        self._max_lease_seconds = max_lease_seconds
        self._clock = clock or _utc_now

    async def refresh_marketplace_participations(
        self,
        *,
        user_id: uuid.UUID,
        account_id: uuid.UUID,
        lease_duration: timedelta | None = None,
    ) -> MarketplaceRefreshResult:
        duration = lease_duration or timedelta(minutes=5)
        lease_ctx = self._acquire_lease(
            user_id=user_id,
            account_id=account_id,
            lease_duration=duration,
        )

        stage = "credential_load"
        request_id: str | None = None
        try:
            encrypted = self._load_encrypted_token(user_id=user_id, account_id=account_id)
            stage = "external_fetch"
            participations, request_id = await self._fetch_participations(
                encrypted=encrypted,
                user_id=user_id,
                account_id=account_id,
            )
            stage = "finalize_success"
            return self._finalize_success(
                lease_ctx=lease_ctx,
                participations=participations,
                request_id=request_id,
            )
        except AmazonError as exc:
            if exc.error_code == AMAZON_SYNC_LEASE_LOST:
                raise
            self._attempt_failure_finalize(
                lease_ctx=lease_ctx,
                error_code=exc.error_code,
                request_id=exc.request_id,
                account_status=self._account_status_for_error(exc),
            )
            raise
        except Exception:
            logger.warning(
                "Marketplace refresh failed operation=marketplace_refresh "
                "category=%s account_id=%s sync_log_id=%s",
                stage,
                account_id,
                lease_ctx.sync_log_id,
            )
            self._attempt_failure_finalize(
                lease_ctx=lease_ctx,
                error_code=AMAZON_SYNC_FINALIZE_FAILED,
                request_id=request_id,
                account_status=AmazonAccountStatus.ERROR,
            )
            raise amazon_sync_finalize_failed_error() from None

    def _acquire_lease(
        self,
        *,
        user_id: uuid.UUID,
        account_id: uuid.UUID,
        lease_duration: timedelta,
    ) -> SyncLeaseContext:
        db = self._session_factory()
        try:
            lease_service = AmazonSyncLeaseService(
                db,
                min_lease_seconds=self._min_lease_seconds,
                max_lease_seconds=self._max_lease_seconds,
                clock=self._clock,
            )
            return lease_service.acquire(
                user_id=user_id,
                account_id=account_id,
                operation=AmazonSyncOperation.MARKETPLACE_REFRESH,
                lease_duration=lease_duration,
            )
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _load_encrypted_token(
        self,
        *,
        user_id: uuid.UUID,
        account_id: uuid.UUID,
    ) -> EncryptedAccountToken:
        db = self._session_factory()
        try:
            account = (
                db.query(AmazonAccount)
                .filter(
                    AmazonAccount.id == account_id,
                    AmazonAccount.user_id == user_id,
                )
                .one_or_none()
            )
            if account is None:
                raise amazon_sync_lease_lost_error()
            token = EncryptedAccountToken(
                account_key=account.account_key,
                refresh_token_ciphertext=account.refresh_token_ciphertext,
                refresh_token_key_version=account.refresh_token_key_version,
            )
            db.rollback()
            return token
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    async def _fetch_participations(
        self,
        *,
        encrypted: EncryptedAccountToken,
        user_id: uuid.UUID,
        account_id: uuid.UUID,
    ) -> tuple[tuple[SellerMarketplaceParticipation, ...], str | None]:
        plaintext = self._encryption.decrypt_refresh_token(
            encrypted.refresh_token_ciphertext,
            user_id=user_id,
            account_id=account_id,
            key_version=encrypted.refresh_token_key_version,
        )
        try:
            sellers_client = self._sellers_client_factory(plaintext)
            participations = await sellers_client.get_marketplace_participations(
                account_key=encrypted.account_key,
            )
        finally:
            del plaintext
        self._ensure_unique_marketplace_ids(participations)
        return participations, None

    @staticmethod
    def _ensure_unique_marketplace_ids(
        participations: tuple[SellerMarketplaceParticipation, ...],
    ) -> None:
        seen: set[str] = set()
        for participation in participations:
            if participation.marketplace_id in seen:
                raise amazon_response_invalid_error()
            seen.add(participation.marketplace_id)

    def _finalize_success(
        self,
        *,
        lease_ctx: SyncLeaseContext,
        participations: tuple[SellerMarketplaceParticipation, ...],
        request_id: str | None,
    ) -> MarketplaceRefreshResult:
        now = self._clock()
        db = self._session_factory()
        try:
            lease_service = AmazonSyncLeaseService(db, clock=self._clock)
            lease_service.assert_lease_owner(
                account_id=lease_ctx.account_id,
                lease_id=lease_ctx.lease_id,
            )

            account = (
                db.query(AmazonAccount)
                .filter(AmazonAccount.id == lease_ctx.account_id)
                .with_for_update()
                .one()
            )
            if (
                account.status == AmazonAccountStatus.DISABLED
                or account.sync_lease_id != lease_ctx.lease_id
                or account.sync_lease_expires_at is None
                or account.sync_lease_expires_at <= now
            ):
                raise amazon_sync_lease_lost_error()

            items_seen, items_written, items_deactivated = self._upsert_participations(
                db,
                account_id=lease_ctx.account_id,
                participations=participations,
                now=now,
            )

            if account.status != AmazonAccountStatus.DISABLED:
                account.status = AmazonAccountStatus.ACTIVE
                account.last_verified_at = now
                db.add(account)

            AmazonSyncLogService.finalize_succeeded(
                db,
                account_id=lease_ctx.account_id,
                sync_log_id=lease_ctx.sync_log_id,
                items_seen=items_seen,
                items_written=items_written,
                items_deactivated=items_deactivated,
                request_id=request_id,
                safe_detail={
                    "participation_count": items_seen,
                    "active_count": items_seen,
                    "deactivated_count": items_deactivated,
                },
                finished_at=now,
            )
            lease_service.clear_lease_if_owner(
                account_id=lease_ctx.account_id,
                lease_id=lease_ctx.lease_id,
            )
            db.commit()
            return MarketplaceRefreshResult(
                account_id=lease_ctx.account_id,
                sync_log_id=lease_ctx.sync_log_id,
                items_seen=items_seen,
                items_written=items_written,
                items_deactivated=items_deactivated,
                request_id=request_id,
            )
        except AmazonError:
            db.rollback()
            raise
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _upsert_participations(
        self,
        db: Session,
        *,
        account_id: uuid.UUID,
        participations: tuple[SellerMarketplaceParticipation, ...],
        now: datetime,
    ) -> tuple[int, int, int]:
        existing_rows = (
            db.query(AmazonMarketplaceParticipation)
            .filter(AmazonMarketplaceParticipation.amazon_account_id == account_id)
            .all()
        )
        existing_by_marketplace = {row.marketplace_id: row for row in existing_rows}
        seen_ids: set[str] = set()
        items_written = 0

        for participation in participations:
            if participation.marketplace_id in seen_ids:
                raise amazon_response_invalid_error()
            seen_ids.add(participation.marketplace_id)

            row = existing_by_marketplace.get(participation.marketplace_id)
            if row is None:
                row = AmazonMarketplaceParticipation(
                    amazon_account_id=account_id,
                    marketplace_id=participation.marketplace_id,
                    marketplace_name=participation.name,
                    country_code=participation.country_code,
                    default_currency_code=participation.default_currency_code,
                    default_language_code=participation.default_language_code,
                    domain_name=participation.domain_name,
                    participating=participation.participating,
                    suspended_listings=participation.suspended_listings,
                    is_active=True,
                    last_seen_at=now,
                )
                db.add(row)
                items_written += 1
            else:
                row.marketplace_name = participation.name
                row.country_code = participation.country_code
                row.default_currency_code = participation.default_currency_code
                row.default_language_code = participation.default_language_code
                row.domain_name = participation.domain_name
                row.participating = participation.participating
                row.suspended_listings = participation.suspended_listings
                row.is_active = True
                row.last_seen_at = now
                db.add(row)
                items_written += 1

        items_deactivated = 0
        for marketplace_id, row in existing_by_marketplace.items():
            if marketplace_id not in seen_ids and row.is_active:
                row.is_active = False
                db.add(row)
                items_deactivated += 1

        return len(participations), items_written, items_deactivated

    def _account_status_for_error(self, exc: AmazonError) -> str | None:
        if exc.error_code in REAUTHORIZATION_ERROR_CODES:
            return AmazonAccountStatus.REAUTHORIZATION_REQUIRED
        return AmazonAccountStatus.ERROR

    def _attempt_failure_finalize(
        self,
        *,
        lease_ctx: SyncLeaseContext,
        error_code: str,
        request_id: str | None,
        account_status: str | None,
    ) -> bool:
        db = self._session_factory()
        try:
            self._apply_failure_finalize(
                db,
                lease_ctx=lease_ctx,
                error_code=error_code,
                request_id=request_id,
                account_status=account_status,
            )
            db.commit()
            return True
        except AmazonError as exc:
            db.rollback()
            if exc.error_code == AMAZON_SYNC_LEASE_LOST:
                return False
            return False
        except Exception:
            db.rollback()
            return False
        finally:
            db.close()

    def _apply_failure_finalize(
        self,
        db: Session,
        *,
        lease_ctx: SyncLeaseContext,
        error_code: str,
        request_id: str | None,
        account_status: str | None,
    ) -> None:
        now = self._clock()
        lease_service = AmazonSyncLeaseService(db, clock=self._clock)
        lease_service.assert_lease_owner(
            account_id=lease_ctx.account_id,
            lease_id=lease_ctx.lease_id,
        )

        account = (
            db.query(AmazonAccount)
            .filter(AmazonAccount.id == lease_ctx.account_id)
            .with_for_update()
            .one()
        )
        if account.status != AmazonAccountStatus.DISABLED and account_status is not None:
            account.status = account_status
            db.add(account)

        AmazonSyncLogService.finalize_failed(
            db,
            account_id=lease_ctx.account_id,
            sync_log_id=lease_ctx.sync_log_id,
            error_code=error_code,
            request_id=request_id,
            finished_at=now,
        )
        lease_service.clear_lease_if_owner(
            account_id=lease_ctx.account_id,
            lease_id=lease_ctx.lease_id,
        )
