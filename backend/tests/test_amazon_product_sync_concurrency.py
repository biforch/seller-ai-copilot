"""A4.2c product sync lease fencing, concurrency, and fault injection tests."""

from __future__ import annotations

import asyncio
import threading
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import httpx
import pytest

from app.integrations.amazon.exceptions import (
    AMAZON_SP_API_SERVER_ERROR,
    AMAZON_SYNC_FINALIZE_FAILED,
    AMAZON_SYNC_IN_PROGRESS,
    AMAZON_SYNC_LEASE_EXPIRED,
    AMAZON_SYNC_LEASE_LOST,
    AmazonError,
)
from app.integrations.amazon.listings_items import map_search_listings_items_page
from app.models.amazon_account import AmazonAccount, AmazonAccountStatus
from app.models.amazon_listing import AmazonListing
from app.models.amazon_sync_log import AmazonSyncLog, AmazonSyncOperation, AmazonSyncStatus
from app.models.product import Product
from app.models.project import Project
from app.services.amazon_marketplace_refresh_service import AmazonMarketplaceRefreshService
from app.services.amazon_product_sync_service import AmazonProductSyncService
from app.services.amazon_sync_lease_service import AmazonSyncLeaseService, SyncLeaseContext
from tests.fixtures.amazon_a32 import (
    FAKE_A32_REFRESH_TOKEN,
    build_sellers_client_factory,
    wire_item,
    wire_response,
)
from tests.fixtures.amazon_a42 import (
    CANARY,
    DEFAULT_MARKETPLACE_ID,
    SENSITIVE_MARKERS,
    FixedClock,
    create_sync_ready_account,
    make_product_sync_service,
    seed_active_listing,
    server_error_handler,
    single_page_success_handler,
    wire_listings_item,
    wire_listings_page,
)


def _assert_no_sensitive_leaks(text: str) -> None:
    for marker in SENSITIVE_MARKERS:
        assert marker not in text


def _make_gated_fetch(service: AmazonProductSyncService, original_fetch):
    gate = asyncio.Event()
    release = asyncio.Event()

    async def gated_fetch(*args, **kwargs):
        gate.set()
        await release.wait()
        return await original_fetch(*args, **kwargs)

    service._fetch_all_listings = gated_fetch  # type: ignore[method-assign]
    return gate, release


def _product_sync_acquire(
    service: AmazonProductSyncService,
    *,
    user_id: uuid.UUID,
    account_id: uuid.UUID,
    lease_duration: timedelta | None = None,
) -> SyncLeaseContext:
    return service._preflight_and_acquire(
        user_id=user_id,
        account_id=account_id,
        marketplace_id=DEFAULT_MARKETPLACE_ID,
        lease_duration=lease_duration or timedelta(seconds=30),
    )


def _takeover_expired_lease(
    session_factory,
    *,
    user_id: uuid.UUID,
    account_id: uuid.UUID,
    clock: FixedClock,
    operation: str = AmazonSyncOperation.PRODUCT_SYNC,
    lease_duration: timedelta | None = None,
) -> SyncLeaseContext:
    db = session_factory()
    try:
        lease_service = AmazonSyncLeaseService(
            db,
            min_lease_seconds=1,
            max_lease_seconds=3600,
            clock=clock,
        )
        return lease_service.acquire(
            user_id=user_id,
            account_id=account_id,
            operation=operation,
            lease_duration=lease_duration or timedelta(seconds=30),
        )
    finally:
        db.close()


@pytest.mark.asyncio
async def test_expired_lease_during_pagination_cannot_finalize(
    a32_session_factory,
    token_encryption_service,
) -> None:
    user, summary = create_sync_ready_account(a32_session_factory, token_encryption_service)
    seed_active_listing(
        a32_session_factory,
        account_id=summary.id,
        seller_sku="SKU-STALE",
    )
    clock = FixedClock(datetime.now(UTC))
    service = make_product_sync_service(
        token_encryption_service,
        a32_session_factory,
        single_page_success_handler,
        clock=clock,
    )
    gate, release = _make_gated_fetch(service, service._fetch_all_listings)
    task = asyncio.create_task(
        service.sync_product_listings(
            user_id=user.id,
            account_id=summary.id,
            marketplace_id=DEFAULT_MARKETPLACE_ID,
            lease_duration=timedelta(seconds=2),
        )
    )
    await asyncio.wait_for(gate.wait(), timeout=5)

    verify_mid = a32_session_factory()
    try:
        lease_ctx_a = (
            verify_mid.query(AmazonSyncLog)
            .filter_by(amazon_account_id=summary.id, status=AmazonSyncStatus.PROCESSING)
            .one()
        )
        log_a_id = lease_ctx_a.id
        account_mid = verify_mid.get(AmazonAccount, summary.id)
        assert account_mid is not None
        lease_a_id = account_mid.sync_lease_id
    finally:
        verify_mid.close()

    clock.advance(timedelta(seconds=3))
    release.set()

    with pytest.raises(AmazonError) as exc_info:
        await asyncio.wait_for(task, timeout=5)
    assert exc_info.value.error_code == AMAZON_SYNC_LEASE_LOST

    verify = a32_session_factory()
    try:
        account = verify.get(AmazonAccount, summary.id)
        assert account is not None
        assert account.sync_lease_id == lease_a_id
        assert account.sync_lease_expires_at is not None
        assert account.sync_lease_expires_at <= clock()

        log_a = verify.get(AmazonSyncLog, log_a_id)
        assert log_a is not None
        assert log_a.status == AmazonSyncStatus.PROCESSING

        stale = (
            verify.query(AmazonListing)
            .filter_by(amazon_account_id=summary.id, seller_sku="SKU-STALE")
            .one()
        )
        assert stale.is_active is True
        assert (
            verify.query(AmazonListing)
            .filter_by(amazon_account_id=summary.id, seller_sku="SKU-001")
            .count()
            == 0
        )
    finally:
        verify.close()

    lease_ctx_b = _takeover_expired_lease(
        a32_session_factory,
        user_id=user.id,
        account_id=summary.id,
        clock=clock,
    )

    verify_after = a32_session_factory()
    try:
        log_a = verify_after.get(AmazonSyncLog, log_a_id)
        assert log_a is not None
        assert log_a.status == AmazonSyncStatus.FAILED
        assert log_a.error_code == AMAZON_SYNC_LEASE_EXPIRED

        log_b = verify_after.get(AmazonSyncLog, lease_ctx_b.sync_log_id)
        assert log_b is not None
        assert log_b.status == AmazonSyncStatus.PROCESSING

        account = verify_after.get(AmazonAccount, summary.id)
        assert account is not None
        assert account.sync_lease_id == lease_ctx_b.lease_id
    finally:
        verify_after.close()

    lease_ctx_a_obj = SyncLeaseContext(
        account_id=summary.id,
        user_id=user.id,
        lease_id=lease_a_id,  # type: ignore[arg-type]
        sync_log_id=log_a_id,
        expires_at=clock(),
        operation=AmazonSyncOperation.PRODUCT_SYNC,
    )
    with pytest.raises(AmazonError) as exc_info:
        service._finalize_success(
            lease_ctx=lease_ctx_a_obj,
            marketplace_id=DEFAULT_MARKETPLACE_ID,
            items=(),
            pages_seen=0,
            request_id=None,
        )
    assert exc_info.value.error_code == AMAZON_SYNC_LEASE_LOST

    verify_final = a32_session_factory()
    try:
        log_b = verify_final.get(AmazonSyncLog, lease_ctx_b.sync_log_id)
        assert log_b is not None
        assert log_b.status == AmazonSyncStatus.PROCESSING
        account = verify_final.get(AmazonAccount, summary.id)
        assert account is not None
        assert account.sync_lease_id == lease_ctx_b.lease_id
    finally:
        verify_final.close()


@pytest.mark.asyncio
async def test_takeover_prevents_old_worker_finalize(
    a32_session_factory,
    token_encryption_service,
) -> None:
    user, summary = create_sync_ready_account(a32_session_factory, token_encryption_service)
    clock = FixedClock(datetime.now(UTC))
    service = make_product_sync_service(
        token_encryption_service,
        a32_session_factory,
        single_page_success_handler,
        clock=clock,
    )

    lease_ctx_a = _product_sync_acquire(
        service,
        user_id=user.id,
        account_id=summary.id,
        lease_duration=timedelta(seconds=2),
    )
    clock.advance(timedelta(seconds=3))
    lease_ctx_b = _takeover_expired_lease(
        a32_session_factory,
        user_id=user.id,
        account_id=summary.id,
        clock=clock,
    )

    with pytest.raises(AmazonError) as exc_info:
        service._finalize_success(
            lease_ctx=lease_ctx_a,
            marketplace_id=DEFAULT_MARKETPLACE_ID,
            items=map_search_listings_items_page(
                wire_listings_page(wire_listings_item()),
                marketplace_id=DEFAULT_MARKETPLACE_ID,
            ).items,
            pages_seen=1,
            request_id="req-takeover",
        )
    assert exc_info.value.error_code == AMAZON_SYNC_LEASE_LOST

    verify = a32_session_factory()
    try:
        account = verify.get(AmazonAccount, summary.id)
        assert account is not None
        assert account.sync_lease_id == lease_ctx_b.lease_id

        log_b = verify.get(AmazonSyncLog, lease_ctx_b.sync_log_id)
        assert log_b is not None
        assert log_b.status == AmazonSyncStatus.PROCESSING

        log_a = verify.get(AmazonSyncLog, lease_ctx_a.sync_log_id)
        assert log_a is not None
        assert log_a.status == AmazonSyncStatus.FAILED
        assert log_a.error_code == AMAZON_SYNC_LEASE_EXPIRED

        assert (
            verify.query(AmazonListing)
            .filter_by(amazon_account_id=summary.id)
            .count()
            == 0
        )
    finally:
        verify.close()


@pytest.mark.asyncio
async def test_public_sync_path_respects_takeover_fencing(
    a32_session_factory,
    token_encryption_service,
) -> None:
    user, summary = create_sync_ready_account(a32_session_factory, token_encryption_service)
    clock = FixedClock(datetime.now(UTC))
    service = make_product_sync_service(
        token_encryption_service,
        a32_session_factory,
        single_page_success_handler,
        clock=clock,
    )
    gate, release = _make_gated_fetch(service, service._fetch_all_listings)
    task = asyncio.create_task(
        service.sync_product_listings(
            user_id=user.id,
            account_id=summary.id,
            marketplace_id=DEFAULT_MARKETPLACE_ID,
            lease_duration=timedelta(seconds=30),
        )
    )
    await asyncio.wait_for(gate.wait(), timeout=5)

    verify_mid = a32_session_factory()
    try:
        account_mid = verify_mid.get(AmazonAccount, summary.id)
        assert account_mid is not None
        lease_a_id = account_mid.sync_lease_id
        log_a_id = (
            verify_mid.query(AmazonSyncLog)
            .filter_by(amazon_account_id=summary.id, status=AmazonSyncStatus.PROCESSING)
            .one()
            .id
        )
    finally:
        verify_mid.close()

    clock.advance(timedelta(seconds=31))
    _takeover_expired_lease(
        a32_session_factory,
        user_id=user.id,
        account_id=summary.id,
        clock=clock,
    )
    release.set()

    with pytest.raises(AmazonError) as exc_info:
        await asyncio.wait_for(task, timeout=5)
    assert exc_info.value.error_code == AMAZON_SYNC_LEASE_LOST

    verify = a32_session_factory()
    try:
        account = verify.get(AmazonAccount, summary.id)
        assert account is not None
        assert account.sync_lease_id != lease_a_id
        log_a = verify.get(AmazonSyncLog, log_a_id)
        assert log_a is not None
        assert log_a.status == AmazonSyncStatus.FAILED
        assert log_a.error_code == AMAZON_SYNC_LEASE_EXPIRED
    finally:
        verify.close()


def test_concurrent_product_sync_acquire_single_winner(
    a32_session_factory,
    token_encryption_service,
) -> None:
    user, summary = create_sync_ready_account(a32_session_factory, token_encryption_service)
    clock = FixedClock(datetime.now(UTC))
    service = make_product_sync_service(
        token_encryption_service,
        a32_session_factory,
        single_page_success_handler,
        clock=clock,
    )
    barrier = threading.Barrier(2)
    results: list[SyncLeaseContext | BaseException] = []

    def worker() -> None:
        db = a32_session_factory()
        try:
            barrier.wait(timeout=5)
            ctx = _product_sync_acquire(
                service,
                user_id=user.id,
                account_id=summary.id,
            )
            results.append(ctx)
        except BaseException as exc:
            results.append(exc)
        finally:
            db.close()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    thread_errors = [
        item for item in results if isinstance(item, BaseException) and not isinstance(item, AmazonError)
    ]
    assert not thread_errors, f"unexpected thread errors: {thread_errors!r}"

    winners = [item for item in results if isinstance(item, SyncLeaseContext)]
    losers = [item for item in results if isinstance(item, AmazonError)]
    assert len(winners) == 1
    assert len(losers) == 1
    assert losers[0].error_code == AMAZON_SYNC_IN_PROGRESS

    verify = a32_session_factory()
    try:
        account = verify.get(AmazonAccount, summary.id)
        assert account is not None
        assert account.sync_lease_id == winners[0].lease_id
        processing = (
            verify.query(AmazonSyncLog)
            .filter_by(amazon_account_id=summary.id, status=AmazonSyncStatus.PROCESSING)
            .all()
        )
        assert len(processing) == 1
        assert processing[0].operation == AmazonSyncOperation.PRODUCT_SYNC
    finally:
        verify.close()


@pytest.mark.asyncio
async def test_product_sync_blocks_marketplace_refresh_acquire(
    a32_session_factory,
    token_encryption_service,
) -> None:
    user, summary = create_sync_ready_account(a32_session_factory, token_encryption_service)
    product_service = make_product_sync_service(
        token_encryption_service,
        a32_session_factory,
        single_page_success_handler,
    )
    refresh_service = AmazonMarketplaceRefreshService(
        session_factory=a32_session_factory,
        encryption_service=token_encryption_service,
        sellers_client_factory=build_sellers_client_factory(
            refresh_token=FAKE_A32_REFRESH_TOKEN,
            sp_api_handler=lambda request: httpx.Response(
                200,
                json=wire_response(wire_item()),
                headers={"x-amzn-requestid": "req-refresh"},
            ),
        ),
        min_lease_seconds=1,
        max_lease_seconds=3600,
    )
    gate, release = _make_gated_fetch(product_service, product_service._fetch_all_listings)
    task = asyncio.create_task(
        product_service.sync_product_listings(
            user_id=user.id,
            account_id=summary.id,
            marketplace_id=DEFAULT_MARKETPLACE_ID,
        )
    )
    await asyncio.wait_for(gate.wait(), timeout=5)

    with pytest.raises(AmazonError) as exc_info:
        await refresh_service.refresh_marketplace_participations(
            user_id=user.id,
            account_id=summary.id,
        )
    assert exc_info.value.error_code == AMAZON_SYNC_IN_PROGRESS

    release.set()
    await asyncio.wait_for(task, timeout=5)


@pytest.mark.asyncio
async def test_failure_finalize_after_lease_takeover_preserves_original_error(
    a32_session_factory,
    token_encryption_service,
    caplog,
) -> None:
    user, summary = create_sync_ready_account(a32_session_factory, token_encryption_service)
    clock = FixedClock(datetime.now(UTC))
    service = make_product_sync_service(
        token_encryption_service,
        a32_session_factory,
        server_error_handler,
        clock=clock,
    )
    lease_ctx_b_holder: dict[str, SyncLeaseContext] = {}
    log_a_holder: dict[str, uuid.UUID] = {}
    original_attempt = service._attempt_failure_finalize

    def attempt_after_takeover(**kwargs):
        log_a_holder["id"] = kwargs["lease_ctx"].sync_log_id
        clock.advance(timedelta(seconds=31))
        lease_ctx_b_holder["ctx"] = _takeover_expired_lease(
            a32_session_factory,
            user_id=user.id,
            account_id=summary.id,
            clock=clock,
        )
        return original_attempt(**kwargs)

    service._attempt_failure_finalize = attempt_after_takeover  # type: ignore[method-assign]

    with pytest.raises(AmazonError) as exc_info:
        await service.sync_product_listings(
            user_id=user.id,
            account_id=summary.id,
            marketplace_id=DEFAULT_MARKETPLACE_ID,
            lease_duration=timedelta(seconds=30),
        )
    assert exc_info.value.error_code == AMAZON_SP_API_SERVER_ERROR
    _assert_no_sensitive_leaks(str(exc_info.value))
    for record in caplog.records:
        _assert_no_sensitive_leaks(record.getMessage())

    lease_ctx_b = lease_ctx_b_holder["ctx"]
    verify = a32_session_factory()
    try:
        log_a = verify.get(AmazonSyncLog, log_a_holder["id"])
        assert log_a is not None
        assert log_a.status == AmazonSyncStatus.FAILED
        assert log_a.error_code == AMAZON_SYNC_LEASE_EXPIRED

        log_b = verify.get(AmazonSyncLog, lease_ctx_b.sync_log_id)
        assert log_b is not None
        assert log_b.status == AmazonSyncStatus.PROCESSING

        account = verify.get(AmazonAccount, summary.id)
        assert account is not None
        assert account.sync_lease_id == lease_ctx_b.lease_id
    finally:
        verify.close()


@pytest.mark.asyncio
async def test_failure_finalize_internal_error_preserves_original_amazon_error(
    a32_session_factory,
    token_encryption_service,
    caplog,
) -> None:
    user, summary = create_sync_ready_account(a32_session_factory, token_encryption_service)
    seed_active_listing(
        a32_session_factory,
        account_id=summary.id,
        seller_sku="SKU-KEEP",
    )
    service = make_product_sync_service(
        token_encryption_service,
        a32_session_factory,
        server_error_handler,
    )
    with patch.object(
        service,
        "_apply_failure_finalize",
        side_effect=RuntimeError(f"finalize boom {CANARY}"),
    ):
        with pytest.raises(AmazonError) as exc_info:
            await service.sync_product_listings(
                user_id=user.id,
                account_id=summary.id,
                marketplace_id=DEFAULT_MARKETPLACE_ID,
            )
    assert exc_info.value.error_code == AMAZON_SP_API_SERVER_ERROR
    _assert_no_sensitive_leaks(str(exc_info.value))
    _assert_no_sensitive_leaks(repr(exc_info.value))
    for record in caplog.records:
        _assert_no_sensitive_leaks(record.getMessage())

    verify = a32_session_factory()
    try:
        row = (
            verify.query(AmazonListing)
            .filter_by(amazon_account_id=summary.id, seller_sku="SKU-KEEP")
            .one()
        )
        assert row.is_active is True
        log = (
            verify.query(AmazonSyncLog)
            .filter_by(amazon_account_id=summary.id)
            .order_by(AmazonSyncLog.created_at.desc())
            .first()
        )
        assert log is not None
        assert log.status == AmazonSyncStatus.PROCESSING
    finally:
        verify.close()


@pytest.mark.asyncio
async def test_tx2_db_exception_finalizes_and_sanitizes_logs(
    a32_session_factory,
    token_encryption_service,
    caplog,
) -> None:
    user, summary = create_sync_ready_account(a32_session_factory, token_encryption_service)
    service = make_product_sync_service(
        token_encryption_service,
        a32_session_factory,
        single_page_success_handler,
    )
    with patch.object(
        AmazonProductSyncService,
        "_upsert_listings",
        side_effect=RuntimeError(f"tx2 boom {CANARY}"),
    ):
        with pytest.raises(AmazonError) as exc_info:
            await service.sync_product_listings(
                user_id=user.id,
                account_id=summary.id,
                marketplace_id=DEFAULT_MARKETPLACE_ID,
            )
    assert exc_info.value.error_code == AMAZON_SYNC_FINALIZE_FAILED
    _assert_no_sensitive_leaks(str(exc_info.value))
    for record in caplog.records:
        _assert_no_sensitive_leaks(record.getMessage())

    verify = a32_session_factory()
    try:
        account = verify.get(AmazonAccount, summary.id)
        assert account is not None
        assert account.status == AmazonAccountStatus.ERROR
        assert account.sync_lease_id is None
        log = (
            verify.query(AmazonSyncLog)
            .filter_by(amazon_account_id=summary.id)
            .order_by(AmazonSyncLog.created_at.desc())
            .first()
        )
        assert log is not None
        assert log.status == AmazonSyncStatus.FAILED
        assert log.error_code == AMAZON_SYNC_FINALIZE_FAILED
        assert (
            verify.query(AmazonListing)
            .filter_by(amazon_account_id=summary.id)
            .count()
            == 0
        )
    finally:
        verify.close()


@pytest.mark.asyncio
async def test_tx2_upsert_deactivate_atomic_rollback(
    a32_session_factory,
    token_encryption_service,
    user_factory,
) -> None:
    user, summary = create_sync_ready_account(a32_session_factory, token_encryption_service)
    project = Project(user_id=user.id, name="Atomic Project")
    db_seed = a32_session_factory()
    product_id = uuid.uuid4()
    try:
        db_seed.add(project)
        db_seed.flush()
        db_seed.add(
            Product(
                id=product_id,
                user_id=user.id,
                project_id=project.id,
                name="Linked",
            )
        )
        db_seed.commit()
    finally:
        db_seed.close()

    seed_active_listing(
        a32_session_factory,
        account_id=summary.id,
        seller_sku="SKU-EXISTING",
        asin="B000000099",
        product_id=product_id,
        is_active=True,
    )

    service = make_product_sync_service(
        token_encryption_service,
        a32_session_factory,
        single_page_success_handler,
    )
    with patch.object(
        AmazonProductSyncService,
        "_soft_deactivate_unseen",
        side_effect=RuntimeError(f"deactivate boom {CANARY}"),
    ):
        with pytest.raises(AmazonError) as exc_info:
            await service.sync_product_listings(
                user_id=user.id,
                account_id=summary.id,
                marketplace_id=DEFAULT_MARKETPLACE_ID,
            )
    assert exc_info.value.error_code == AMAZON_SYNC_FINALIZE_FAILED

    verify = a32_session_factory()
    try:
        existing = (
            verify.query(AmazonListing)
            .filter_by(amazon_account_id=summary.id, seller_sku="SKU-EXISTING")
            .one()
        )
        assert existing.asin == "B000000099"
        assert existing.is_active is True
        assert existing.product_id == product_id
        assert (
            verify.query(AmazonListing)
            .filter_by(amazon_account_id=summary.id, seller_sku="SKU-001")
            .count()
            == 0
        )

        account = verify.get(AmazonAccount, summary.id)
        assert account is not None
        assert account.sync_lease_id is None
        log = (
            verify.query(AmazonSyncLog)
            .filter_by(amazon_account_id=summary.id)
            .order_by(AmazonSyncLog.created_at.desc())
            .first()
        )
        assert log is not None
        assert log.status == AmazonSyncStatus.FAILED
        assert log.error_code == AMAZON_SYNC_FINALIZE_FAILED
    finally:
        verify.close()
