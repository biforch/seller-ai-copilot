from __future__ import annotations

import threading
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.integrations.amazon.exceptions import (
    AMAZON_ACCOUNT_DISABLED,
    AMAZON_ACCOUNT_NOT_FOUND,
    AMAZON_CONFIG_INVALID,
    AMAZON_SYNC_IN_PROGRESS,
    AMAZON_SYNC_LEASE_EXPIRED,
    AMAZON_SYNC_LEASE_LOST,
    AmazonError,
)
from app.models.amazon_account import AmazonAccount
from app.models.amazon_sync_log import AmazonSyncLog, AmazonSyncOperation, AmazonSyncStatus
from app.services.amazon_sync_lease_service import AmazonSyncLeaseService, SyncLeaseContext
from tests.fixtures.amazon_a32 import create_account_via_service, create_committed_account


class FixedClock:
    def __init__(self, start: datetime) -> None:
        self._now = start

    def advance(self, delta: timedelta) -> None:
        self._now += delta

    def __call__(self) -> datetime:
        return self._now


def _acquire(
    db_session,
    *,
    user_id: uuid.UUID,
    account_id: uuid.UUID,
    clock: FixedClock | None = None,
    duration: timedelta | None = None,
) -> SyncLeaseContext:
    service = AmazonSyncLeaseService(
        db_session,
        min_lease_seconds=1,
        max_lease_seconds=3600,
        clock=clock,
    )
    return service.acquire(
        user_id=user_id,
        account_id=account_id,
        operation=AmazonSyncOperation.MARKETPLACE_REFRESH,
        lease_duration=duration or timedelta(seconds=30),
    )


def test_first_acquire_succeeds(db_session, token_encryption_service, user_factory) -> None:
    user, summary = create_account_via_service(
        db_session,
        user_factory,
        token_encryption_service,
        token="fake-refresh-token-a3-2-never-log",
    )
    ctx = _acquire(db_session, user_id=user.id, account_id=summary.id)
    account = db_session.get(AmazonAccount, summary.id)
    assert account is not None
    assert account.sync_lease_id == ctx.lease_id
    log = db_session.get(AmazonSyncLog, ctx.sync_log_id)
    assert log is not None
    assert log.status == AmazonSyncStatus.PROCESSING


def test_second_acquire_while_active_is_rejected(
    db_session,
    token_encryption_service,
    user_factory,
) -> None:
    user, summary = create_account_via_service(
        db_session,
        user_factory,
        token_encryption_service,
        token="fake-refresh-token-a3-2-never-log",
    )
    clock = FixedClock(datetime.now(UTC))
    _acquire(db_session, user_id=user.id, account_id=summary.id, clock=clock)
    with pytest.raises(AmazonError) as exc_info:
        _acquire(db_session, user_id=user.id, account_id=summary.id, clock=clock)
    assert exc_info.value.error_code == AMAZON_SYNC_IN_PROGRESS


def test_expired_lease_can_be_taken_over(
    db_session,
    token_encryption_service,
    user_factory,
) -> None:
    user, summary = create_account_via_service(
        db_session,
        user_factory,
        token_encryption_service,
        token="fake-refresh-token-a3-2-never-log",
    )
    clock = FixedClock(datetime.now(UTC))
    first = _acquire(
        db_session,
        user_id=user.id,
        account_id=summary.id,
        clock=clock,
        duration=timedelta(seconds=5),
    )
    clock.advance(timedelta(seconds=6))
    second = _acquire(
        db_session,
        user_id=user.id,
        account_id=summary.id,
        clock=clock,
        duration=timedelta(seconds=5),
    )
    assert second.lease_id != first.lease_id
    stale = db_session.get(AmazonSyncLog, first.sync_log_id)
    assert stale is not None
    assert stale.status == AmazonSyncStatus.FAILED
    assert stale.error_code == AMAZON_SYNC_LEASE_EXPIRED


def test_disabled_account_cannot_acquire(
    db_session,
    token_encryption_service,
    user_factory,
) -> None:
    from app.services.amazon_account_service import AmazonAccountService

    user, summary = create_account_via_service(
        db_session,
        user_factory,
        token_encryption_service,
        token="fake-refresh-token-a3-2-never-log",
    )
    AmazonAccountService(db_session, token_encryption_service).disable_account(
        user_id=user.id,
        account_id=summary.id,
    )
    with pytest.raises(AmazonError) as exc_info:
        _acquire(db_session, user_id=user.id, account_id=summary.id)
    assert exc_info.value.error_code == AMAZON_ACCOUNT_DISABLED


def test_lease_duration_bounds(db_session, token_encryption_service, user_factory) -> None:
    user, summary = create_account_via_service(
        db_session,
        user_factory,
        token_encryption_service,
        token="fake-refresh-token-a3-2-never-log",
    )
    service = AmazonSyncLeaseService(db_session, min_lease_seconds=5, max_lease_seconds=60)
    with pytest.raises(AmazonError) as exc_info:
        service.acquire(
            user_id=user.id,
            account_id=summary.id,
            operation=AmazonSyncOperation.MARKETPLACE_REFRESH,
            lease_duration=timedelta(seconds=0),
        )
    assert exc_info.value.error_code == AMAZON_CONFIG_INVALID


def test_clear_lease_requires_owner(db_session, token_encryption_service, user_factory) -> None:
    user, summary = create_account_via_service(
        db_session,
        user_factory,
        token_encryption_service,
        token="fake-refresh-token-a3-2-never-log",
    )
    ctx = _acquire(db_session, user_id=user.id, account_id=summary.id)
    service = AmazonSyncLeaseService(db_session)
    service.clear_lease_if_owner(account_id=summary.id, lease_id=ctx.lease_id)
    with pytest.raises(AmazonError) as exc_info:
        service.clear_lease_if_owner(account_id=summary.id, lease_id=uuid.uuid4())
    assert exc_info.value.error_code == AMAZON_SYNC_LEASE_LOST


def test_tenant_isolation_on_acquire(db_session, token_encryption_service, user_factory) -> None:
    owner, summary = create_account_via_service(
        db_session,
        user_factory,
        token_encryption_service,
        token="fake-refresh-token-a3-2-never-log",
    )
    other = user_factory("lease-other@example.com")
    with pytest.raises(AmazonError) as exc_info:
        _acquire(db_session, user_id=other.id, account_id=summary.id)
    assert exc_info.value.error_code == AMAZON_ACCOUNT_NOT_FOUND


def test_old_worker_cannot_clear_lease_after_takeover(
    db_session,
    token_encryption_service,
    user_factory,
) -> None:
    user, summary = create_account_via_service(
        db_session,
        user_factory,
        token_encryption_service,
        token="fake-refresh-token-a3-2-never-log",
    )
    clock = FixedClock(datetime.now(UTC))
    first = _acquire(
        db_session,
        user_id=user.id,
        account_id=summary.id,
        clock=clock,
        duration=timedelta(seconds=2),
    )
    clock.advance(timedelta(seconds=3))
    _acquire(db_session, user_id=user.id, account_id=summary.id, clock=clock)
    service = AmazonSyncLeaseService(db_session, clock=clock)
    with pytest.raises(AmazonError) as exc_info:
        service.clear_lease_if_owner(account_id=summary.id, lease_id=first.lease_id)
    assert exc_info.value.error_code == AMAZON_SYNC_LEASE_LOST


def test_expired_lease_owner_cannot_clear_or_assert(
    db_session,
    token_encryption_service,
    user_factory,
) -> None:
    user, summary = create_account_via_service(
        db_session,
        user_factory,
        token_encryption_service,
        token="fake-refresh-token-a3-2-never-log",
    )
    clock = FixedClock(datetime.now(UTC))
    ctx = _acquire(
        db_session,
        user_id=user.id,
        account_id=summary.id,
        clock=clock,
        duration=timedelta(seconds=1),
    )
    clock.advance(timedelta(seconds=1))
    service = AmazonSyncLeaseService(db_session, clock=clock)
    with pytest.raises(AmazonError) as exc_info:
        service.assert_lease_owner(account_id=summary.id, lease_id=ctx.lease_id)
    assert exc_info.value.error_code == AMAZON_SYNC_LEASE_LOST
    with pytest.raises(AmazonError) as exc_info:
        service.clear_lease_if_owner(account_id=summary.id, lease_id=ctx.lease_id)
    assert exc_info.value.error_code == AMAZON_SYNC_LEASE_LOST


def test_postgresql_concurrent_acquire_single_winner(
    engine, a32_session_factory, token_encryption_service, user_factory
) -> None:
    user, summary = create_committed_account(
        a32_session_factory,
        token_encryption_service,
        token="fake-refresh-token-a3-2-never-log",
    )
    account_id = summary.id
    user_id = user.id

    barrier = threading.Barrier(2)
    results: list[SyncLeaseContext | BaseException] = []

    def worker() -> None:
        db = a32_session_factory()
        try:
            barrier.wait(timeout=5)
            ctx = _acquire(db, user_id=user_id, account_id=account_id)
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

    thread_errors = [item for item in results if isinstance(item, BaseException) and not isinstance(item, AmazonError)]
    assert not thread_errors, f"unexpected thread errors: {thread_errors!r}"

    winners = [item for item in results if isinstance(item, SyncLeaseContext)]
    losers = [item for item in results if isinstance(item, AmazonError)]
    assert len(winners) == 1
    assert len(losers) == 1
    assert losers[0].error_code == AMAZON_SYNC_IN_PROGRESS

    verify = a32_session_factory()
    try:
        account = verify.get(AmazonAccount, account_id)
        assert account is not None
        assert account.sync_lease_id == winners[0].lease_id
        processing_count = (
            verify.query(AmazonSyncLog)
            .filter_by(amazon_account_id=account_id, status=AmazonSyncStatus.PROCESSING)
            .count()
        )
        assert processing_count == 1
    finally:
        verify.close()
