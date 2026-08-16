"""Amazon OAuth state model and database constraint tests."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.amazon_account import AmazonAccount, AmazonAccountStatus, new_account_key
from app.models.amazon_oauth_state import (
    STATE_TOKEN_HASH_UNIQUE_CONSTRAINT,
    AmazonOAuthState,
    OAuthStateIntent,
    OAuthStateStatus,
)

CANARY_HASH = "c" * 64


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _make_account(user_id: uuid.UUID) -> AmazonAccount:
    ciphertext = secrets.token_bytes(48)
    return AmazonAccount(
        user_id=user_id,
        account_key=new_account_key(),
        region="na",
        endpoint_mode="sandbox",
        status=AmazonAccountStatus.ACTIVE,
        refresh_token_ciphertext=ciphertext,
        refresh_token_key_version=1,
        refresh_token_fingerprint=secrets.token_hex(32),
    )


def _make_state(
    *,
    user_id: uuid.UUID,
    state_hash: str | None = None,
    intent: str = OAuthStateIntent.CONNECT,
    target_account_id: uuid.UUID | None = None,
    status: str = OAuthStateStatus.PENDING,
    created_at: datetime | None = None,
    expires_at: datetime | None = None,
    consumed_at: datetime | None = None,
    region: str = "na",
    marketplace_code: str = "US",
) -> AmazonOAuthState:
    row_created_at = created_at or datetime(2026, 1, 1, tzinfo=UTC)
    return AmazonOAuthState(
        state_token_hash=state_hash or _hash(secrets.token_urlsafe(32)),
        user_id=user_id,
        marketplace_code=marketplace_code,
        region=region,
        intent=intent,
        target_account_id=target_account_id,
        status=status,
        expires_at=expires_at or row_created_at + timedelta(minutes=10),
        consumed_at=consumed_at,
        created_at=row_created_at,
    )


def test_model_columns_do_not_store_raw_state(db_session: Session, user_factory) -> None:
    user = user_factory("oauth-model-columns@example.com")
    raw = secrets.token_urlsafe(32)
    row = _make_state(user_id=user.id, state_hash=_hash(raw))
    db_session.add(row)
    db_session.flush()
    columns = {column.name for column in AmazonOAuthState.__table__.columns}
    assert "raw_state" not in columns
    assert raw not in repr(row)


def test_state_token_hash_unique(db_session: Session, user_factory) -> None:
    user = user_factory("oauth-hash-unique@example.com")
    shared_hash = _hash("shared-state-token-value-for-unique-test-abc")
    db_session.add(_make_state(user_id=user.id, state_hash=shared_hash))
    db_session.flush()
    with pytest.raises(IntegrityError):
        db_session.add(_make_state(user_id=user.id, state_hash=shared_hash))
        db_session.flush()


@pytest.mark.parametrize("invalid_hash", ["abc", "A" * 64, "g" * 64])
def test_invalid_state_hash_format_rejected(
    db_session: Session,
    user_factory,
    invalid_hash: str,
) -> None:
    user = user_factory(f"oauth-hash-invalid-{invalid_hash[:3]}@example.com")
    db_session.add(_make_state(user_id=user.id, state_hash=invalid_hash))
    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize("region", ["xx", "us"])
def test_invalid_region_rejected(db_session: Session, user_factory, region: str) -> None:
    user = user_factory(f"oauth-region-{region}@example.com")
    db_session.add(_make_state(user_id=user.id, region=region))
    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize("intent", ["link", ""])
def test_invalid_intent_rejected(db_session: Session, user_factory, intent: str) -> None:
    user = user_factory(f"oauth-intent-{intent or 'empty'}@example.com")
    db_session.add(_make_state(user_id=user.id, intent=intent))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_connect_with_target_account_rejected(db_session: Session, user_factory) -> None:
    user = user_factory("oauth-connect-target@example.com")
    account = _make_account(user.id)
    db_session.add(account)
    db_session.flush()
    db_session.add(
        _make_state(
            user_id=user.id,
            intent=OAuthStateIntent.CONNECT,
            target_account_id=account.id,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_reauthorize_without_target_account_rejected(db_session: Session, user_factory) -> None:
    user = user_factory("oauth-reauth-no-target@example.com")
    db_session.add(
        _make_state(
            user_id=user.id,
            intent=OAuthStateIntent.REAUTHORIZE,
            target_account_id=None,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_pending_with_consumed_at_rejected(db_session: Session, user_factory) -> None:
    user = user_factory("oauth-pending-consumed@example.com")
    now = datetime(2026, 1, 1, tzinfo=UTC)
    db_session.add(
        _make_state(
            user_id=user.id,
            status=OAuthStateStatus.PENDING,
            consumed_at=now,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_consumed_without_consumed_at_rejected(db_session: Session, user_factory) -> None:
    user = user_factory("oauth-consumed-null@example.com")
    db_session.add(
        _make_state(
            user_id=user.id,
            status=OAuthStateStatus.CONSUMED,
            consumed_at=None,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_expires_at_must_be_after_created_at(db_session: Session, user_factory) -> None:
    user = user_factory("oauth-expiry-order@example.com")
    created_at = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    db_session.add(
        _make_state(
            user_id=user.id,
            created_at=created_at,
            expires_at=created_at,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_user_delete_cascades(db_session: Session, user_factory) -> None:
    user = user_factory("oauth-user-cascade@example.com")
    row = _make_state(user_id=user.id)
    db_session.add(row)
    db_session.flush()
    state_id = row.id
    db_session.delete(user)
    db_session.flush()
    db_session.expire_all()
    assert db_session.get(AmazonOAuthState, state_id) is None


def test_target_account_delete_cascades(db_session: Session, user_factory) -> None:
    user = user_factory("oauth-account-cascade@example.com")
    account = _make_account(user.id)
    db_session.add(account)
    db_session.flush()
    row = _make_state(
        user_id=user.id,
        intent=OAuthStateIntent.REAUTHORIZE,
        target_account_id=account.id,
    )
    db_session.add(row)
    db_session.flush()
    state_id = row.id
    db_session.delete(account)
    db_session.flush()
    db_session.expire_all()
    assert db_session.get(AmazonOAuthState, state_id) is None


def test_repr_does_not_contain_hash(db_session: Session, user_factory) -> None:
    user = user_factory("oauth-repr@example.com")
    state_hash = _hash("repr-test-state-token-value-1234567890123456789012")
    row = _make_state(user_id=user.id, state_hash=state_hash)
    rendered = repr(row)
    assert state_hash not in rendered
    assert CANARY_HASH not in rendered


def test_indexes_match_model(db_session: Session) -> None:
    inspector = inspect(db_session.bind)
    index_names = {idx["name"] for idx in inspector.get_indexes("amazon_oauth_states")}
    assert "ix_amazon_oauth_states_status_expires_at" in index_names
    assert "ix_amazon_oauth_states_user_id_created_at" in index_names
    assert "ix_amazon_oauth_states_target_account_id" in index_names

    unique_names = {
        constraint["name"]
        for constraint in inspector.get_unique_constraints("amazon_oauth_states")
    }
    assert STATE_TOKEN_HASH_UNIQUE_CONSTRAINT in unique_names

    check_names = {check["name"] for check in inspector.get_check_constraints("amazon_oauth_states")}
    assert "ck_amazon_oauth_states_state_token_hash_format" in check_names
    assert "ck_amazon_oauth_states_intent_target_account" in check_names
    assert "ck_amazon_oauth_states_status_consumed_at" in check_names
    assert "ck_amazon_oauth_states_expires_after_created" in check_names
