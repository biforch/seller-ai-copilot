"""Amazon product sync service integration tests (A4.2b)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import patch

import httpx
import pytest
from sqlalchemy.orm import Session

from app.integrations.amazon.exceptions import (
    AMAZON_ACCOUNT_DISABLED,
    AMAZON_ACCOUNT_NOT_ACTIVE,
    AMAZON_ACCOUNT_NOT_FOUND,
    AMAZON_LWA_TOKEN_INVALID,
    AMAZON_MARKETPLACE_INACTIVE,
    AMAZON_MARKETPLACE_NOT_ELIGIBLE,
    AMAZON_MARKETPLACE_NOT_FOUND,
    AMAZON_RESPONSE_INVALID,
    AMAZON_SELLING_PARTNER_ID_REQUIRED,
    AMAZON_SP_API_RATE_LIMITED,
    AMAZON_SP_API_SERVER_ERROR,
    AMAZON_SP_API_UNAUTHORIZED,
    AMAZON_SYNC_FINALIZE_FAILED,
    AMAZON_SYNC_LEASE_LOST,
    AMAZON_SYNC_PAGINATION_LIMIT,
    AMAZON_SYNC_PAGINATION_LOOP,
    AMAZON_TOKEN_DECRYPTION_FAILED,
    AmazonError,
    amazon_selling_partner_id_required_error,
    amazon_sync_lease_lost_error,
    amazon_token_decryption_failed_error,
)
from app.models.amazon_account import AmazonAccount, AmazonAccountStatus
from app.models.amazon_listing import AmazonListing
from app.models.amazon_marketplace_participation import AmazonMarketplaceParticipation
from app.models.amazon_sync_log import AmazonSyncLog, AmazonSyncOperation, AmazonSyncStatus
from app.models.product import Product
from app.models.project import Project
from app.services.amazon_product_sync_service import AmazonProductSyncService
from tests.fixtures.amazon_a42 import (
    CANARY,
    DEFAULT_MARKETPLACE_ID,
    FAKE_A42_REFRESH_TOKEN,
    FAKE_PAGE_TOKEN,
    OTHER_FAKE_A42_REFRESH_TOKEN,
    SENSITIVE_MARKERS,
    build_listings_client_factory,
    create_sync_ready_account,
    make_product_sync_service,
    single_page_success_handler,
    wire_listings_item,
    wire_listings_page,
)


def _listings_for_account(db: Session, account_id: uuid.UUID) -> list[AmazonListing]:
    return db.query(AmazonListing).filter_by(amazon_account_id=account_id).all()


def _assert_no_sensitive_leaks(text: str) -> None:
    for marker in SENSITIVE_MARKERS:
        assert marker not in text


@pytest.mark.asyncio
async def test_sync_single_page_inserts_listing(
    a32_session_factory,
    token_encryption_service,
) -> None:
    user, summary = create_sync_ready_account(a32_session_factory, token_encryption_service)
    service = make_product_sync_service(
        token_encryption_service,
        a32_session_factory,
        single_page_success_handler,
    )
    result = await service.sync_product_listings(
        user_id=user.id,
        account_id=summary.id,
        marketplace_id=DEFAULT_MARKETPLACE_ID,
    )
    assert result.items_seen == 1
    assert result.items_written == 1
    assert result.items_deactivated == 0
    assert result.pages_seen == 1
    assert result.request_id == "req-success-123"

    verify = a32_session_factory()
    try:
        rows = _listings_for_account(verify, summary.id)
        assert len(rows) == 1
        row = rows[0]
        assert row.seller_sku == "SKU-001"
        assert row.asin == "B012345678"
        assert row.is_active is True
        assert row.last_seen_sync_id == result.sync_log_id
    finally:
        verify.close()


@pytest.mark.asyncio
async def test_sync_multi_page_inserts(
    a32_session_factory,
    token_encryption_service,
) -> None:
    user, summary = create_sync_ready_account(a32_session_factory, token_encryption_service)
    page_calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        page_calls["count"] += 1
        if page_calls["count"] == 1:
            return httpx.Response(
                200,
                json=wire_listings_page(
                    wire_listings_item(sku="SKU-P1"),
                    next_token=FAKE_PAGE_TOKEN,
                ),
                headers={"x-amzn-requestid": "req-page-1"},
            )
        return httpx.Response(
            200,
            json=wire_listings_page(wire_listings_item(sku="SKU-P2")),
            headers={"x-amzn-requestid": "req-page-2"},
        )

    service = make_product_sync_service(token_encryption_service, a32_session_factory, handler)
    result = await service.sync_product_listings(
        user_id=user.id,
        account_id=summary.id,
        marketplace_id=DEFAULT_MARKETPLACE_ID,
    )
    assert result.items_seen == 2
    assert result.pages_seen == 2
    verify = a32_session_factory()
    try:
        skus = {row.seller_sku for row in _listings_for_account(verify, summary.id)}
        assert skus == {"SKU-P1", "SKU-P2"}
    finally:
        verify.close()


@pytest.mark.asyncio
async def test_sync_mixed_insert_and_update(
    a32_session_factory,
    token_encryption_service,
) -> None:
    user, summary = create_sync_ready_account(a32_session_factory, token_encryption_service)
    service = make_product_sync_service(
        token_encryption_service,
        a32_session_factory,
        single_page_success_handler,
    )
    await service.sync_product_listings(
        user_id=user.id,
        account_id=summary.id,
        marketplace_id=DEFAULT_MARKETPLACE_ID,
    )

    def updated_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=wire_listings_page(
                wire_listings_item(sku="SKU-001", asin="B099999999"),
                wire_listings_item(sku="SKU-NEW"),
            ),
            headers={"x-amzn-requestid": "req-mixed"},
        )

    service = make_product_sync_service(token_encryption_service, a32_session_factory, updated_handler)
    result = await service.sync_product_listings(
        user_id=user.id,
        account_id=summary.id,
        marketplace_id=DEFAULT_MARKETPLACE_ID,
    )
    assert result.items_seen == 2
    assert result.items_written == 2
    verify = a32_session_factory()
    try:
        rows = {row.seller_sku: row for row in _listings_for_account(verify, summary.id)}
        assert len(rows) == 2
        assert rows["SKU-001"].asin == "B099999999"
        assert rows["SKU-NEW"].asin == "B012345678"
    finally:
        verify.close()


@pytest.mark.asyncio
async def test_sync_updates_amazon_snapshot_fields(
    a32_session_factory,
    token_encryption_service,
) -> None:
    user, summary = create_sync_ready_account(a32_session_factory, token_encryption_service)
    seed = a32_session_factory()
    now = datetime.now(tz=UTC)
    sync_id = uuid.uuid4()
    try:
        seed.add(
            AmazonListing(
                amazon_account_id=summary.id,
                marketplace_id=DEFAULT_MARKETPLACE_ID,
                seller_sku="SKU-001",
                asin="B000000001",
                status_codes=["DISCOVERABLE"],
                product_type="OLD_TYPE",
                is_active=True,
                last_seen_sync_id=sync_id,
                first_seen_at=now,
                last_seen_at=now,
                created_at=now,
                updated_at=now,
            )
        )
        seed.commit()
    finally:
        seed.close()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=wire_listings_page(
                wire_listings_item(
                    sku="SKU-001",
                    asin="B088888888",
                    product_type="NEW_TYPE",
                    status=["BUYABLE"],
                )
            ),
            headers={"x-amzn-requestid": "req-snapshot"},
        )

    service = make_product_sync_service(token_encryption_service, a32_session_factory, handler)
    await service.sync_product_listings(
        user_id=user.id,
        account_id=summary.id,
        marketplace_id=DEFAULT_MARKETPLACE_ID,
    )
    verify = a32_session_factory()
    try:
        row = (
            verify.query(AmazonListing)
            .filter_by(amazon_account_id=summary.id, seller_sku="SKU-001")
            .one()
        )
        assert row.asin == "B088888888"
        assert row.product_type == "NEW_TYPE"
        assert row.status_codes == ["BUYABLE"]
    finally:
        verify.close()


@pytest.mark.asyncio
async def test_sync_preserves_product_id(
    a32_session_factory,
    token_encryption_service,
) -> None:
    user, summary = create_sync_ready_account(a32_session_factory, token_encryption_service)
    product_id = uuid.uuid4()
    seed = a32_session_factory()
    now = datetime.now(tz=UTC)
    try:
        project = Project(user_id=user.id, name="Sync Project")
        seed.add(project)
        seed.flush()
        seed.add(
            Product(
                id=product_id,
                user_id=user.id,
                project_id=project.id,
                name="Linked Product",
            )
        )
        seed.add(
            AmazonListing(
                amazon_account_id=summary.id,
                marketplace_id=DEFAULT_MARKETPLACE_ID,
                seller_sku="SKU-001",
                product_id=product_id,
                is_active=True,
                last_seen_sync_id=uuid.uuid4(),
                first_seen_at=now,
                last_seen_at=now,
                created_at=now,
                updated_at=now,
            )
        )
        seed.commit()
    finally:
        seed.close()

    service = make_product_sync_service(
        token_encryption_service,
        a32_session_factory,
        single_page_success_handler,
    )
    await service.sync_product_listings(
        user_id=user.id,
        account_id=summary.id,
        marketplace_id=DEFAULT_MARKETPLACE_ID,
    )
    verify = a32_session_factory()
    try:
        row = (
            verify.query(AmazonListing)
            .filter_by(amazon_account_id=summary.id, seller_sku="SKU-001")
            .one()
        )
        assert row.product_id == product_id
    finally:
        verify.close()


@pytest.mark.asyncio
async def test_sync_reactivates_inactive_listing(
    a32_session_factory,
    token_encryption_service,
) -> None:
    user, summary = create_sync_ready_account(a32_session_factory, token_encryption_service)
    seed = a32_session_factory()
    now = datetime.now(tz=UTC)
    try:
        seed.add(
            AmazonListing(
                amazon_account_id=summary.id,
                marketplace_id=DEFAULT_MARKETPLACE_ID,
                seller_sku="SKU-001",
                is_active=False,
                last_seen_sync_id=uuid.uuid4(),
                first_seen_at=now,
                last_seen_at=now,
                created_at=now,
                updated_at=now,
            )
        )
        seed.commit()
    finally:
        seed.close()

    service = make_product_sync_service(
        token_encryption_service,
        a32_session_factory,
        single_page_success_handler,
    )
    await service.sync_product_listings(
        user_id=user.id,
        account_id=summary.id,
        marketplace_id=DEFAULT_MARKETPLACE_ID,
    )
    verify = a32_session_factory()
    try:
        row = (
            verify.query(AmazonListing)
            .filter_by(amazon_account_id=summary.id, seller_sku="SKU-001")
            .one()
        )
        assert row.is_active is True
    finally:
        verify.close()


@pytest.mark.asyncio
async def test_sync_soft_deactivates_unseen_listings(
    a32_session_factory,
    token_encryption_service,
) -> None:
    user, summary = create_sync_ready_account(a32_session_factory, token_encryption_service)
    seed = a32_session_factory()
    now = datetime.now(tz=UTC)
    try:
        seed.add(
            AmazonListing(
                amazon_account_id=summary.id,
                marketplace_id=DEFAULT_MARKETPLACE_ID,
                seller_sku="SKU-STALE",
                is_active=True,
                last_seen_sync_id=uuid.uuid4(),
                first_seen_at=now,
                last_seen_at=now,
                created_at=now,
                updated_at=now,
            )
        )
        seed.commit()
    finally:
        seed.close()

    service = make_product_sync_service(
        token_encryption_service,
        a32_session_factory,
        single_page_success_handler,
    )
    result = await service.sync_product_listings(
        user_id=user.id,
        account_id=summary.id,
        marketplace_id=DEFAULT_MARKETPLACE_ID,
    )
    verify = a32_session_factory()
    try:
        rows = {row.seller_sku: row for row in _listings_for_account(verify, summary.id)}
        assert rows["SKU-001"].is_active is True
        assert rows["SKU-STALE"].is_active is False
        assert result.items_deactivated == 1
    finally:
        verify.close()


@pytest.mark.asyncio
async def test_sync_does_not_affect_other_marketplace(
    a32_session_factory,
    token_encryption_service,
) -> None:
    user, summary = create_sync_ready_account(a32_session_factory, token_encryption_service)
    other_marketplace = "A1PA6795UKMFR9"
    seed = a32_session_factory()
    now = datetime.now(tz=UTC)
    try:
        seed.add(
            AmazonListing(
                amazon_account_id=summary.id,
                marketplace_id=other_marketplace,
                seller_sku="SKU-DE",
                is_active=True,
                last_seen_sync_id=uuid.uuid4(),
                first_seen_at=now,
                last_seen_at=now,
                created_at=now,
                updated_at=now,
            )
        )
        seed.commit()
    finally:
        seed.close()

    service = make_product_sync_service(
        token_encryption_service,
        a32_session_factory,
        single_page_success_handler,
    )
    await service.sync_product_listings(
        user_id=user.id,
        account_id=summary.id,
        marketplace_id=DEFAULT_MARKETPLACE_ID,
    )
    verify = a32_session_factory()
    try:
        other = (
            verify.query(AmazonListing)
            .filter_by(
                amazon_account_id=summary.id,
                marketplace_id=other_marketplace,
                seller_sku="SKU-DE",
            )
            .one()
        )
        assert other.is_active is True
    finally:
        verify.close()


@pytest.mark.asyncio
async def test_sync_does_not_affect_other_account(
    a32_session_factory,
    token_encryption_service,
) -> None:
    user_a, account_a = create_sync_ready_account(a32_session_factory, token_encryption_service)
    _user_b, account_b = create_sync_ready_account(
        a32_session_factory,
        token_encryption_service,
        token=OTHER_FAKE_A42_REFRESH_TOKEN,
    )
    seed = a32_session_factory()
    now = datetime.now(tz=UTC)
    try:
        seed.add(
            AmazonListing(
                amazon_account_id=account_b.id,
                marketplace_id=DEFAULT_MARKETPLACE_ID,
                seller_sku="SKU-OTHER",
                is_active=True,
                last_seen_sync_id=uuid.uuid4(),
                first_seen_at=now,
                last_seen_at=now,
                created_at=now,
                updated_at=now,
            )
        )
        seed.commit()
    finally:
        seed.close()

    service = make_product_sync_service(
        token_encryption_service,
        a32_session_factory,
        single_page_success_handler,
    )
    await service.sync_product_listings(
        user_id=user_a.id,
        account_id=account_a.id,
        marketplace_id=DEFAULT_MARKETPLACE_ID,
    )
    verify = a32_session_factory()
    try:
        other = (
            verify.query(AmazonListing)
            .filter_by(amazon_account_id=account_b.id, seller_sku="SKU-OTHER")
            .one()
        )
        assert other.is_active is True
    finally:
        verify.close()


@pytest.mark.asyncio
async def test_sync_empty_enumeration_deactivates_all_scoped(
    a32_session_factory,
    token_encryption_service,
) -> None:
    user, summary = create_sync_ready_account(a32_session_factory, token_encryption_service)
    seed = a32_session_factory()
    now = datetime.now(tz=UTC)
    try:
        for sku in ("SKU-A", "SKU-B"):
            seed.add(
                AmazonListing(
                    amazon_account_id=summary.id,
                    marketplace_id=DEFAULT_MARKETPLACE_ID,
                    seller_sku=sku,
                    is_active=True,
                    last_seen_sync_id=uuid.uuid4(),
                    first_seen_at=now,
                    last_seen_at=now,
                    created_at=now,
                    updated_at=now,
                )
            )
        seed.commit()
    finally:
        seed.close()

    def empty_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=wire_listings_page(),
            headers={"x-amzn-requestid": "req-empty"},
        )

    service = make_product_sync_service(token_encryption_service, a32_session_factory, empty_handler)
    result = await service.sync_product_listings(
        user_id=user.id,
        account_id=summary.id,
        marketplace_id=DEFAULT_MARKETPLACE_ID,
    )
    assert result.items_seen == 0
    assert result.items_written == 0
    assert result.items_deactivated == 2
    verify = a32_session_factory()
    try:
        rows = _listings_for_account(verify, summary.id)
        assert all(not row.is_active for row in rows)
    finally:
        verify.close()


@pytest.mark.asyncio
async def test_sync_log_fields_on_success(
    a32_session_factory,
    token_encryption_service,
) -> None:
    user, summary = create_sync_ready_account(a32_session_factory, token_encryption_service)
    service = make_product_sync_service(
        token_encryption_service,
        a32_session_factory,
        single_page_success_handler,
    )
    result = await service.sync_product_listings(
        user_id=user.id,
        account_id=summary.id,
        marketplace_id=DEFAULT_MARKETPLACE_ID,
    )
    verify = a32_session_factory()
    try:
        log = verify.get(AmazonSyncLog, result.sync_log_id)
        assert log is not None
        assert log.operation == AmazonSyncOperation.PRODUCT_SYNC
        assert log.status == AmazonSyncStatus.SUCCEEDED
        assert log.items_seen == 1
        assert log.items_written == 1
        assert log.items_deactivated == 0
        assert log.request_id == "req-success-123"
        assert log.safe_detail == {"pages_seen": 1}
        account = verify.get(AmazonAccount, summary.id)
        assert account is not None
        assert account.sync_lease_id is None
    finally:
        verify.close()


@pytest.mark.asyncio
async def test_sync_sets_last_seen_sync_id(
    a32_session_factory,
    token_encryption_service,
) -> None:
    user, summary = create_sync_ready_account(a32_session_factory, token_encryption_service)
    service = make_product_sync_service(
        token_encryption_service,
        a32_session_factory,
        single_page_success_handler,
    )
    result = await service.sync_product_listings(
        user_id=user.id,
        account_id=summary.id,
        marketplace_id=DEFAULT_MARKETPLACE_ID,
    )
    verify = a32_session_factory()
    try:
        row = (
            verify.query(AmazonListing)
            .filter_by(amazon_account_id=summary.id, seller_sku="SKU-001")
            .one()
        )
        assert row.last_seen_sync_id == result.sync_log_id
    finally:
        verify.close()


@pytest.mark.asyncio
async def test_preflight_account_not_found_for_wrong_user(
    a32_session_factory,
    token_encryption_service,
    user_factory,
) -> None:
    user, summary = create_sync_ready_account(a32_session_factory, token_encryption_service)
    other = user_factory(f"other-{uuid.uuid4()}@example.com")
    service = make_product_sync_service(
        token_encryption_service,
        a32_session_factory,
        single_page_success_handler,
    )
    with pytest.raises(AmazonError) as exc_info:
        await service.sync_product_listings(
            user_id=other.id,
            account_id=summary.id,
            marketplace_id=DEFAULT_MARKETPLACE_ID,
        )
    assert exc_info.value.error_code == AMAZON_ACCOUNT_NOT_FOUND


@pytest.mark.asyncio
async def test_preflight_disabled_account(
    a32_session_factory,
    token_encryption_service,
) -> None:
    user, summary = create_sync_ready_account(a32_session_factory, token_encryption_service)
    db = a32_session_factory()
    try:
        account = db.get(AmazonAccount, summary.id)
        assert account is not None
        account.status = AmazonAccountStatus.DISABLED
        db.commit()
    finally:
        db.close()

    service = make_product_sync_service(
        token_encryption_service,
        a32_session_factory,
        single_page_success_handler,
    )
    with pytest.raises(AmazonError) as exc_info:
        await service.sync_product_listings(
            user_id=user.id,
            account_id=summary.id,
            marketplace_id=DEFAULT_MARKETPLACE_ID,
        )
    assert exc_info.value.error_code == AMAZON_ACCOUNT_DISABLED


@pytest.mark.parametrize(
    "status",
    [
        AmazonAccountStatus.REAUTHORIZATION_REQUIRED,
        AmazonAccountStatus.ERROR,
    ],
)
@pytest.mark.asyncio
async def test_preflight_non_active_account_status(
    a32_session_factory,
    token_encryption_service,
    status: str,
) -> None:
    user, summary = create_sync_ready_account(a32_session_factory, token_encryption_service)
    db = a32_session_factory()
    try:
        account = db.get(AmazonAccount, summary.id)
        assert account is not None
        account.status = status
        db.commit()
    finally:
        db.close()

    service = make_product_sync_service(
        token_encryption_service,
        a32_session_factory,
        single_page_success_handler,
    )
    with pytest.raises(AmazonError) as exc_info:
        await service.sync_product_listings(
            user_id=user.id,
            account_id=summary.id,
            marketplace_id=DEFAULT_MARKETPLACE_ID,
        )
    assert exc_info.value.error_code == AMAZON_ACCOUNT_NOT_ACTIVE


@pytest.mark.parametrize("selling_partner_id", [None])
@pytest.mark.asyncio
async def test_preflight_missing_selling_partner_id(
    a32_session_factory,
    token_encryption_service,
    selling_partner_id: str | None,
) -> None:
    user, summary = create_sync_ready_account(a32_session_factory, token_encryption_service)
    db = a32_session_factory()
    try:
        account = db.get(AmazonAccount, summary.id)
        assert account is not None
        account.selling_partner_id = selling_partner_id
        db.commit()
    finally:
        db.close()

    service = make_product_sync_service(
        token_encryption_service,
        a32_session_factory,
        single_page_success_handler,
    )
    with pytest.raises(AmazonError) as exc_info:
        await service.sync_product_listings(
            user_id=user.id,
            account_id=summary.id,
            marketplace_id=DEFAULT_MARKETPLACE_ID,
        )
    assert exc_info.value.error_code == AMAZON_SELLING_PARTNER_ID_REQUIRED


@pytest.mark.asyncio
async def test_preflight_participation_missing(
    a32_session_factory,
    token_encryption_service,
) -> None:
    user, summary = create_sync_ready_account(a32_session_factory, token_encryption_service)
    db = a32_session_factory()
    try:
        db.query(AmazonMarketplaceParticipation).filter_by(amazon_account_id=summary.id).delete()
        db.commit()
    finally:
        db.close()

    service = make_product_sync_service(
        token_encryption_service,
        a32_session_factory,
        single_page_success_handler,
    )
    with pytest.raises(AmazonError) as exc_info:
        await service.sync_product_listings(
            user_id=user.id,
            account_id=summary.id,
            marketplace_id=DEFAULT_MARKETPLACE_ID,
        )
    assert exc_info.value.error_code == AMAZON_MARKETPLACE_NOT_FOUND


@pytest.mark.asyncio
async def test_preflight_participation_inactive(
    a32_session_factory,
    token_encryption_service,
) -> None:
    user, summary = create_sync_ready_account(
        a32_session_factory,
        token_encryption_service,
        participation_active=False,
    )
    service = make_product_sync_service(
        token_encryption_service,
        a32_session_factory,
        single_page_success_handler,
    )
    with pytest.raises(AmazonError) as exc_info:
        await service.sync_product_listings(
            user_id=user.id,
            account_id=summary.id,
            marketplace_id=DEFAULT_MARKETPLACE_ID,
        )
    assert exc_info.value.error_code == AMAZON_MARKETPLACE_INACTIVE


@pytest.mark.asyncio
async def test_preflight_participation_not_participating(
    a32_session_factory,
    token_encryption_service,
) -> None:
    user, summary = create_sync_ready_account(
        a32_session_factory,
        token_encryption_service,
        participating=False,
    )
    service = make_product_sync_service(
        token_encryption_service,
        a32_session_factory,
        single_page_success_handler,
    )
    with pytest.raises(AmazonError) as exc_info:
        await service.sync_product_listings(
            user_id=user.id,
            account_id=summary.id,
            marketplace_id=DEFAULT_MARKETPLACE_ID,
        )
    assert exc_info.value.error_code == AMAZON_MARKETPLACE_NOT_ELIGIBLE


@pytest.mark.asyncio
async def test_preflight_participation_suspended(
    a32_session_factory,
    token_encryption_service,
) -> None:
    user, summary = create_sync_ready_account(
        a32_session_factory,
        token_encryption_service,
        suspended_listings=True,
    )
    service = make_product_sync_service(
        token_encryption_service,
        a32_session_factory,
        single_page_success_handler,
    )
    with pytest.raises(AmazonError) as exc_info:
        await service.sync_product_listings(
            user_id=user.id,
            account_id=summary.id,
            marketplace_id=DEFAULT_MARKETPLACE_ID,
        )
    assert exc_info.value.error_code == AMAZON_MARKETPLACE_NOT_ELIGIBLE


@pytest.mark.asyncio
async def test_second_page_failure_leaves_listings_unchanged(
    a32_session_factory,
    token_encryption_service,
) -> None:
    user, summary = create_sync_ready_account(a32_session_factory, token_encryption_service)
    seed = a32_session_factory()
    now = datetime.now(tz=UTC)
    try:
        seed.add(
            AmazonListing(
                amazon_account_id=summary.id,
                marketplace_id=DEFAULT_MARKETPLACE_ID,
                seller_sku="SKU-EXISTING",
                is_active=True,
                last_seen_sync_id=uuid.uuid4(),
                first_seen_at=now,
                last_seen_at=now,
                created_at=now,
                updated_at=now,
            )
        )
        seed.commit()
    finally:
        seed.close()

    page_calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        page_calls["count"] += 1
        if page_calls["count"] == 1:
            return httpx.Response(
                200,
                json=wire_listings_page(
                    wire_listings_item(sku="SKU-P1"),
                    next_token=FAKE_PAGE_TOKEN,
                ),
                headers={"x-amzn-requestid": "req-p1"},
            )
        return httpx.Response(500, json={"errors": []}, headers={"x-amzn-requestid": "req-p2-fail"})

    service = make_product_sync_service(token_encryption_service, a32_session_factory, handler)
    with pytest.raises(AmazonError) as exc_info:
        await service.sync_product_listings(
            user_id=user.id,
            account_id=summary.id,
            marketplace_id=DEFAULT_MARKETPLACE_ID,
        )
    assert exc_info.value.error_code == AMAZON_SP_API_SERVER_ERROR

    verify = a32_session_factory()
    try:
        rows = _listings_for_account(verify, summary.id)
        assert len(rows) == 1
        assert rows[0].seller_sku == "SKU-EXISTING"
        assert rows[0].is_active is True
    finally:
        verify.close()


@pytest.mark.asyncio
async def test_duplicate_next_page_token_fails(
    a32_session_factory,
    token_encryption_service,
) -> None:
    user, summary = create_sync_ready_account(a32_session_factory, token_encryption_service)
    token = "LOOP-TOKEN-ABC"
    page_calls = {"count": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        page_calls["count"] += 1
        if page_calls["count"] == 1:
            return httpx.Response(
                200,
                json=wire_listings_page(wire_listings_item(sku="SKU-1"), next_token=token),
            )
        return httpx.Response(
            200,
            json=wire_listings_page(wire_listings_item(sku="SKU-2"), next_token=token),
        )

    service = make_product_sync_service(token_encryption_service, a32_session_factory, handler)
    with pytest.raises(AmazonError) as exc_info:
        await service.sync_product_listings(
            user_id=user.id,
            account_id=summary.id,
            marketplace_id=DEFAULT_MARKETPLACE_ID,
        )
    assert exc_info.value.error_code == AMAZON_SYNC_PAGINATION_LOOP


@pytest.mark.asyncio
async def test_self_loop_page_token_fails(
    a32_session_factory,
    token_encryption_service,
) -> None:
    user, summary = create_sync_ready_account(a32_session_factory, token_encryption_service)

    def handler(request: httpx.Request) -> httpx.Response:
        if "pageToken=" in str(request.url):
            return httpx.Response(
                200,
                json=wire_listings_page(
                    wire_listings_item(sku="SKU-2"),
                    next_token=FAKE_PAGE_TOKEN,
                ),
            )
        return httpx.Response(
            200,
            json=wire_listings_page(
                wire_listings_item(sku="SKU-1"),
                next_token=FAKE_PAGE_TOKEN,
            ),
        )

    service = make_product_sync_service(token_encryption_service, a32_session_factory, handler)
    with pytest.raises(AmazonError) as exc_info:
        await service.sync_product_listings(
            user_id=user.id,
            account_id=summary.id,
            marketplace_id=DEFAULT_MARKETPLACE_ID,
        )
    assert exc_info.value.error_code == AMAZON_SYNC_PAGINATION_LOOP


@pytest.mark.asyncio
async def test_cross_page_duplicate_identity_fails(
    a32_session_factory,
    token_encryption_service,
) -> None:
    user, summary = create_sync_ready_account(a32_session_factory, token_encryption_service)
    page_calls = {"count": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        page_calls["count"] += 1
        if page_calls["count"] == 1:
            return httpx.Response(
                200,
                json=wire_listings_page(
                    wire_listings_item(sku="SKU-DUP"),
                    next_token=FAKE_PAGE_TOKEN,
                ),
            )
        return httpx.Response(
            200,
            json=wire_listings_page(wire_listings_item(sku="SKU-DUP")),
        )

    service = make_product_sync_service(token_encryption_service, a32_session_factory, handler)
    with pytest.raises(AmazonError) as exc_info:
        await service.sync_product_listings(
            user_id=user.id,
            account_id=summary.id,
            marketplace_id=DEFAULT_MARKETPLACE_ID,
        )
    assert exc_info.value.error_code == AMAZON_RESPONSE_INVALID


@pytest.mark.asyncio
async def test_exceeds_max_sync_pages(
    a32_session_factory,
    token_encryption_service,
) -> None:
    user, summary = create_sync_ready_account(a32_session_factory, token_encryption_service)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=wire_listings_page(wire_listings_item(), next_token=FAKE_PAGE_TOKEN),
        )

    service = make_product_sync_service(token_encryption_service, a32_session_factory, handler)
    with patch(
        "app.services.amazon_product_sync_service.MAX_SYNC_PAGES",
        1,
    ):
        with pytest.raises(AmazonError) as exc_info:
            await service.sync_product_listings(
                user_id=user.id,
                account_id=summary.id,
                marketplace_id=DEFAULT_MARKETPLACE_ID,
            )
    assert exc_info.value.error_code == AMAZON_SYNC_PAGINATION_LIMIT


@pytest.mark.asyncio
async def test_exceeds_max_sync_items(
    a32_session_factory,
    token_encryption_service,
) -> None:
    user, summary = create_sync_ready_account(a32_session_factory, token_encryption_service)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=wire_listings_page(
                wire_listings_item(sku="SKU-1"),
                wire_listings_item(sku="SKU-2"),
            ),
        )

    service = make_product_sync_service(token_encryption_service, a32_session_factory, handler)
    with patch(
        "app.services.amazon_product_sync_service.MAX_SYNC_ITEMS",
        1,
    ):
        with pytest.raises(AmazonError) as exc_info:
            await service.sync_product_listings(
                user_id=user.id,
                account_id=summary.id,
                marketplace_id=DEFAULT_MARKETPLACE_ID,
            )
    assert exc_info.value.error_code == AMAZON_SYNC_PAGINATION_LIMIT


@pytest.mark.asyncio
async def test_failure_finalize_clears_lease_and_marks_log_failed(
    a32_session_factory,
    token_encryption_service,
) -> None:
    user, summary = create_sync_ready_account(a32_session_factory, token_encryption_service)

    def fail_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"errors": []}, headers={"x-amzn-requestid": "req-fail"})

    service = make_product_sync_service(token_encryption_service, a32_session_factory, fail_handler)
    with pytest.raises(AmazonError) as exc_info:
        await service.sync_product_listings(
            user_id=user.id,
            account_id=summary.id,
            marketplace_id=DEFAULT_MARKETPLACE_ID,
        )
    assert exc_info.value.error_code == AMAZON_SP_API_SERVER_ERROR

    verify = a32_session_factory()
    try:
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
        assert log.error_code == AMAZON_SP_API_SERVER_ERROR
    finally:
        verify.close()


@pytest.mark.asyncio
async def test_non_auth_error_keeps_account_active(
    a32_session_factory,
    token_encryption_service,
) -> None:
    user, summary = create_sync_ready_account(a32_session_factory, token_encryption_service)

    def rate_limit_handler(request: httpx.Request) -> httpx.Response:
        if "mock.lwa.local" in str(request.url):
            from tests.integrations.amazon.conftest import lwa_success_handler

            return lwa_success_handler(refresh_token=FAKE_A42_REFRESH_TOKEN)(request)
        return httpx.Response(429, json={"errors": []}, headers={"x-amzn-requestid": "req-429"})

    service = make_product_sync_service(token_encryption_service, a32_session_factory, rate_limit_handler)
    with pytest.raises(AmazonError) as exc_info:
        await service.sync_product_listings(
            user_id=user.id,
            account_id=summary.id,
            marketplace_id=DEFAULT_MARKETPLACE_ID,
        )
    assert exc_info.value.error_code == AMAZON_SP_API_RATE_LIMITED

    verify = a32_session_factory()
    try:
        account = verify.get(AmazonAccount, summary.id)
        assert account is not None
        assert account.status == AmazonAccountStatus.ACTIVE
    finally:
        verify.close()


@pytest.mark.asyncio
async def test_unauthorized_sets_reauthorization_required(
    a32_session_factory,
    token_encryption_service,
) -> None:
    user, summary = create_sync_ready_account(a32_session_factory, token_encryption_service)

    def handler(request: httpx.Request) -> httpx.Response:
        if "mock.lwa.local" in str(request.url):
            from tests.integrations.amazon.conftest import lwa_success_handler

            return lwa_success_handler(refresh_token=FAKE_A42_REFRESH_TOKEN)(request)
        return httpx.Response(401, json={"errors": []}, headers={"x-amzn-requestid": "req-401"})

    service = make_product_sync_service(token_encryption_service, a32_session_factory, handler)
    with pytest.raises(AmazonError) as exc_info:
        await service.sync_product_listings(
            user_id=user.id,
            account_id=summary.id,
            marketplace_id=DEFAULT_MARKETPLACE_ID,
        )
    assert exc_info.value.error_code == AMAZON_SP_API_UNAUTHORIZED
    verify = a32_session_factory()
    try:
        account = verify.get(AmazonAccount, summary.id)
        assert account is not None
        assert account.status == AmazonAccountStatus.REAUTHORIZATION_REQUIRED
    finally:
        verify.close()


@pytest.mark.asyncio
async def test_forbidden_sets_reauthorization_required(
    a32_session_factory,
    token_encryption_service,
) -> None:
    user, summary = create_sync_ready_account(a32_session_factory, token_encryption_service)

    def handler(request: httpx.Request) -> httpx.Response:
        if "mock.lwa.local" in str(request.url):
            from tests.integrations.amazon.conftest import lwa_success_handler

            return lwa_success_handler(refresh_token=FAKE_A42_REFRESH_TOKEN)(request)
        return httpx.Response(403, json={"errors": []}, headers={"x-amzn-requestid": "req-403"})

    service = make_product_sync_service(token_encryption_service, a32_session_factory, handler)
    with pytest.raises(AmazonError):
        await service.sync_product_listings(
            user_id=user.id,
            account_id=summary.id,
            marketplace_id=DEFAULT_MARKETPLACE_ID,
        )
    verify = a32_session_factory()
    try:
        account = verify.get(AmazonAccount, summary.id)
        assert account is not None
        assert account.status == AmazonAccountStatus.REAUTHORIZATION_REQUIRED
    finally:
        verify.close()


@pytest.mark.asyncio
async def test_lwa_invalid_sets_reauthorization_required(
    a32_session_factory,
    token_encryption_service,
) -> None:
    user, summary = create_sync_ready_account(a32_session_factory, token_encryption_service)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=wire_listings_page())

    def lwa_invalid_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "invalid_grant"})

    service = AmazonProductSyncService(
        session_factory=a32_session_factory,
        encryption_service=token_encryption_service,
        listings_client_factory=build_listings_client_factory(
            refresh_token=FAKE_A42_REFRESH_TOKEN,
            sp_api_handler=handler,
            lwa_handler=lwa_invalid_handler,
        ),
        min_lease_seconds=1,
        max_lease_seconds=3600,
    )
    with pytest.raises(AmazonError) as exc_info:
        await service.sync_product_listings(
            user_id=user.id,
            account_id=summary.id,
            marketplace_id=DEFAULT_MARKETPLACE_ID,
        )
    assert exc_info.value.error_code == AMAZON_LWA_TOKEN_INVALID
    verify = a32_session_factory()
    try:
        account = verify.get(AmazonAccount, summary.id)
        assert account is not None
        assert account.status == AmazonAccountStatus.REAUTHORIZATION_REQUIRED
    finally:
        verify.close()


@pytest.mark.asyncio
async def test_errors_do_not_leak_sensitive_markers(
    a32_session_factory,
    token_encryption_service,
    caplog,
) -> None:
    user, summary = create_sync_ready_account(a32_session_factory, token_encryption_service)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=wire_listings_page(
                wire_listings_item(sku="SKU-1"),
                next_token=FAKE_PAGE_TOKEN,
            ),
        )

    service = make_product_sync_service(token_encryption_service, a32_session_factory, handler)
    with patch("app.services.amazon_product_sync_service.MAX_SYNC_PAGES", 1):
        with pytest.raises(AmazonError) as exc_info:
            await service.sync_product_listings(
                user_id=user.id,
                account_id=summary.id,
                marketplace_id=DEFAULT_MARKETPLACE_ID,
            )
    _assert_no_sensitive_leaks(str(exc_info.value))
    _assert_no_sensitive_leaks(repr(exc_info.value))
    for record in caplog.records:
        _assert_no_sensitive_leaks(record.getMessage())


@pytest.mark.asyncio
async def test_no_open_db_session_during_client_calls(
    a32_session_factory,
    token_encryption_service,
) -> None:
    user, summary = create_sync_ready_account(a32_session_factory, token_encryption_service)
    open_sessions: list[Session] = []

    def tracked_session_factory() -> Session:
        session = a32_session_factory()
        open_sessions.append(session)
        original_close = session.close

        def tracked_close() -> None:
            if session in open_sessions:
                open_sessions.remove(session)
            original_close()

        session.close = tracked_close  # type: ignore[method-assign]
        return session

    service = AmazonProductSyncService(
        session_factory=tracked_session_factory,
        encryption_service=token_encryption_service,
        listings_client_factory=build_listings_client_factory(
            refresh_token=FAKE_A42_REFRESH_TOKEN,
            sp_api_handler=single_page_success_handler,
        ),
        min_lease_seconds=1,
        max_lease_seconds=3600,
    )
    observed: dict[str, int] = {"open_during_fetch": -1}
    original_fetch = service._fetch_all_listings

    async def fetch_wrapper(*args, **kwargs):
        observed["open_during_fetch"] = len(open_sessions)
        return await original_fetch(*args, **kwargs)

    service._fetch_all_listings = fetch_wrapper  # type: ignore[method-assign]
    await service.sync_product_listings(
        user_id=user.id,
        account_id=summary.id,
        marketplace_id=DEFAULT_MARKETPLACE_ID,
    )
    assert observed["open_during_fetch"] == 0


@pytest.mark.asyncio
async def test_finalize_db_failure_returns_stable_error(
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
        side_effect=RuntimeError(f"db finalize boom {CANARY}"),
    ):
        with pytest.raises(AmazonError) as exc_info:
            await service.sync_product_listings(
                user_id=user.id,
                account_id=summary.id,
                marketplace_id=DEFAULT_MARKETPLACE_ID,
            )
    assert exc_info.value.error_code == AMAZON_SYNC_FINALIZE_FAILED
    _assert_no_sensitive_leaks(str(exc_info.value))
    _assert_no_sensitive_leaks(repr(exc_info.value))
    for record in caplog.records:
        _assert_no_sensitive_leaks(record.getMessage())


@pytest.mark.asyncio
async def test_credential_load_amazon_error_finalizes_and_reraises(
    a32_session_factory,
    token_encryption_service,
) -> None:
    user, summary = create_sync_ready_account(a32_session_factory, token_encryption_service)
    service = make_product_sync_service(
        token_encryption_service,
        a32_session_factory,
        single_page_success_handler,
    )
    with patch.object(
        service,
        "_load_sync_credentials",
        side_effect=amazon_selling_partner_id_required_error(),
    ):
        with pytest.raises(AmazonError) as exc_info:
            await service.sync_product_listings(
                user_id=user.id,
                account_id=summary.id,
                marketplace_id=DEFAULT_MARKETPLACE_ID,
            )
    assert exc_info.value.error_code == AMAZON_SELLING_PARTNER_ID_REQUIRED

    verify = a32_session_factory()
    try:
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
        assert log.error_code == AMAZON_SELLING_PARTNER_ID_REQUIRED
    finally:
        verify.close()


@pytest.mark.asyncio
async def test_credential_load_lease_lost_does_not_modify_state(
    a32_session_factory,
    token_encryption_service,
) -> None:
    user, summary = create_sync_ready_account(a32_session_factory, token_encryption_service)
    seed = a32_session_factory()
    now = datetime.now(tz=UTC)
    try:
        seed.add(
            AmazonListing(
                amazon_account_id=summary.id,
                marketplace_id=DEFAULT_MARKETPLACE_ID,
                seller_sku="SKU-EXISTING",
                is_active=True,
                last_seen_sync_id=uuid.uuid4(),
                first_seen_at=now,
                last_seen_at=now,
                created_at=now,
                updated_at=now,
            )
        )
        seed.commit()
    finally:
        seed.close()

    service = make_product_sync_service(
        token_encryption_service,
        a32_session_factory,
        single_page_success_handler,
    )
    with patch.object(
        service,
        "_load_sync_credentials",
        side_effect=amazon_sync_lease_lost_error(),
    ):
        with pytest.raises(AmazonError) as exc_info:
            await service.sync_product_listings(
                user_id=user.id,
                account_id=summary.id,
                marketplace_id=DEFAULT_MARKETPLACE_ID,
            )
    assert exc_info.value.error_code == AMAZON_SYNC_LEASE_LOST

    verify = a32_session_factory()
    try:
        account = verify.get(AmazonAccount, summary.id)
        assert account is not None
        assert account.status == AmazonAccountStatus.ACTIVE
        log = (
            verify.query(AmazonSyncLog)
            .filter_by(amazon_account_id=summary.id)
            .order_by(AmazonSyncLog.created_at.desc())
            .first()
        )
        assert log is not None
        assert log.status == AmazonSyncStatus.PROCESSING
        row = (
            verify.query(AmazonListing)
            .filter_by(amazon_account_id=summary.id, seller_sku="SKU-EXISTING")
            .one()
        )
        assert row.is_active is True
    finally:
        verify.close()


@pytest.mark.asyncio
async def test_credential_load_unexpected_error_finalizes_without_leaking(
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
        service,
        "_load_sync_credentials",
        side_effect=RuntimeError(f"credential load boom {CANARY}"),
    ):
        with pytest.raises(AmazonError) as exc_info:
            await service.sync_product_listings(
                user_id=user.id,
                account_id=summary.id,
                marketplace_id=DEFAULT_MARKETPLACE_ID,
            )
    assert exc_info.value.error_code == AMAZON_SYNC_FINALIZE_FAILED
    _assert_no_sensitive_leaks(str(exc_info.value))
    _assert_no_sensitive_leaks(repr(exc_info.value))
    for record in caplog.records:
        _assert_no_sensitive_leaks(record.getMessage())

    verify = a32_session_factory()
    try:
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


@pytest.mark.asyncio
async def test_token_decrypt_failure_finalizes_and_reraises(
    a32_session_factory,
    token_encryption_service,
) -> None:
    user, summary = create_sync_ready_account(a32_session_factory, token_encryption_service)
    service = make_product_sync_service(
        token_encryption_service,
        a32_session_factory,
        single_page_success_handler,
    )
    with patch.object(
        token_encryption_service,
        "decrypt_refresh_token",
        side_effect=amazon_token_decryption_failed_error(),
    ):
        with pytest.raises(AmazonError) as exc_info:
            await service.sync_product_listings(
                user_id=user.id,
                account_id=summary.id,
                marketplace_id=DEFAULT_MARKETPLACE_ID,
            )
    assert exc_info.value.error_code == AMAZON_TOKEN_DECRYPTION_FAILED

    verify = a32_session_factory()
    try:
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
        assert log.error_code == AMAZON_TOKEN_DECRYPTION_FAILED
    finally:
        verify.close()
