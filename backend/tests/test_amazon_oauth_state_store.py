"""Amazon OAuth state store unit tests."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app.integrations.amazon.exceptions import (
    AMAZON_ACCOUNT_NOT_FOUND,
    AMAZON_OAUTH_INTENT_INVALID,
    AMAZON_OAUTH_MARKETPLACE_INVALID,
    AMAZON_OAUTH_STATE_EXPIRED,
    AMAZON_OAUTH_STATE_INVALID,
    AMAZON_OAUTH_STATE_REPLAY,
    AMAZON_OAUTH_USER_NOT_FOUND,
    AmazonError,
)
from app.models.amazon_oauth_state import AmazonOAuthState, OAuthStateIntent, OAuthStateStatus
from app.services.amazon_oauth_state_store import (
    AmazonOAuthStateStore,
    OAuthStateIssue,
    hash_oauth_state_token,
)
from tests.fixtures.amazon_a32 import FAKE_A32_REFRESH_TOKEN, create_account_via_service

CANARY = "CANARY_OAUTH_STATE_TOKEN_XYZ"
DEFAULT_TTL_SECONDS = 600


class FixedClock:
    def __init__(self, current: datetime) -> None:
        if current.tzinfo is None:
            current = current.replace(tzinfo=UTC)
        self._current = current

    def __call__(self) -> datetime:
        return self._current

    def advance(self, delta: timedelta) -> None:
        self._current += delta


def _store(
    db_session: Session,
    *,
    clock: FixedClock | None = None,
    token_generator=None,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> tuple[AmazonOAuthStateStore, FixedClock]:
    fixed_clock = clock or FixedClock(datetime(2026, 1, 1, 12, 0, tzinfo=UTC))
    return (
        AmazonOAuthStateStore(
            db_session,
            ttl_seconds=ttl_seconds,
            clock=fixed_clock,
            token_generator=token_generator,
        ),
        fixed_clock,
    )


def test_create_connect_state_success(db_session: Session, user_factory) -> None:
    user = user_factory("oauth-create-connect@example.com")
    store, clock = _store(db_session)
    issue = store.create_state(
        user_id=user.id,
        marketplace_code="us",
        intent=OAuthStateIntent.CONNECT,
    )
    assert isinstance(issue, OAuthStateIssue)
    assert issue.marketplace_code == "US"
    assert issue.region == "na"
    assert issue.intent == OAuthStateIntent.CONNECT
    assert issue.target_account_id is None
    assert issue.expires_at == clock() + timedelta(seconds=DEFAULT_TTL_SECONDS)

    row = db_session.query(AmazonOAuthState).one()
    assert row.state_token_hash == hash_oauth_state_token(issue.raw_state_token)
    assert row.status == OAuthStateStatus.PENDING


def test_create_reauthorize_state_success(
    db_session: Session,
    user_factory,
    token_encryption_service,
) -> None:
    user, summary = create_account_via_service(
        db_session,
        user_factory,
        token_encryption_service,
        token=FAKE_A32_REFRESH_TOKEN,
    )
    store, _clock = _store(db_session)
    issue = store.create_state(
        user_id=user.id,
        marketplace_code="DE",
        intent=OAuthStateIntent.REAUTHORIZE,
        target_account_id=summary.id,
    )
    assert issue.intent == OAuthStateIntent.REAUTHORIZE
    assert issue.target_account_id == summary.id
    assert issue.region == "eu"


def test_create_state_user_not_found(db_session: Session) -> None:
    store, _clock = _store(db_session)
    with pytest.raises(AmazonError) as exc_info:
        store.create_state(
            user_id=uuid.uuid4(),
            marketplace_code="US",
            intent=OAuthStateIntent.CONNECT,
        )
    assert exc_info.value.error_code == AMAZON_OAUTH_USER_NOT_FOUND


def test_create_reauthorize_account_not_owned(
    db_session: Session,
    user_factory,
    token_encryption_service,
) -> None:
    owner, summary = create_account_via_service(
        db_session,
        user_factory,
        token_encryption_service,
        token=FAKE_A32_REFRESH_TOKEN,
    )
    other = user_factory("oauth-other-user@example.com")
    store, _clock = _store(db_session)
    with pytest.raises(AmazonError) as exc_info:
        store.create_state(
            user_id=other.id,
            marketplace_code="US",
            intent=OAuthStateIntent.REAUTHORIZE,
            target_account_id=summary.id,
        )
    assert exc_info.value.error_code == AMAZON_ACCOUNT_NOT_FOUND
    assert str(owner.id) not in str(exc_info.value)


def test_create_invalid_marketplace(db_session: Session, user_factory) -> None:
    user = user_factory("oauth-invalid-market@example.com")
    store, _clock = _store(db_session)
    with pytest.raises(AmazonError) as exc_info:
        store.create_state(
            user_id=user.id,
            marketplace_code="ZZ",
            intent=OAuthStateIntent.CONNECT,
        )
    assert exc_info.value.error_code == AMAZON_OAUTH_MARKETPLACE_INVALID


@pytest.mark.parametrize(
    ("intent", "target_account_id"),
    [
        (OAuthStateIntent.CONNECT, uuid.uuid4()),
        (OAuthStateIntent.REAUTHORIZE, None),
        ("upgrade", None),
    ],
)
def test_create_invalid_intent_combinations(
    db_session: Session,
    user_factory,
    intent: str,
    target_account_id: uuid.UUID | None,
) -> None:
    user = user_factory("oauth-invalid-intent@example.com")
    store, _clock = _store(db_session)
    with pytest.raises(AmazonError) as exc_info:
        store.create_state(
            user_id=user.id,
            marketplace_code="US",
            intent=intent,
            target_account_id=target_account_id,
        )
    assert exc_info.value.error_code in {
        AMAZON_OAUTH_INTENT_INVALID,
        AMAZON_ACCOUNT_NOT_FOUND,
    }


def test_issue_repr_hides_raw_token(db_session: Session, user_factory) -> None:
    user = user_factory("oauth-issue-repr@example.com")
    store, _clock = _store(db_session)
    issue = store.create_state(
        user_id=user.id,
        marketplace_code="US",
        intent=OAuthStateIntent.CONNECT,
    )
    assert issue.raw_state_token not in repr(issue)
    assert issue.raw_state_token not in str(issue)


def test_create_persists_hash_only(db_session: Session, user_factory) -> None:
    user = user_factory("oauth-hash-only@example.com")
    raw = "B" * 43
    store, _clock = _store(db_session, token_generator=lambda: raw)
    store.create_state(
        user_id=user.id,
        marketplace_code="US",
        intent=OAuthStateIntent.CONNECT,
    )
    row = db_session.query(AmazonOAuthState).one()
    assert row.state_token_hash == hashlib.sha256(raw.encode("utf-8")).hexdigest()
    for value in row.__dict__.values():
        assert raw not in str(value)


def test_create_does_not_commit(db_session: Session, user_factory) -> None:
    user = user_factory("oauth-no-commit-create@example.com")
    store, _clock = _store(db_session)
    store.create_state(
        user_id=user.id,
        marketplace_code="US",
        intent=OAuthStateIntent.CONNECT,
    )
    assert db_session.is_active


def test_create_rejects_invalid_generated_token(db_session: Session, user_factory) -> None:
    user = user_factory("oauth-invalid-generated@example.com")
    store, _clock = _store(db_session, token_generator=lambda: "short")
    with pytest.raises(AmazonError) as exc_info:
        store.create_state(
            user_id=user.id,
            marketplace_code="US",
            intent=OAuthStateIntent.CONNECT,
        )
    assert exc_info.value.error_code == AMAZON_OAUTH_STATE_INVALID


def test_create_hash_collision_retries(db_session: Session, user_factory) -> None:
    user = user_factory("oauth-collision-retry@example.com")
    raw_a = "C" * 43
    raw_b = "D" * 43
    generator = iter([raw_a, raw_b]).__next__
    store, _clock = _store(db_session, token_generator=generator)
    db_session.add(
        AmazonOAuthState(
            state_token_hash=hash_oauth_state_token(raw_a),
            user_id=user.id,
            marketplace_code="US",
            region="na",
            intent=OAuthStateIntent.CONNECT,
            status=OAuthStateStatus.PENDING,
            expires_at=_clock() + timedelta(minutes=10),
            created_at=_clock(),
        )
    )
    db_session.flush()
    issue = store.create_state(
        user_id=user.id,
        marketplace_code="US",
        intent=OAuthStateIntent.CONNECT,
    )
    assert issue.raw_state_token == raw_b


def test_create_hash_collision_exhaustion_fails(db_session: Session, user_factory) -> None:
    user = user_factory("oauth-collision-exhaust@example.com")
    raw = "E" * 43
    store, _clock = _store(db_session, token_generator=lambda: raw)
    db_session.add(
        AmazonOAuthState(
            state_token_hash=hash_oauth_state_token(raw),
            user_id=user.id,
            marketplace_code="US",
            region="na",
            intent=OAuthStateIntent.CONNECT,
            status=OAuthStateStatus.PENDING,
            expires_at=_clock() + timedelta(minutes=10),
            created_at=_clock(),
        )
    )
    db_session.flush()
    with pytest.raises(AmazonError) as exc_info:
        store.create_state(
            user_id=user.id,
            marketplace_code="US",
            intent=OAuthStateIntent.CONNECT,
        )
    assert exc_info.value.error_code == AMAZON_OAUTH_STATE_INVALID


def test_consume_pending_state_success(db_session: Session, user_factory) -> None:
    user = user_factory("oauth-consume-success@example.com")
    store, clock = _store(db_session)
    issue = store.create_state(
        user_id=user.id,
        marketplace_code="US",
        intent=OAuthStateIntent.CONNECT,
    )
    consumed = store.consume_state(issue.raw_state_token)
    assert consumed.user_id == user.id
    assert consumed.intent == OAuthStateIntent.CONNECT
    assert consumed.consumed_at == clock()
    row = db_session.query(AmazonOAuthState).one()
    assert row.status == OAuthStateStatus.CONSUMED
    assert row.consumed_at == clock()


def test_consume_invalid_format(db_session: Session) -> None:
    store, _clock = _store(db_session)
    with pytest.raises(AmazonError) as exc_info:
        store.consume_state("bad")
    assert exc_info.value.error_code == AMAZON_OAUTH_STATE_INVALID
    assert CANARY not in str(exc_info.value)


def test_consume_unknown_hash(db_session: Session) -> None:
    store, _clock = _store(db_session)
    unknown = "F" * 43
    with pytest.raises(AmazonError) as exc_info:
        store.consume_state(unknown)
    assert exc_info.value.error_code == AMAZON_OAUTH_STATE_INVALID


def test_consume_expired_state(db_session: Session, user_factory) -> None:
    user = user_factory("oauth-consume-expired@example.com")
    clock = FixedClock(datetime(2026, 1, 1, 12, 0, tzinfo=UTC))
    store, clock = _store(db_session, clock=clock)
    issue = store.create_state(
        user_id=user.id,
        marketplace_code="US",
        intent=OAuthStateIntent.CONNECT,
    )
    clock.advance(timedelta(seconds=DEFAULT_TTL_SECONDS + 1))
    with pytest.raises(AmazonError) as exc_info:
        store.consume_state(issue.raw_state_token)
    assert exc_info.value.error_code == AMAZON_OAUTH_STATE_EXPIRED


def test_consume_replay(db_session: Session, user_factory) -> None:
    user = user_factory("oauth-consume-replay@example.com")
    store, _clock = _store(db_session)
    issue = store.create_state(
        user_id=user.id,
        marketplace_code="US",
        intent=OAuthStateIntent.CONNECT,
    )
    store.consume_state(issue.raw_state_token)
    with pytest.raises(AmazonError) as exc_info:
        store.consume_state(issue.raw_state_token)
    assert exc_info.value.error_code == AMAZON_OAUTH_STATE_REPLAY


def test_consume_does_not_commit(db_session: Session, user_factory) -> None:
    user = user_factory("oauth-no-commit-consume@example.com")
    store, _clock = _store(db_session)
    issue = store.create_state(
        user_id=user.id,
        marketplace_code="US",
        intent=OAuthStateIntent.CONNECT,
    )
    store.consume_state(issue.raw_state_token)
    assert db_session.is_active


def test_consumed_result_hides_raw_and_hash(db_session: Session, user_factory) -> None:
    user = user_factory("oauth-consumed-safe@example.com")
    store, _clock = _store(db_session)
    issue = store.create_state(
        user_id=user.id,
        marketplace_code="US",
        intent=OAuthStateIntent.CONNECT,
    )
    consumed = store.consume_state(issue.raw_state_token)
    rendered = repr(consumed)
    assert issue.raw_state_token not in rendered
    assert hash_oauth_state_token(issue.raw_state_token) not in rendered
    assert CANARY not in rendered


def test_consume_logs_safe_on_error(db_session: Session, caplog: pytest.LogCaptureFixture) -> None:
    store, _clock = _store(db_session)
    token = f"{CANARY}{'G' * 30}"
    with caplog.at_level("WARNING"):
        with pytest.raises(AmazonError):
            store.consume_state(token)
    combined = " ".join(record.message for record in caplog.records)
    assert CANARY not in combined
