"""Amazon product listing sync orchestration."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.database.session import SessionLocal
from app.integrations.amazon.exceptions import (
    AMAZON_LWA_TOKEN_INVALID,
    AMAZON_SP_API_FORBIDDEN,
    AMAZON_SP_API_UNAUTHORIZED,
    AMAZON_SYNC_FINALIZE_FAILED,
    AMAZON_SYNC_LEASE_LOST,
    AmazonError,
    amazon_account_disabled_error,
    amazon_account_not_active_error,
    amazon_account_not_found_error,
    amazon_marketplace_inactive_error,
    amazon_marketplace_not_eligible_error,
    amazon_marketplace_not_found_error,
    amazon_response_invalid_error,
    amazon_selling_partner_id_required_error,
    amazon_sync_finalize_failed_error,
    amazon_sync_lease_lost_error,
    amazon_sync_pagination_limit_error,
    amazon_sync_pagination_loop_error,
)
from app.integrations.amazon.listings_items import (
    ListingsItemsClient,
    SearchListingsItem,
    _validate_marketplace_id_for_client,
)
from app.integrations.amazon.token_encryption import TokenEncryptionService
from app.models.amazon_account import AmazonAccount, AmazonAccountStatus
from app.models.amazon_listing import AmazonListing
from app.models.amazon_marketplace_participation import AmazonMarketplaceParticipation
from app.models.amazon_sync_log import AmazonSyncOperation
from app.services.amazon_sync_lease_service import (
    AmazonSyncLeaseService,
    SyncLeaseContext,
    _utc_now,
)
from app.services.amazon_sync_log_service import AmazonSyncLogService

logger = logging.getLogger(__name__)

ListingsClientFactory = Callable[[str], ListingsItemsClient]

MAX_SYNC_PAGES = 500
MAX_SYNC_ITEMS = 10_000

REAUTHORIZATION_ERROR_CODES = frozenset(
    {
        AMAZON_LWA_TOKEN_INVALID,
        AMAZON_SP_API_UNAUTHORIZED,
        AMAZON_SP_API_FORBIDDEN,
    }
)


@dataclass(frozen=True)
class ProductSyncResult:
    account_id: uuid.UUID
    marketplace_id: str
    sync_log_id: uuid.UUID
    items_seen: int
    items_written: int
    items_deactivated: int
    pages_seen: int
    request_id: str | None


@dataclass(frozen=True)
class ProductSyncCredentials:
    user_id: uuid.UUID
    account_id: uuid.UUID
    account_key: str
    refresh_token_ciphertext: bytes
    refresh_token_key_version: int
    selling_partner_id: str


class AmazonProductSyncService:
    def __init__(
        self,
        *,
        session_factory: Callable[[], Session] | None = None,
        encryption_service: TokenEncryptionService,
        listings_client_factory: ListingsClientFactory,
        min_lease_seconds: int = 30,
        max_lease_seconds: int = 3600,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._session_factory = session_factory or SessionLocal
        self._encryption = encryption_service
        self._listings_client_factory = listings_client_factory
        self._min_lease_seconds = min_lease_seconds
        self._max_lease_seconds = max_lease_seconds
        self._clock = clock or _utc_now

    async def sync_product_listings(
        self,
        *,
        user_id: uuid.UUID,
        account_id: uuid.UUID,
        marketplace_id: str,
        lease_duration: timedelta | None = None,
    ) -> ProductSyncResult:
        normalized_marketplace_id = _validate_marketplace_id_for_client(marketplace_id)
        duration = lease_duration or timedelta(minutes=5)
        lease_ctx = self._preflight_and_acquire(
            user_id=user_id,
            account_id=account_id,
            marketplace_id=normalized_marketplace_id,
            lease_duration=duration,
        )

        last_request_id: str | None = None
        try:
            credentials = self._load_sync_credentials(
                user_id=user_id,
                lease_ctx=lease_ctx,
            )
            items, pages_seen, last_request_id = await self._fetch_all_listings(
                credentials=credentials,
                marketplace_id=normalized_marketplace_id,
            )
            return self._finalize_success(
                lease_ctx=lease_ctx,
                marketplace_id=normalized_marketplace_id,
                items=items,
                pages_seen=pages_seen,
                request_id=last_request_id,
            )
        except AmazonError as exc:
            self._handle_post_acquire_amazon_error(lease_ctx=lease_ctx, exc=exc)
            raise AssertionError("unreachable")  # pragma: no cover
        except Exception:
            self._handle_post_acquire_unexpected_error(
                lease_ctx=lease_ctx,
                request_id=last_request_id,
                category="unexpected",
            )
            raise AssertionError("unreachable")  # pragma: no cover

    def _handle_post_acquire_amazon_error(
        self,
        *,
        lease_ctx: SyncLeaseContext,
        exc: AmazonError,
    ) -> None:
        if exc.error_code == AMAZON_SYNC_LEASE_LOST:
            raise exc
        self._attempt_failure_finalize(
            lease_ctx=lease_ctx,
            error_code=exc.error_code,
            request_id=exc.request_id,
            account_status=self._account_status_for_error(exc),
        )
        raise exc

    def _handle_post_acquire_unexpected_error(
        self,
        *,
        lease_ctx: SyncLeaseContext,
        request_id: str | None,
        category: str,
    ) -> None:
        self._log_post_acquire_failure(lease_ctx=lease_ctx, category=category)
        self._attempt_failure_finalize(
            lease_ctx=lease_ctx,
            error_code=AMAZON_SYNC_FINALIZE_FAILED,
            request_id=request_id,
            account_status=AmazonAccountStatus.ERROR,
        )
        raise amazon_sync_finalize_failed_error() from None

    @staticmethod
    def _log_post_acquire_failure(
        *,
        lease_ctx: SyncLeaseContext,
        category: str,
    ) -> None:
        logger.warning(
            "Product sync post-acquire failure operation=product_sync category=%s "
            "account_id=%s sync_log_id=%s",
            category,
            lease_ctx.account_id,
            lease_ctx.sync_log_id,
        )

    def _preflight_and_acquire(
        self,
        *,
        user_id: uuid.UUID,
        account_id: uuid.UUID,
        marketplace_id: str,
        lease_duration: timedelta,
    ) -> SyncLeaseContext:
        db = self._session_factory()
        try:
            account = (
                db.query(AmazonAccount)
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
                raise amazon_account_disabled_error()
            if account.status != AmazonAccountStatus.ACTIVE:
                raise amazon_account_not_active_error()

            selling_partner_id = (account.selling_partner_id or "").strip()
            if not selling_partner_id:
                raise amazon_selling_partner_id_required_error()

            participation = (
                db.query(AmazonMarketplaceParticipation)
                .filter(
                    AmazonMarketplaceParticipation.amazon_account_id == account_id,
                    AmazonMarketplaceParticipation.marketplace_id == marketplace_id,
                )
                .with_for_update()
                .one_or_none()
            )
            if participation is None:
                raise amazon_marketplace_not_found_error()
            if not participation.is_active:
                raise amazon_marketplace_inactive_error()
            if not participation.sync_eligible:
                raise amazon_marketplace_not_eligible_error()

            lease_service = AmazonSyncLeaseService(
                db,
                min_lease_seconds=self._min_lease_seconds,
                max_lease_seconds=self._max_lease_seconds,
                clock=self._clock,
            )
            return lease_service.acquire(
                user_id=user_id,
                account_id=account_id,
                operation=AmazonSyncOperation.PRODUCT_SYNC,
                lease_duration=lease_duration,
            )
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _load_sync_credentials(
        self,
        *,
        user_id: uuid.UUID,
        lease_ctx: SyncLeaseContext,
    ) -> ProductSyncCredentials:
        now = self._clock()
        db = self._session_factory()
        try:
            account = (
                db.query(AmazonAccount)
                .filter(
                    AmazonAccount.id == lease_ctx.account_id,
                    AmazonAccount.user_id == user_id,
                    AmazonAccount.sync_lease_id == lease_ctx.lease_id,
                )
                .one_or_none()
            )
            if account is None:
                raise amazon_sync_lease_lost_error()
            if (
                account.sync_lease_expires_at is None
                or account.sync_lease_expires_at <= now
                or account.status == AmazonAccountStatus.DISABLED
            ):
                raise amazon_sync_lease_lost_error()

            selling_partner_id = (account.selling_partner_id or "").strip()
            if not selling_partner_id:
                raise amazon_selling_partner_id_required_error()

            credentials = ProductSyncCredentials(
                user_id=user_id,
                account_id=lease_ctx.account_id,
                account_key=account.account_key,
                refresh_token_ciphertext=account.refresh_token_ciphertext,
                refresh_token_key_version=account.refresh_token_key_version,
                selling_partner_id=selling_partner_id,
            )
            db.rollback()
            return credentials
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    async def _fetch_all_listings(
        self,
        *,
        credentials: ProductSyncCredentials,
        marketplace_id: str,
    ) -> tuple[tuple[SearchListingsItem, ...], int, str | None]:
        plaintext = self._encryption.decrypt_refresh_token(
            credentials.refresh_token_ciphertext,
            user_id=credentials.user_id,
            account_id=credentials.account_id,
            key_version=credentials.refresh_token_key_version,
        )
        try:
            client = self._listings_client_factory(plaintext)
            collected: list[SearchListingsItem] = []
            seen_identities: set[tuple[str, str]] = set()
            seen_page_tokens: set[str] = set()
            page_token: str | None = None
            pages_seen = 0
            last_request_id: str | None = None

            while True:
                if pages_seen >= MAX_SYNC_PAGES:
                    raise amazon_sync_pagination_limit_error()
                if len(collected) >= MAX_SYNC_ITEMS:
                    raise amazon_sync_pagination_limit_error()

                page = await client.search_listings_items(
                    seller_id=credentials.selling_partner_id,
                    marketplace_id=marketplace_id,
                    account_key=credentials.account_key,
                    page_token=page_token,
                )
                pages_seen += 1
                if page.request_id is not None:
                    last_request_id = page.request_id

                for item in page.items:
                    identity = (item.marketplace_id, item.seller_sku)
                    if identity in seen_identities:
                        raise amazon_response_invalid_error()
                    seen_identities.add(identity)
                    collected.append(item)
                    if len(collected) > MAX_SYNC_ITEMS:
                        raise amazon_sync_pagination_limit_error()

                next_token = page.next_page_token
                if next_token is None:
                    break
                if next_token in seen_page_tokens or (
                    page_token is not None and next_token == page_token
                ):
                    raise amazon_sync_pagination_loop_error()
                seen_page_tokens.add(next_token)
                page_token = next_token

            return tuple(collected), pages_seen, last_request_id
        finally:
            del plaintext

    def _finalize_success(
        self,
        *,
        lease_ctx: SyncLeaseContext,
        marketplace_id: str,
        items: tuple[SearchListingsItem, ...],
        pages_seen: int,
        request_id: str | None,
    ) -> ProductSyncResult:
        now = self._clock()
        sync_run_id = lease_ctx.sync_log_id
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
                account.status != AmazonAccountStatus.ACTIVE
                or account.sync_lease_id != lease_ctx.lease_id
                or account.sync_lease_expires_at is None
                or account.sync_lease_expires_at <= now
            ):
                raise amazon_sync_lease_lost_error()

            participation = (
                db.query(AmazonMarketplaceParticipation)
                .filter(
                    AmazonMarketplaceParticipation.amazon_account_id == lease_ctx.account_id,
                    AmazonMarketplaceParticipation.marketplace_id == marketplace_id,
                )
                .with_for_update()
                .one_or_none()
            )
            self._assert_participation_eligible_for_sync(participation)

            if items:
                self._upsert_listings(
                    db,
                    account_id=lease_ctx.account_id,
                    marketplace_id=marketplace_id,
                    items=items,
                    sync_run_id=sync_run_id,
                    now=now,
                )

            items_deactivated = self._soft_deactivate_unseen(
                db,
                account_id=lease_ctx.account_id,
                marketplace_id=marketplace_id,
                sync_run_id=sync_run_id,
                now=now,
            )

            AmazonSyncLogService.finalize_succeeded(
                db,
                account_id=lease_ctx.account_id,
                sync_log_id=lease_ctx.sync_log_id,
                items_seen=len(items),
                items_written=len(items),
                items_deactivated=items_deactivated,
                request_id=request_id,
                safe_detail={"pages_seen": pages_seen},
                finished_at=now,
            )
            lease_service.clear_lease_if_owner(
                account_id=lease_ctx.account_id,
                lease_id=lease_ctx.lease_id,
            )
            db.commit()
            return ProductSyncResult(
                account_id=lease_ctx.account_id,
                marketplace_id=marketplace_id,
                sync_log_id=lease_ctx.sync_log_id,
                items_seen=len(items),
                items_written=len(items),
                items_deactivated=items_deactivated,
                pages_seen=pages_seen,
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

    @staticmethod
    def _assert_participation_eligible_for_sync(
        participation: AmazonMarketplaceParticipation | None,
    ) -> None:
        if participation is None:
            raise amazon_marketplace_not_found_error()
        if not participation.is_active:
            raise amazon_marketplace_inactive_error()
        if not participation.sync_eligible:
            raise amazon_marketplace_not_eligible_error()

    @staticmethod
    def _upsert_listings(
        db: Session,
        *,
        account_id: uuid.UUID,
        marketplace_id: str,
        items: tuple[SearchListingsItem, ...],
        sync_run_id: uuid.UUID,
        now: datetime,
    ) -> None:
        rows: list[dict[str, Any]] = []
        for item in items:
            rows.append(
                {
                    "id": uuid.uuid4(),
                    "amazon_account_id": account_id,
                    "marketplace_id": marketplace_id,
                    "seller_sku": item.seller_sku,
                    "asin": item.asin,
                    "status_codes": list(item.status_codes),
                    "product_type": item.product_type,
                    "upstream_created_at": item.upstream_created_at,
                    "upstream_last_updated_at": item.upstream_last_updated_at,
                    "is_active": True,
                    "last_seen_sync_id": sync_run_id,
                    "first_seen_at": now,
                    "last_seen_at": now,
                    "created_at": now,
                    "updated_at": now,
                }
            )

        insert_stmt = pg_insert(AmazonListing.__table__).values(rows)
        excluded = insert_stmt.excluded
        upsert_stmt = insert_stmt.on_conflict_do_update(
            constraint="uq_amazon_listings_account_marketplace_sku",
            set_={
                "asin": excluded.asin,
                "status_codes": excluded.status_codes,
                "product_type": excluded.product_type,
                "upstream_created_at": excluded.upstream_created_at,
                "upstream_last_updated_at": excluded.upstream_last_updated_at,
                "is_active": excluded.is_active,
                "last_seen_sync_id": excluded.last_seen_sync_id,
                "last_seen_at": excluded.last_seen_at,
                "updated_at": excluded.updated_at,
            },
        )
        db.execute(upsert_stmt)

    @staticmethod
    def _soft_deactivate_unseen(
        db: Session,
        *,
        account_id: uuid.UUID,
        marketplace_id: str,
        sync_run_id: uuid.UUID,
        now: datetime,
    ) -> int:
        result = db.execute(
            update(AmazonListing)
            .where(
                AmazonListing.amazon_account_id == account_id,
                AmazonListing.marketplace_id == marketplace_id,
                AmazonListing.is_active.is_(True),
                AmazonListing.last_seen_sync_id.is_distinct_from(sync_run_id),
            )
            .values(is_active=False, updated_at=now)
            .returning(AmazonListing.id)
        )
        return len(result.fetchall())

    @staticmethod
    def _account_status_for_error(exc: AmazonError) -> str | None:
        if exc.error_code in REAUTHORIZATION_ERROR_CODES:
            return AmazonAccountStatus.REAUTHORIZATION_REQUIRED
        return None

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
            logger.warning(
                "Product sync failure finalize rejected operation=product_sync category=finalize "
                "account_id=%s sync_log_id=%s",
                lease_ctx.account_id,
                lease_ctx.sync_log_id,
            )
            return False
        except Exception:
            db.rollback()
            logger.warning(
                "Product sync failure finalize failed operation=product_sync category=finalize "
                "account_id=%s sync_log_id=%s",
                lease_ctx.account_id,
                lease_ctx.sync_log_id,
            )
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
