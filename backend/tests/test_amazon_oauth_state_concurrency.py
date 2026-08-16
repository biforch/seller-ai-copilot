"""Amazon OAuth state concurrent consumption tests."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import sessionmaker

from app.core.security import get_password_hash
from app.integrations.amazon.exceptions import (
    AMAZON_OAUTH_STATE_REPLAY,
    AmazonError,
)
from app.models.amazon_oauth_state import AmazonOAuthState, OAuthStateIntent, OAuthStateStatus
from app.models.user import User
from app.services.amazon_oauth_state_store import AmazonOAuthStateStore, ConsumedOAuthState

CONSUME_TIMEOUT_SECONDS = 10


class FixedClock:
    def __init__(self, current: datetime) -> None:
        if current.tzinfo is None:
            current = current.replace(tzinfo=UTC)
        self._current = current

    def __call__(self) -> datetime:
        return self._current


@pytest.fixture
def oauth_session_factory(engine):
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


def test_concurrent_consume_single_winner(oauth_session_factory) -> None:
    clock = FixedClock(datetime(2026, 2, 1, 12, 0, tzinfo=UTC))
    create_session = oauth_session_factory()
    try:
        user = User(
            email="oauth-concurrency@example.com",
            password_hash=get_password_hash("Password1"),
            plan="free",
            monthly_tokens=100_000,
            used_tokens=0,
        )
        create_session.add(user)
        create_session.flush()
        store = AmazonOAuthStateStore(create_session, ttl_seconds=600, clock=clock)
        issue = store.create_state(
            user_id=user.id,
            marketplace_code="US",
            intent=OAuthStateIntent.CONNECT,
        )
        raw_state = issue.raw_state_token
        create_session.commit()
    finally:
        create_session.close()

    results: list[ConsumedOAuthState | AmazonError] = []

    def _worker() -> None:
        session = oauth_session_factory()
        try:
            store = AmazonOAuthStateStore(session, ttl_seconds=600, clock=clock)
            results.append(store.consume_state(raw_state))
            session.commit()
        except AmazonError as exc:
            results.append(exc)
            session.rollback()
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(_worker) for _ in range(2)]
        for future in as_completed(futures, timeout=CONSUME_TIMEOUT_SECONDS):
            future.result(timeout=CONSUME_TIMEOUT_SECONDS)

    successes = [result for result in results if isinstance(result, ConsumedOAuthState)]
    failures = [result for result in results if isinstance(result, AmazonError)]
    assert len(successes) == 1
    assert len(failures) == 1
    assert failures[0].error_code == AMAZON_OAUTH_STATE_REPLAY

    verify_session = oauth_session_factory()
    try:
        row = verify_session.query(AmazonOAuthState).one()
        assert row.status == OAuthStateStatus.CONSUMED
        assert row.consumed_at is not None
        verify_session.delete(row)
        verify_session.commit()
    finally:
        verify_session.close()
