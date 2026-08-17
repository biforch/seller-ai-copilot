"""Tenant-safe, TTL-aware Amazon catalog enrichment orchestration."""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.database.session import SessionLocal
from app.integrations.amazon.catalog_items import CatalogItemsClient, CatalogItemSummary
from app.integrations.amazon.exceptions import (
    AmazonError,
    amazon_account_disabled_error,
    amazon_account_not_active_error,
    amazon_account_not_found_error,
    amazon_catalog_asin_required_error,
    amazon_catalog_fetch_failed_error,
    amazon_catalog_identity_changed_error,
    amazon_catalog_persist_failed_error,
    amazon_listing_not_found_error,
    amazon_marketplace_inactive_error,
    amazon_marketplace_not_found_error,
)
from app.integrations.amazon.token_encryption import TokenEncryptionService
from app.models.amazon_account import AmazonAccount, AmazonAccountStatus
from app.models.amazon_catalog_snapshot import AmazonCatalogSnapshot
from app.models.amazon_listing import AmazonListing
from app.models.amazon_marketplace_participation import AmazonMarketplaceParticipation

logger = logging.getLogger(__name__)

CatalogClientFactory = Callable[[str], CatalogItemsClient]
DEFAULT_CATALOG_TTL = timedelta(hours=24)
MIN_CATALOG_TTL = timedelta(minutes=5)
MAX_CATALOG_TTL = timedelta(days=7)


@dataclass(frozen=True)
class CatalogEnrichmentResult:
    snapshot_id: uuid.UUID
    listing_id: uuid.UUID
    asin: str
    marketplace_id: str
    item_name: str | None
    brand: str | None
    manufacturer: str | None
    color: str | None
    size: str | None
    style: str | None
    model_number: str | None
    part_number: str | None
    product_type: str | None
    fetched_at: datetime
    expires_at: datetime
    cache_hit: bool


@dataclass(frozen=True)
class _EncryptedCatalogContext:
    user_id: uuid.UUID
    account_id: uuid.UUID
    listing_id: uuid.UUID
    account_key: str
    refresh_token_ciphertext: bytes
    refresh_token_key_version: int
    asin: str
    marketplace_id: str


class AmazonCatalogEnrichmentService:
    def __init__(
        self,
        *,
        encryption_service: TokenEncryptionService,
        catalog_client_factory: CatalogClientFactory,
        session_factory: Callable[[], Session] | None = None,
        clock: Callable[[], datetime] | None = None,
        ttl: timedelta = DEFAULT_CATALOG_TTL,
    ) -> None:
        if ttl < MIN_CATALOG_TTL or ttl > MAX_CATALOG_TTL:
            raise ValueError("catalog enrichment TTL is outside the allowed range")
        self._encryption = encryption_service
        self._catalog_client_factory = catalog_client_factory
        self._session_factory = session_factory or SessionLocal
        self._clock = clock or (lambda: datetime.now(UTC))
        self._ttl = ttl

    async def enrich_listing(
        self,
        *,
        user_id: uuid.UUID,
        account_id: uuid.UUID,
        listing_id: uuid.UUID,
        marketplace_id: str | None = None,
        force_refresh: bool = False,
    ) -> CatalogEnrichmentResult:
        cached, context = self._preflight(
            user_id=user_id,
            account_id=account_id,
            listing_id=listing_id,
            expected_marketplace_id=marketplace_id,
            allow_cache=not force_refresh,
        )
        if cached is not None:
            return cached
        assert context is not None

        try:
            summary = await self._fetch_catalog_summary(context)
        except AmazonError:
            raise
        except Exception:
            logger.warning(
                "Catalog enrichment fetch failed operation=catalog_enrichment "
                "category=external account_id=%s listing_id=%s",
                context.account_id,
                context.listing_id,
            )
            raise amazon_catalog_fetch_failed_error() from None
        return self._persist_summary(context=context, summary=summary)

    def _preflight(
        self,
        *,
        user_id: uuid.UUID,
        account_id: uuid.UUID,
        listing_id: uuid.UUID,
        expected_marketplace_id: str | None,
        allow_cache: bool,
    ) -> tuple[CatalogEnrichmentResult | None, _EncryptedCatalogContext | None]:
        now = self._clock()
        db = self._session_factory()
        try:
            account = (
                db.query(AmazonAccount)
                .filter(AmazonAccount.id == account_id, AmazonAccount.user_id == user_id)
                .one_or_none()
            )
            if account is None:
                raise amazon_account_not_found_error()
            self._assert_account_active(account)

            listing = (
                db.query(AmazonListing)
                .filter(
                    AmazonListing.id == listing_id,
                    AmazonListing.amazon_account_id == account_id,
                )
                .one_or_none()
            )
            if listing is None:
                raise amazon_listing_not_found_error()
            if (
                expected_marketplace_id is not None
                and listing.marketplace_id != expected_marketplace_id
            ):
                raise amazon_listing_not_found_error()
            asin = (listing.asin or "").strip()
            if not asin:
                raise amazon_catalog_asin_required_error()
            self._assert_marketplace_active(
                db,
                account_id=account_id,
                marketplace_id=listing.marketplace_id,
            )

            if allow_cache:
                snapshot = (
                    db.query(AmazonCatalogSnapshot)
                    .filter(
                        AmazonCatalogSnapshot.amazon_listing_id == listing.id,
                        AmazonCatalogSnapshot.asin == asin,
                        AmazonCatalogSnapshot.marketplace_id == listing.marketplace_id,
                        AmazonCatalogSnapshot.expires_at > now,
                    )
                    .order_by(
                        AmazonCatalogSnapshot.fetched_at.desc(),
                        AmazonCatalogSnapshot.id.desc(),
                    )
                    .first()
                )
                if snapshot is not None:
                    result = self._result_from_snapshot(snapshot, cache_hit=True)
                    db.rollback()
                    return result, None

            context = _EncryptedCatalogContext(
                user_id=user_id,
                account_id=account_id,
                listing_id=listing.id,
                account_key=account.account_key,
                refresh_token_ciphertext=bytes(account.refresh_token_ciphertext),
                refresh_token_key_version=account.refresh_token_key_version,
                asin=asin,
                marketplace_id=listing.marketplace_id,
            )
            db.rollback()
            return None, context
        except AmazonError:
            db.rollback()
            raise
        except Exception:
            db.rollback()
            logger.warning(
                "Catalog enrichment preflight failed operation=catalog_enrichment "
                "category=database account_id=%s listing_id=%s",
                account_id,
                listing_id,
            )
            raise amazon_catalog_persist_failed_error() from None
        finally:
            db.close()

    async def _fetch_catalog_summary(
        self,
        context: _EncryptedCatalogContext,
    ) -> CatalogItemSummary:
        plaintext = self._encryption.decrypt_refresh_token(
            context.refresh_token_ciphertext,
            user_id=context.user_id,
            account_id=context.account_id,
            key_version=context.refresh_token_key_version,
        )
        try:
            client = self._catalog_client_factory(plaintext)
            return await client.get_catalog_item(
                asin=context.asin,
                marketplace_id=context.marketplace_id,
                account_key=context.account_key,
            )
        finally:
            del plaintext

    def _persist_summary(
        self,
        *,
        context: _EncryptedCatalogContext,
        summary: CatalogItemSummary,
    ) -> CatalogEnrichmentResult:
        if summary.asin != context.asin or summary.marketplace_id != context.marketplace_id:
            raise amazon_catalog_identity_changed_error()
        db: Session | None = None
        try:
            now = self._clock()
            expires_at = now + self._ttl
            content_hash = catalog_summary_content_hash(summary)
            db = self._session_factory()
            account = (
                db.query(AmazonAccount)
                .filter(
                    AmazonAccount.id == context.account_id,
                    AmazonAccount.user_id == context.user_id,
                )
                .with_for_update()
                .one_or_none()
            )
            if account is None:
                raise amazon_account_not_found_error()
            self._assert_account_active(account)
            listing = (
                db.query(AmazonListing)
                .filter(
                    AmazonListing.id == context.listing_id,
                    AmazonListing.amazon_account_id == context.account_id,
                )
                .with_for_update()
                .one_or_none()
            )
            if listing is None:
                raise amazon_listing_not_found_error()
            if listing.asin != context.asin or listing.marketplace_id != context.marketplace_id:
                raise amazon_catalog_identity_changed_error()

            values = {
                "id": uuid.uuid4(),
                "amazon_listing_id": context.listing_id,
                "content_hash": content_hash,
                "asin": summary.asin,
                "marketplace_id": summary.marketplace_id,
                "item_name": summary.item_name,
                "brand": summary.brand,
                "manufacturer": summary.manufacturer,
                "color": summary.color,
                "size": summary.size,
                "style": summary.style,
                "model_number": summary.model_number,
                "part_number": summary.part_number,
                "product_type": summary.product_type,
                "source_request_id": summary.request_id,
                "fetched_at": now,
                "expires_at": expires_at,
                "updated_at": now,
            }
            insert_statement = pg_insert(AmazonCatalogSnapshot).values(**values)
            upsert_statement = insert_statement.on_conflict_do_update(
                constraint="uq_amazon_catalog_snapshots_listing_content",
                set_={
                    "source_request_id": insert_statement.excluded.source_request_id,
                    "fetched_at": insert_statement.excluded.fetched_at,
                    "expires_at": insert_statement.excluded.expires_at,
                    "updated_at": insert_statement.excluded.updated_at,
                },
            ).returning(AmazonCatalogSnapshot.id)
            snapshot_id = db.execute(upsert_statement).scalar_one()
            db.commit()
            snapshot = db.get(AmazonCatalogSnapshot, snapshot_id)
            assert snapshot is not None
            return self._result_from_snapshot(snapshot, cache_hit=False)
        except AmazonError:
            if db is not None:
                db.rollback()
            raise
        except Exception:
            if db is not None:
                db.rollback()
            logger.warning(
                "Catalog enrichment persist failed operation=catalog_enrichment "
                "category=database account_id=%s listing_id=%s",
                context.account_id,
                context.listing_id,
            )
            raise amazon_catalog_persist_failed_error() from None
        finally:
            if db is not None:
                db.close()

    @staticmethod
    def _assert_account_active(account: AmazonAccount) -> None:
        if account.status == AmazonAccountStatus.DISABLED:
            raise amazon_account_disabled_error()
        if account.status != AmazonAccountStatus.ACTIVE:
            raise amazon_account_not_active_error()

    @staticmethod
    def _assert_marketplace_active(
        db: Session,
        *,
        account_id: uuid.UUID,
        marketplace_id: str,
    ) -> None:
        participation = (
            db.query(AmazonMarketplaceParticipation)
            .filter(
                AmazonMarketplaceParticipation.amazon_account_id == account_id,
                AmazonMarketplaceParticipation.marketplace_id == marketplace_id,
            )
            .one_or_none()
        )
        if participation is None:
            raise amazon_marketplace_not_found_error()
        if not participation.is_active:
            raise amazon_marketplace_inactive_error()

    @staticmethod
    def _result_from_snapshot(
        snapshot: AmazonCatalogSnapshot,
        *,
        cache_hit: bool,
    ) -> CatalogEnrichmentResult:
        return CatalogEnrichmentResult(
            snapshot_id=snapshot.id,
            listing_id=snapshot.amazon_listing_id,
            asin=snapshot.asin,
            marketplace_id=snapshot.marketplace_id,
            item_name=snapshot.item_name,
            brand=snapshot.brand,
            manufacturer=snapshot.manufacturer,
            color=snapshot.color,
            size=snapshot.size,
            style=snapshot.style,
            model_number=snapshot.model_number,
            part_number=snapshot.part_number,
            product_type=snapshot.product_type,
            fetched_at=snapshot.fetched_at,
            expires_at=snapshot.expires_at,
            cache_hit=cache_hit,
        )


def catalog_summary_content_hash(summary: CatalogItemSummary) -> str:
    payload = asdict(summary)
    payload.pop("request_id", None)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
