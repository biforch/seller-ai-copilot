from __future__ import annotations

import asyncio
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app.integrations.amazon.catalog_items import CatalogItemSummary
from app.integrations.amazon.exceptions import (
    AMAZON_ACCOUNT_NOT_FOUND,
    AMAZON_CATALOG_ASIN_REQUIRED,
    AMAZON_CATALOG_FETCH_FAILED,
    AMAZON_CATALOG_IDENTITY_CHANGED,
    AMAZON_CATALOG_PERSIST_FAILED,
    AMAZON_LISTING_NOT_FOUND,
    AMAZON_MARKETPLACE_INACTIVE,
    AMAZON_SP_API_RATE_LIMITED,
    AmazonError,
    sp_api_error_from_status,
)
from app.models.amazon_account import AmazonAccount, AmazonAccountStatus
from app.models.amazon_catalog_snapshot import AmazonCatalogSnapshot
from app.models.amazon_listing import AmazonListing
from app.models.amazon_marketplace_participation import AmazonMarketplaceParticipation
from app.models.user import User
from app.services.amazon_catalog_enrichment_service import (
    AmazonCatalogEnrichmentService,
    catalog_summary_content_hash,
)
from tests.fixtures.amazon_a32 import FAKE_A32_REFRESH_TOKEN, create_committed_account

MARKETPLACE_ID = "ATVPDKIKX0DER"
ASIN = "B012345678"


class FixedClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 8, 17, 12, tzinfo=UTC)

    def advance(self, delta: timedelta) -> None:
        self.now += delta

    def __call__(self) -> datetime:
        return self.now


@dataclass(frozen=True)
class CatalogBundle:
    user_id: uuid.UUID
    account_id: uuid.UUID
    listing_id: uuid.UUID


@pytest.fixture
def catalog_bundle_factory(a32_session_factory, token_encryption_service):
    user_ids: list[uuid.UUID] = []

    def create(*, asin: str | None = ASIN, participation_active: bool = True) -> CatalogBundle:
        user, account_summary = create_committed_account(
            a32_session_factory,
            token_encryption_service,
            token=FAKE_A32_REFRESH_TOKEN,
        )
        user_ids.append(user.id)
        db = a32_session_factory()
        try:
            db.add(
                AmazonMarketplaceParticipation(
                    amazon_account_id=account_summary.id,
                    marketplace_id=MARKETPLACE_ID,
                    marketplace_name="Amazon.com",
                    country_code="US",
                    participating=True,
                    suspended_listings=False,
                    is_active=participation_active,
                )
            )
            listing = AmazonListing(
                amazon_account_id=account_summary.id,
                marketplace_id=MARKETPLACE_ID,
                seller_sku=f"CATALOG-{uuid.uuid4()}",
                asin=asin,
                status_codes=["BUYABLE"],
                is_active=True,
                first_seen_at=datetime.now(UTC),
                last_seen_at=datetime.now(UTC),
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
            db.add(listing)
            db.commit()
            db.refresh(listing)
            return CatalogBundle(user.id, account_summary.id, listing.id)
        finally:
            db.close()

    yield create

    db = a32_session_factory()
    try:
        db.query(User).filter(User.id.in_(user_ids)).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


def _summary(**overrides) -> CatalogItemSummary:
    item = CatalogItemSummary(
        asin=ASIN,
        marketplace_id=MARKETPLACE_ID,
        item_name="Catalog title",
        brand="Brand",
        manufacturer="Manufacturer",
        color="Blue",
        size="Medium",
        style="Modern",
        model_number="MODEL-1",
        part_number="PART-1",
        product_type="PRODUCT",
        request_id="catalog-request-1",
    )
    return replace(item, **overrides)


class FakeCatalogClient:
    def __init__(self, result, calls, callback=None) -> None:
        self._result = result
        self._calls = calls
        self._callback = callback

    async def get_catalog_item(self, **kwargs):
        self._calls.append(kwargs)
        if self._callback is not None:
            self._callback()
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


def _service(
    *,
    session_factory,
    encryption,
    result=None,
    calls=None,
    callback=None,
    clock=None,
    ttl=timedelta(hours=24),
):
    call_list = calls if calls is not None else []

    def factory(plaintext):
        assert plaintext == FAKE_A32_REFRESH_TOKEN
        return FakeCatalogClient(result or _summary(), call_list, callback)

    return AmazonCatalogEnrichmentService(
        session_factory=session_factory,
        encryption_service=encryption,
        catalog_client_factory=factory,
        clock=clock,
        ttl=ttl,
    )


@pytest.mark.asyncio
async def test_enrich_persists_bounded_snapshot(
    a32_session_factory, token_encryption_service, catalog_bundle_factory
) -> None:
    bundle = catalog_bundle_factory()
    clock = FixedClock()
    calls = []
    service = _service(
        session_factory=a32_session_factory,
        encryption=token_encryption_service,
        calls=calls,
        clock=clock,
    )
    result = await service.enrich_listing(
        user_id=bundle.user_id,
        account_id=bundle.account_id,
        listing_id=bundle.listing_id,
    )
    assert result.cache_hit is False
    assert result.item_name == "Catalog title"
    assert result.expires_at == clock.now + timedelta(hours=24)
    assert len(calls) == 1
    db = a32_session_factory()
    try:
        snapshot = db.get(AmazonCatalogSnapshot, result.snapshot_id)
        assert snapshot is not None
        assert snapshot.content_hash == catalog_summary_content_hash(_summary())
        assert not hasattr(snapshot, "payload")
    finally:
        db.close()


@pytest.mark.asyncio
async def test_fresh_cache_hit_skips_decrypt_factory_and_http(
    a32_session_factory, token_encryption_service, catalog_bundle_factory, monkeypatch
) -> None:
    bundle = catalog_bundle_factory()
    clock = FixedClock()
    calls = []
    service = _service(
        session_factory=a32_session_factory,
        encryption=token_encryption_service,
        calls=calls,
        clock=clock,
    )
    first = await service.enrich_listing(
        user_id=bundle.user_id,
        account_id=bundle.account_id,
        listing_id=bundle.listing_id,
    )
    monkeypatch.setattr(
        token_encryption_service,
        "decrypt_refresh_token",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not decrypt")),
    )
    second = await service.enrich_listing(
        user_id=bundle.user_id,
        account_id=bundle.account_id,
        listing_id=bundle.listing_id,
    )
    assert second.cache_hit is True
    assert second.snapshot_id == first.snapshot_id
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_force_refresh_same_content_updates_one_row(
    a32_session_factory, token_encryption_service, catalog_bundle_factory
) -> None:
    bundle = catalog_bundle_factory()
    clock = FixedClock()
    service = _service(
        session_factory=a32_session_factory,
        encryption=token_encryption_service,
        clock=clock,
    )
    first = await service.enrich_listing(
        user_id=bundle.user_id,
        account_id=bundle.account_id,
        listing_id=bundle.listing_id,
    )
    clock.advance(timedelta(hours=1))
    second = await service.enrich_listing(
        user_id=bundle.user_id,
        account_id=bundle.account_id,
        listing_id=bundle.listing_id,
        force_refresh=True,
    )
    assert second.snapshot_id == first.snapshot_id
    assert second.fetched_at == clock.now
    db = a32_session_factory()
    try:
        assert (
            db.query(AmazonCatalogSnapshot)
            .filter(AmazonCatalogSnapshot.amazon_listing_id == bundle.listing_id)
            .count()
            == 1
        )
    finally:
        db.close()


@pytest.mark.asyncio
async def test_changed_content_creates_history_row(
    a32_session_factory, token_encryption_service, catalog_bundle_factory
) -> None:
    bundle = catalog_bundle_factory()
    clock = FixedClock()
    first_service = _service(
        session_factory=a32_session_factory,
        encryption=token_encryption_service,
        clock=clock,
    )
    first = await first_service.enrich_listing(
        user_id=bundle.user_id,
        account_id=bundle.account_id,
        listing_id=bundle.listing_id,
    )
    clock.advance(timedelta(hours=1))
    changed_service = _service(
        session_factory=a32_session_factory,
        encryption=token_encryption_service,
        result=_summary(item_name="Changed title"),
        clock=clock,
    )
    second = await changed_service.enrich_listing(
        user_id=bundle.user_id,
        account_id=bundle.account_id,
        listing_id=bundle.listing_id,
        force_refresh=True,
    )
    assert second.snapshot_id != first.snapshot_id
    db = a32_session_factory()
    try:
        assert (
            db.query(AmazonCatalogSnapshot)
            .filter(AmazonCatalogSnapshot.amazon_listing_id == bundle.listing_id)
            .count()
            == 2
        )
    finally:
        db.close()


@pytest.mark.asyncio
async def test_external_call_has_no_open_service_transaction(
    a32_session_factory, token_encryption_service, catalog_bundle_factory
) -> None:
    bundle = catalog_bundle_factory()
    sessions: list[Session] = []

    def tracked_factory():
        session = a32_session_factory()
        sessions.append(session)
        return session

    def assert_closed_transactions():
        assert all(not session.in_transaction() for session in sessions)

    service = _service(
        session_factory=tracked_factory,
        encryption=token_encryption_service,
        callback=assert_closed_transactions,
    )
    await service.enrich_listing(
        user_id=bundle.user_id,
        account_id=bundle.account_id,
        listing_id=bundle.listing_id,
    )


@pytest.mark.asyncio
async def test_listing_identity_change_during_http_is_fenced(
    a32_session_factory, token_encryption_service, catalog_bundle_factory
) -> None:
    bundle = catalog_bundle_factory()

    def mutate_identity():
        db = a32_session_factory()
        try:
            listing = db.get(AmazonListing, bundle.listing_id)
            assert listing is not None
            listing.asin = "B000000001"
            db.commit()
        finally:
            db.close()

    service = _service(
        session_factory=a32_session_factory,
        encryption=token_encryption_service,
        callback=mutate_identity,
    )
    with pytest.raises(AmazonError) as exc_info:
        await service.enrich_listing(
            user_id=bundle.user_id,
            account_id=bundle.account_id,
            listing_id=bundle.listing_id,
        )
    assert exc_info.value.error_code == AMAZON_CATALOG_IDENTITY_CHANGED
    db = a32_session_factory()
    try:
        assert db.query(AmazonCatalogSnapshot).count() == 0
    finally:
        db.close()


@pytest.mark.asyncio
async def test_external_amazon_error_creates_no_snapshot(
    a32_session_factory, token_encryption_service, catalog_bundle_factory
) -> None:
    bundle = catalog_bundle_factory()
    service = _service(
        session_factory=a32_session_factory,
        encryption=token_encryption_service,
        result=sp_api_error_from_status(429),
    )
    with pytest.raises(AmazonError) as exc_info:
        await service.enrich_listing(
            user_id=bundle.user_id,
            account_id=bundle.account_id,
            listing_id=bundle.listing_id,
        )
    assert exc_info.value.error_code == AMAZON_SP_API_RATE_LIMITED
    db = a32_session_factory()
    try:
        assert db.query(AmazonCatalogSnapshot).count() == 0
    finally:
        db.close()


@pytest.mark.asyncio
async def test_unexpected_external_error_is_stable_and_sanitized(
    a32_session_factory,
    token_encryption_service,
    catalog_bundle_factory,
    caplog,
) -> None:
    bundle = catalog_bundle_factory()
    canary = "CATALOG_EXTERNAL_SECRET_CANARY"
    service = _service(
        session_factory=a32_session_factory,
        encryption=token_encryption_service,
        result=RuntimeError(canary),
    )
    with caplog.at_level("WARNING"):
        with pytest.raises(AmazonError) as exc_info:
            await service.enrich_listing(
                user_id=bundle.user_id,
                account_id=bundle.account_id,
                listing_id=bundle.listing_id,
            )
    assert exc_info.value.error_code == AMAZON_CATALOG_FETCH_FAILED
    assert canary not in str(exc_info.value)
    assert canary not in " ".join(record.message for record in caplog.records)


@pytest.mark.asyncio
async def test_unexpected_persist_error_is_stable_and_sanitized(
    a32_session_factory,
    token_encryption_service,
    catalog_bundle_factory,
    monkeypatch,
    caplog,
) -> None:
    bundle = catalog_bundle_factory()
    canary = "CATALOG_PERSIST_SECRET_CANARY"
    service = _service(
        session_factory=a32_session_factory,
        encryption=token_encryption_service,
    )
    monkeypatch.setattr(
        "app.services.amazon_catalog_enrichment_service.catalog_summary_content_hash",
        lambda _summary: (_ for _ in ()).throw(RuntimeError(canary)),
    )
    with caplog.at_level("WARNING"):
        with pytest.raises(AmazonError) as exc_info:
            await service.enrich_listing(
                user_id=bundle.user_id,
                account_id=bundle.account_id,
                listing_id=bundle.listing_id,
            )
    assert exc_info.value.error_code == AMAZON_CATALOG_PERSIST_FAILED
    assert canary not in str(exc_info.value)
    assert canary not in " ".join(record.message for record in caplog.records)


@pytest.mark.asyncio
async def test_missing_asin_rejected_without_decrypt_or_http(
    a32_session_factory, token_encryption_service, catalog_bundle_factory
) -> None:
    bundle = catalog_bundle_factory(asin=None)
    calls = []
    service = _service(
        session_factory=a32_session_factory,
        encryption=token_encryption_service,
        calls=calls,
    )
    with pytest.raises(AmazonError) as exc_info:
        await service.enrich_listing(
            user_id=bundle.user_id,
            account_id=bundle.account_id,
            listing_id=bundle.listing_id,
        )
    assert exc_info.value.error_code == AMAZON_CATALOG_ASIN_REQUIRED
    assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("scope", "expected_code"),
    [
        ("account", AMAZON_ACCOUNT_NOT_FOUND),
        ("listing", AMAZON_LISTING_NOT_FOUND),
        ("marketplace", AMAZON_MARKETPLACE_INACTIVE),
    ],
)
async def test_preflight_scope_and_marketplace_errors_are_stable(
    scope,
    expected_code,
    a32_session_factory,
    token_encryption_service,
    catalog_bundle_factory,
) -> None:
    bundle = catalog_bundle_factory(participation_active=scope != "marketplace")
    account_id = uuid.uuid4() if scope == "account" else bundle.account_id
    listing_id = uuid.uuid4() if scope == "listing" else bundle.listing_id
    service = _service(
        session_factory=a32_session_factory,
        encryption=token_encryption_service,
    )
    with pytest.raises(AmazonError) as exc_info:
        await service.enrich_listing(
            user_id=bundle.user_id,
            account_id=account_id,
            listing_id=listing_id,
        )
    assert exc_info.value.error_code == expected_code


@pytest.mark.asyncio
async def test_account_disabled_during_http_is_rechecked(
    a32_session_factory, token_encryption_service, catalog_bundle_factory
) -> None:
    bundle = catalog_bundle_factory()

    def disable_account():
        db = a32_session_factory()
        try:
            account = db.get(AmazonAccount, bundle.account_id)
            assert account is not None
            account.status = AmazonAccountStatus.DISABLED
            db.commit()
        finally:
            db.close()

    service = _service(
        session_factory=a32_session_factory,
        encryption=token_encryption_service,
        callback=disable_account,
    )
    with pytest.raises(AmazonError):
        await service.enrich_listing(
            user_id=bundle.user_id,
            account_id=bundle.account_id,
            listing_id=bundle.listing_id,
        )
    db = a32_session_factory()
    try:
        assert db.query(AmazonCatalogSnapshot).count() == 0
    finally:
        db.close()


def test_content_hash_is_stable_and_ignores_request_id() -> None:
    first = _summary(request_id="request-a")
    second = _summary(request_id="request-b")
    assert catalog_summary_content_hash(first) == catalog_summary_content_hash(second)
    assert catalog_summary_content_hash(first) != catalog_summary_content_hash(
        _summary(item_name="Different")
    )


@pytest.mark.parametrize(
    "ttl",
    [timedelta(minutes=4), timedelta(days=8)],
)
def test_ttl_bounds_fail_fast(ttl, token_encryption_service) -> None:
    with pytest.raises(ValueError):
        AmazonCatalogEnrichmentService(
            encryption_service=token_encryption_service,
            catalog_client_factory=lambda _token: None,  # type: ignore[arg-type,return-value]
            ttl=ttl,
        )


def test_concurrent_same_content_is_single_row(
    a32_session_factory, token_encryption_service, catalog_bundle_factory
) -> None:
    bundle = catalog_bundle_factory()
    barrier = threading.Barrier(2)

    class BarrierClient:
        async def get_catalog_item(self, **_kwargs):
            barrier.wait(timeout=5)
            return _summary()

    def run_once():
        service = AmazonCatalogEnrichmentService(
            session_factory=a32_session_factory,
            encryption_service=token_encryption_service,
            catalog_client_factory=lambda _token: BarrierClient(),  # type: ignore[arg-type,return-value]
        )
        return asyncio.run(
            service.enrich_listing(
                user_id=bundle.user_id,
                account_id=bundle.account_id,
                listing_id=bundle.listing_id,
                force_refresh=True,
            )
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _index: run_once(), range(2)))
    assert results[0].snapshot_id == results[1].snapshot_id
    db = a32_session_factory()
    try:
        assert (
            db.query(AmazonCatalogSnapshot)
            .filter(AmazonCatalogSnapshot.amazon_listing_id == bundle.listing_id)
            .count()
            == 1
        )
    finally:
        db.close()
