from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest
from sqlalchemy.orm import Session

from app.integrations.amazon.exceptions import (
    AMAZON_RESPONSE_INVALID,
    AMAZON_SP_API_RATE_LIMITED,
    AMAZON_SYNC_FINALIZE_FAILED,
    AmazonError,
)
from app.models.amazon_account import AmazonAccount, AmazonAccountStatus
from app.models.amazon_marketplace_participation import AmazonMarketplaceParticipation
from app.models.amazon_sync_log import AmazonSyncLog, AmazonSyncStatus
from app.services.amazon_marketplace_refresh_service import AmazonMarketplaceRefreshService
from tests.fixtures.amazon_a32 import (
    FAKE_A32_REFRESH_TOKEN,
    OTHER_FAKE_A32_REFRESH_TOKEN,
    build_sellers_client_factory,
    create_committed_account,
    wire_item,
    wire_response,
)


def _success_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json=wire_response(wire_item()),
        headers={"x-amzn-requestid": "req-success-123"},
    )


def _duplicate_marketplace_handler(request: httpx.Request) -> httpx.Response:
    item = wire_item()
    return httpx.Response(
        200,
        json=wire_response(item, item),
        headers={"x-amzn-requestid": "req-dup"},
    )


def _unauthorized_handler(request: httpx.Request) -> httpx.Response:
    if "mock.lwa.local" in str(request.url):
        return httpx.Response(400, json={"error": "invalid_grant"})
    return httpx.Response(401, json={"errors": []}, headers={"x-amzn-requestid": "req-unauth"})


def _rate_limit_handler(request: httpx.Request) -> httpx.Response:
    if "mock.lwa.local" in str(request.url):
        from tests.integrations.amazon.conftest import lwa_success_handler

        return lwa_success_handler(refresh_token=FAKE_A32_REFRESH_TOKEN)(request)
    return httpx.Response(429, json={"errors": []}, headers={"x-amzn-requestid": "req-429"})


def _make_refresh_service(token_encryption_service, a32_session_factory, handler) -> AmazonMarketplaceRefreshService:
    return AmazonMarketplaceRefreshService(
        session_factory=a32_session_factory,
        encryption_service=token_encryption_service,
        sellers_client_factory=build_sellers_client_factory(
            refresh_token=FAKE_A32_REFRESH_TOKEN,
            sp_api_handler=handler,
        ),
        min_lease_seconds=1,
        max_lease_seconds=3600,
    )


@pytest.mark.asyncio
async def test_refresh_success_upserts_participation(
    a32_session_factory,
    user_factory,
    token_encryption_service,
    refresh_service: AmazonMarketplaceRefreshService,
) -> None:
    user, summary = create_committed_account(
        a32_session_factory,
        token_encryption_service,
        token=FAKE_A32_REFRESH_TOKEN,
    )
    result = await refresh_service.refresh_marketplace_participations(
        user_id=user.id,
        account_id=summary.id,
    )
    assert result.items_seen == 1
    verify = a32_session_factory()
    try:
        account = verify.get(AmazonAccount, summary.id)
        assert account is not None
        assert account.status == AmazonAccountStatus.ACTIVE
        assert account.sync_lease_id is None
        rows = verify.query(AmazonMarketplaceParticipation).filter_by(amazon_account_id=summary.id).all()
        assert len(rows) == 1
        assert rows[0].sync_eligible is True
        log = verify.get(AmazonSyncLog, result.sync_log_id)
        assert log is not None
        assert log.status == AmazonSyncStatus.SUCCEEDED
    finally:
        verify.close()


@pytest.mark.asyncio
async def test_refresh_soft_deactivates_missing_marketplaces(
    a32_session_factory,
    user_factory,
    token_encryption_service,
) -> None:
    user, summary = create_committed_account(
        a32_session_factory,
        token_encryption_service,
        token=FAKE_A32_REFRESH_TOKEN,
    )
    seed = a32_session_factory()
    try:
        seed.add(
            AmazonMarketplaceParticipation(
                amazon_account_id=summary.id,
                marketplace_id="OLDMARKET",
                marketplace_name="Old",
                country_code="US",
                participating=True,
                suspended_listings=False,
                is_active=True,
            )
        )
        seed.commit()
    finally:
        seed.close()

    service = _make_refresh_service(token_encryption_service, a32_session_factory, _success_handler)
    result = await service.refresh_marketplace_participations(
        user_id=user.id,
        account_id=summary.id,
    )
    verify = a32_session_factory()
    try:
        rows = {
            row.marketplace_id: row
            for row in verify.query(AmazonMarketplaceParticipation)
            .filter_by(amazon_account_id=summary.id)
            .all()
        }
        assert rows["ATVPDKIKX0DER"].is_active is True
        assert rows["OLDMARKET"].is_active is False
        assert result.items_deactivated == 1
    finally:
        verify.close()


@pytest.mark.asyncio
async def test_refresh_does_not_affect_other_account(
    a32_session_factory,
    user_factory,
    token_encryption_service,
) -> None:
    user_a, account_a = create_committed_account(
        a32_session_factory,
        token_encryption_service,
        token=FAKE_A32_REFRESH_TOKEN,
    )
    user_b, account_b = create_committed_account(
        a32_session_factory,
        token_encryption_service,
        token=OTHER_FAKE_A32_REFRESH_TOKEN,
    )
    seed = a32_session_factory()
    try:
        seed.add(
            AmazonMarketplaceParticipation(
                amazon_account_id=account_b.id,
                marketplace_id="OTHERONLY",
                marketplace_name="Other",
                country_code="US",
                participating=True,
                suspended_listings=False,
                is_active=True,
            )
        )
        seed.commit()
    finally:
        seed.close()

    service = _make_refresh_service(token_encryption_service, a32_session_factory, _success_handler)
    await service.refresh_marketplace_participations(
        user_id=user_a.id,
        account_id=account_a.id,
    )
    verify = a32_session_factory()
    try:
        other_row = (
            verify.query(AmazonMarketplaceParticipation)
            .filter_by(amazon_account_id=account_b.id, marketplace_id="OTHERONLY")
            .one()
        )
        assert other_row.is_active is True
    finally:
        verify.close()


@pytest.mark.asyncio
async def test_duplicate_marketplace_id_fails_without_partial_write(
    a32_session_factory,
    user_factory,
    token_encryption_service,
) -> None:
    user, summary = create_committed_account(
        a32_session_factory,
        token_encryption_service,
        token=FAKE_A32_REFRESH_TOKEN,
    )
    service = _make_refresh_service(
        token_encryption_service,
        a32_session_factory,
        _duplicate_marketplace_handler,
    )
    with pytest.raises(AmazonError) as exc_info:
        await service.refresh_marketplace_participations(
            user_id=user.id,
            account_id=summary.id,
        )
    assert exc_info.value.error_code == AMAZON_RESPONSE_INVALID
    verify = a32_session_factory()
    try:
        assert (
            verify.query(AmazonMarketplaceParticipation)
            .filter_by(amazon_account_id=summary.id)
            .count()
            == 0
        )
    finally:
        verify.close()


@pytest.mark.asyncio
async def test_authorization_failure_sets_reauthorization_required(
    a32_session_factory,
    user_factory,
    token_encryption_service,
) -> None:
    user, summary = create_committed_account(
        a32_session_factory,
        token_encryption_service,
        token=FAKE_A32_REFRESH_TOKEN,
    )
    service = _make_refresh_service(
        token_encryption_service,
        a32_session_factory,
        _unauthorized_handler,
    )
    with pytest.raises(AmazonError):
        await service.refresh_marketplace_participations(
            user_id=user.id,
            account_id=summary.id,
        )
    verify = a32_session_factory()
    try:
        account = verify.get(AmazonAccount, summary.id)
        assert account is not None
        assert account.status == AmazonAccountStatus.REAUTHORIZATION_REQUIRED
    finally:
        verify.close()


@pytest.mark.asyncio
async def test_rate_limit_does_not_set_reauthorization_required(
    a32_session_factory,
    user_factory,
    token_encryption_service,
) -> None:
    user, summary = create_committed_account(
        a32_session_factory,
        token_encryption_service,
        token=FAKE_A32_REFRESH_TOKEN,
    )
    service = _make_refresh_service(token_encryption_service, a32_session_factory, _rate_limit_handler)
    with pytest.raises(AmazonError) as exc_info:
        await service.refresh_marketplace_participations(
            user_id=user.id,
            account_id=summary.id,
        )
    assert exc_info.value.error_code == AMAZON_SP_API_RATE_LIMITED
    verify = a32_session_factory()
    try:
        account = verify.get(AmazonAccount, summary.id)
        assert account is not None
        assert account.status == AmazonAccountStatus.ERROR
    finally:
        verify.close()


@pytest.mark.asyncio
async def test_tx1_committed_before_external_call(
    a32_session_factory,
    user_factory,
    token_encryption_service,
) -> None:
    user, summary = create_committed_account(
        a32_session_factory,
        token_encryption_service,
        token=FAKE_A32_REFRESH_TOKEN,
    )
    service = _make_refresh_service(token_encryption_service, a32_session_factory, _success_handler)
    observed: dict[str, bool] = {"during_fetch": False}

    original_fetch = service._fetch_participations

    async def fetch_wrapper(encrypted, user_id, account_id):
        verify = a32_session_factory()
        try:
            account = verify.get(AmazonAccount, summary.id)
            observed["during_fetch"] = account is not None and account.sync_lease_id is not None
        finally:
            verify.close()
        return await original_fetch(
            encrypted=encrypted,
            user_id=user_id,
            account_id=account_id,
        )

    service._fetch_participations = fetch_wrapper  # type: ignore[method-assign]
    await service.refresh_marketplace_participations(
        user_id=user.id,
        account_id=summary.id,
    )
    assert observed["during_fetch"] is True


@pytest.mark.asyncio
async def test_finalize_failure_returns_stable_error(
    a32_session_factory,
    user_factory,
    token_encryption_service,
) -> None:
    user, summary = create_committed_account(
        a32_session_factory,
        token_encryption_service,
        token=FAKE_A32_REFRESH_TOKEN,
    )
    service = _make_refresh_service(token_encryption_service, a32_session_factory, _success_handler)
    with patch.object(
        AmazonMarketplaceRefreshService,
        "_upsert_participations",
        side_effect=RuntimeError("db finalize boom"),
    ):
        with pytest.raises(AmazonError) as exc_info:
            await service.refresh_marketplace_participations(
                user_id=user.id,
                account_id=summary.id,
            )
    assert exc_info.value.error_code == AMAZON_SYNC_FINALIZE_FAILED


@pytest.mark.asyncio
async def test_reactivate_soft_deactivated_marketplace(
    a32_session_factory,
    token_encryption_service,
) -> None:
    user, summary = create_committed_account(
        a32_session_factory,
        token_encryption_service,
        token=FAKE_A32_REFRESH_TOKEN,
    )
    service = _make_refresh_service(token_encryption_service, a32_session_factory, _success_handler)
    await service.refresh_marketplace_participations(user_id=user.id, account_id=summary.id)

    seed = a32_session_factory()
    try:
        row = (
            seed.query(AmazonMarketplaceParticipation)
            .filter_by(amazon_account_id=summary.id, marketplace_id="ATVPDKIKX0DER")
            .one()
        )
        row.is_active = False
        seed.commit()
    finally:
        seed.close()

    await service.refresh_marketplace_participations(user_id=user.id, account_id=summary.id)
    verify = a32_session_factory()
    try:
        row = (
            verify.query(AmazonMarketplaceParticipation)
            .filter_by(amazon_account_id=summary.id, marketplace_id="ATVPDKIKX0DER")
            .one()
        )
        assert row.is_active is True
    finally:
        verify.close()


@pytest.mark.asyncio
async def test_disable_during_external_call_keeps_account_disabled(
    a32_session_factory,
    token_encryption_service,
) -> None:
    import asyncio

    from app.integrations.amazon.exceptions import AMAZON_ACCOUNT_DISABLED, AMAZON_SYNC_LEASE_LOST
    from app.services.amazon_account_service import AmazonAccountService

    user, summary = create_committed_account(
        a32_session_factory,
        token_encryption_service,
        token=FAKE_A32_REFRESH_TOKEN,
    )
    service = _make_refresh_service(token_encryption_service, a32_session_factory, _success_handler)
    gate = asyncio.Event()
    release = asyncio.Event()
    original_fetch = service._fetch_participations

    async def gated_fetch(encrypted, user_id, account_id):
        gate.set()
        await release.wait()
        return await original_fetch(
            encrypted=encrypted,
            user_id=user_id,
            account_id=account_id,
        )

    service._fetch_participations = gated_fetch  # type: ignore[method-assign]
    task = asyncio.create_task(
        service.refresh_marketplace_participations(
            user_id=user.id,
            account_id=summary.id,
        )
    )
    await asyncio.wait_for(gate.wait(), timeout=5)

    disable_db = a32_session_factory()
    try:
        AmazonAccountService(disable_db, token_encryption_service).disable_account(
            user_id=user.id,
            account_id=summary.id,
        )
    finally:
        disable_db.close()

    release.set()
    with pytest.raises(AmazonError) as exc_info:
        await asyncio.wait_for(task, timeout=5)
    assert exc_info.value.error_code == AMAZON_SYNC_LEASE_LOST

    verify = a32_session_factory()
    try:
        account = verify.get(AmazonAccount, summary.id)
        assert account is not None
        assert account.status == AmazonAccountStatus.DISABLED
        assert (
            verify.query(AmazonMarketplaceParticipation)
            .filter_by(amazon_account_id=summary.id)
            .count()
            == 0
        )
        failed_logs = (
            verify.query(AmazonSyncLog)
            .filter_by(amazon_account_id=summary.id, status=AmazonSyncStatus.FAILED)
            .all()
        )
        assert failed_logs
        assert any(log.error_code == AMAZON_ACCOUNT_DISABLED for log in failed_logs)
        assert FAKE_A32_REFRESH_TOKEN not in repr(failed_logs)
    finally:
        verify.close()


@pytest.mark.asyncio
async def test_expired_lease_during_external_call_cannot_finalize_success(
    a32_session_factory,
    token_encryption_service,
) -> None:
    import asyncio
    from datetime import UTC, datetime, timedelta

    from app.integrations.amazon.exceptions import AMAZON_SYNC_LEASE_LOST

    user, summary = create_committed_account(
        a32_session_factory,
        token_encryption_service,
        token=FAKE_A32_REFRESH_TOKEN,
    )
    clock_start = datetime.now(UTC)

    class FixedClock:
        def __init__(self) -> None:
            self._now = clock_start

        def advance(self, delta: timedelta) -> None:
            self._now += delta

        def __call__(self) -> datetime:
            return self._now

    clock = FixedClock()
    service = AmazonMarketplaceRefreshService(
        session_factory=a32_session_factory,
        encryption_service=token_encryption_service,
        sellers_client_factory=build_sellers_client_factory(
            refresh_token=FAKE_A32_REFRESH_TOKEN,
            sp_api_handler=_success_handler,
        ),
        min_lease_seconds=1,
        max_lease_seconds=3600,
        clock=clock,
    )
    gate = asyncio.Event()
    release = asyncio.Event()
    original_fetch = service._fetch_participations

    async def gated_fetch(encrypted, user_id, account_id):
        gate.set()
        await release.wait()
        return await original_fetch(
            encrypted=encrypted,
            user_id=user_id,
            account_id=account_id,
        )

    service._fetch_participations = gated_fetch  # type: ignore[method-assign]
    task = asyncio.create_task(
        service.refresh_marketplace_participations(
            user_id=user.id,
            account_id=summary.id,
            lease_duration=timedelta(seconds=2),
        )
    )
    await asyncio.wait_for(gate.wait(), timeout=5)
    clock.advance(timedelta(seconds=3))
    release.set()

    with pytest.raises(AmazonError) as exc_info:
        await asyncio.wait_for(task, timeout=5)
    assert exc_info.value.error_code == AMAZON_SYNC_LEASE_LOST

    verify = a32_session_factory()
    try:
        assert (
            verify.query(AmazonMarketplaceParticipation)
            .filter_by(amazon_account_id=summary.id)
            .count()
            == 0
        )
    finally:
        verify.close()


@pytest.mark.asyncio
async def test_external_call_runs_without_open_db_transaction(
    a32_session_factory,
    token_encryption_service,
) -> None:
    user, summary = create_committed_account(
        a32_session_factory,
        token_encryption_service,
        token=FAKE_A32_REFRESH_TOKEN,
    )
    active_sessions = 0
    original_factory = a32_session_factory

    def instrumented_factory() -> Session:
        nonlocal active_sessions
        db = original_factory()
        active_sessions += 1
        original_close = db.close

        def close() -> None:
            nonlocal active_sessions
            active_sessions -= 1
            original_close()

        db.close = close  # type: ignore[method-assign]
        return db

    service = AmazonMarketplaceRefreshService(
        session_factory=instrumented_factory,
        encryption_service=token_encryption_service,
        sellers_client_factory=build_sellers_client_factory(
            refresh_token=FAKE_A32_REFRESH_TOKEN,
            sp_api_handler=_success_handler,
        ),
        min_lease_seconds=1,
    )
    original_fetch = service._fetch_participations

    async def instrumented_fetch(encrypted, user_id, account_id):
        assert active_sessions == 0
        return await original_fetch(
            encrypted=encrypted,
            user_id=user_id,
            account_id=account_id,
        )

    service._fetch_participations = instrumented_fetch  # type: ignore[method-assign]
    await service.refresh_marketplace_participations(
        user_id=user.id,
        account_id=summary.id,
    )
    assert active_sessions == 0


@pytest.mark.asyncio
async def test_no_plaintext_leak_in_db_or_logs(
    a32_session_factory,
    user_factory,
    token_encryption_service,
    caplog: pytest.LogCaptureFixture,
) -> None:
    user, summary = create_committed_account(
        a32_session_factory,
        token_encryption_service,
        token=FAKE_A32_REFRESH_TOKEN,
    )
    service = _make_refresh_service(token_encryption_service, a32_session_factory, _success_handler)
    with caplog.at_level("ERROR"):
        await service.refresh_marketplace_participations(
            user_id=user.id,
            account_id=summary.id,
        )
    verify = a32_session_factory()
    try:
        account = verify.get(AmazonAccount, summary.id)
        logs = verify.query(AmazonSyncLog).filter_by(amazon_account_id=summary.id).all()
        combined = " ".join([repr(account), repr(logs), caplog.text])
        assert FAKE_A32_REFRESH_TOKEN not in combined
    finally:
        verify.close()
