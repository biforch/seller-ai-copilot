"""OAuth account persistence transaction cleanup and lock-release tests."""

from __future__ import annotations

import threading
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.core.security import get_password_hash
from app.integrations.amazon.exceptions import (
    AMAZON_OAUTH_SELLER_ALREADY_LINKED,
    AMAZON_OAUTH_SELLER_MISMATCH,
    AMAZON_SYNC_IN_PROGRESS,
    AmazonError,
)
from app.integrations.amazon.token_encryption import TokenEncryptionConfig, TokenEncryptionService
from app.models.amazon_account import AmazonAccount
from app.models.user import User
from app.services.amazon_account_service import AmazonAccountService
from tests.fixtures.amazon_a32 import FAKE_A32_REFRESH_TOKEN

LOCK_TIMEOUT_SECONDS = 5
OTHER_OAUTH_TOKEN = "other-oauth-refresh-token-valid"


class FixedClock:
    def __init__(self, current: datetime) -> None:
        if current.tzinfo is None:
            current = current.replace(tzinfo=UTC)
        self._current = current

    def __call__(self) -> datetime:
        return self._current


@pytest.fixture
def oauth_tx_session_factory(engine):
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


def _encryption_service() -> TokenEncryptionService:
    import secrets

    return TokenEncryptionService(
        TokenEncryptionConfig(
            active_key_version=1,
            keys={1: secrets.token_bytes(32)},
            fingerprint_pepper=secrets.token_bytes(32),
        )
    )


def _assert_session_usable_after_oauth_failure(session) -> None:
    assert not session.in_transaction()
    assert session.execute(text("SELECT 1")).scalar_one() == 1


def _assert_for_update_lock_released(
    session_factory,
    *,
    account_id: uuid.UUID,
) -> None:
    acquired = threading.Event()
    errors: list[BaseException] = []

    def _worker() -> None:
        session = session_factory()
        try:
            session.query(AmazonAccount).filter(AmazonAccount.id == account_id).with_for_update().one()
            acquired.set()
            session.rollback()
        except BaseException as exc:
            errors.append(exc)
        finally:
            session.close()

    thread = threading.Thread(target=_worker)
    thread.start()
    thread.join(timeout=LOCK_TIMEOUT_SECONDS)
    assert not thread.is_alive(), "secondary FOR UPDATE did not complete within timeout"
    assert not errors, f"secondary FOR UPDATE raised: {errors!r}"
    assert acquired.is_set(), "secondary session could not acquire FOR UPDATE lock"


def _create_committed_oauth_account(
    session_factory,
    *,
    email: str,
    seller_id: str,
    token: str = FAKE_A32_REFRESH_TOKEN,
) -> tuple[uuid.UUID, uuid.UUID]:
    encryption = _encryption_service()
    session = session_factory()
    try:
        user = User(
            email=email,
            password_hash=get_password_hash("Password1"),
            plan="free",
            monthly_tokens=100_000,
            used_tokens=0,
        )
        session.add(user)
        session.flush()
        service = AmazonAccountService(session, encryption)
        summary = service.connect_account_from_oauth(
            user_id=user.id,
            region="na",
            selling_partner_id=seller_id,
            plaintext_refresh_token=token,
        )
        session.commit()
        return user.id, summary.id
    finally:
        session.close()


def test_connect_seller_already_linked_cleans_transaction_and_releases_lock(
    oauth_tx_session_factory,
) -> None:
    seller_id = "TxCleanupSellerLinked1"
    owner_id, account_id = _create_committed_oauth_account(
        oauth_tx_session_factory,
        email="oauth-tx-owner@example.com",
        seller_id=seller_id,
    )
    challenger = oauth_tx_session_factory()
    try:
        challenger_user = User(
            email="oauth-tx-challenger@example.com",
            password_hash=get_password_hash("Password1"),
            plan="free",
            monthly_tokens=100_000,
            used_tokens=0,
        )
        challenger.add(challenger_user)
        challenger.commit()
        service = AmazonAccountService(challenger, _encryption_service())
        with pytest.raises(AmazonError) as exc_info:
            service.connect_account_from_oauth(
                user_id=challenger_user.id,
                region="na",
                selling_partner_id=seller_id,
                plaintext_refresh_token=OTHER_OAUTH_TOKEN,
            )
        assert exc_info.value.error_code == AMAZON_OAUTH_SELLER_ALREADY_LINKED
        _assert_session_usable_after_oauth_failure(challenger)
    finally:
        challenger.close()

    verify = oauth_tx_session_factory()
    try:
        stored = verify.query(AmazonAccount).filter_by(selling_partner_id=seller_id).one()
        assert stored.id == account_id
        assert stored.user_id == owner_id
    finally:
        verify.close()

    _assert_for_update_lock_released(oauth_tx_session_factory, account_id=account_id)


def test_connect_active_lease_cleans_transaction_and_releases_lock(
    oauth_tx_session_factory,
) -> None:
    seller_id = "TxCleanupConnectLease1"
    user_id, account_id = _create_committed_oauth_account(
        oauth_tx_session_factory,
        email="oauth-tx-connect-lease@example.com",
        seller_id=seller_id,
    )
    clock = FixedClock(datetime(2026, 3, 1, 12, 0, tzinfo=UTC))
    lease_session = oauth_tx_session_factory()
    try:
        account = lease_session.get(AmazonAccount, account_id)
        assert account is not None
        account.sync_lease_id = uuid.uuid4()
        account.sync_lease_expires_at = clock() + timedelta(minutes=5)
        lease_session.commit()
    finally:
        lease_session.close()

    fail_session = oauth_tx_session_factory()
    try:
        service = AmazonAccountService(fail_session, _encryption_service(), clock=clock)
        with pytest.raises(AmazonError) as exc_info:
            service.connect_account_from_oauth(
                user_id=user_id,
                region="na",
                selling_partner_id=seller_id,
                plaintext_refresh_token=OTHER_OAUTH_TOKEN,
            )
        assert exc_info.value.error_code == AMAZON_SYNC_IN_PROGRESS
        _assert_session_usable_after_oauth_failure(fail_session)
    finally:
        fail_session.close()

    _assert_for_update_lock_released(oauth_tx_session_factory, account_id=account_id)


def test_reauthorize_seller_mismatch_cleans_transaction_and_releases_lock(
    oauth_tx_session_factory,
) -> None:
    seller_id = "TxCleanupReauthMatch1"
    user_id, account_id = _create_committed_oauth_account(
        oauth_tx_session_factory,
        email="oauth-tx-reauth-mismatch@example.com",
        seller_id=seller_id,
    )
    fail_session = oauth_tx_session_factory()
    try:
        service = AmazonAccountService(fail_session, _encryption_service())
        with pytest.raises(AmazonError) as exc_info:
            service.reauthorize_account_from_oauth(
                user_id=user_id,
                account_id=account_id,
                selling_partner_id="WrongSeller1234567",
                plaintext_refresh_token=OTHER_OAUTH_TOKEN,
            )
        assert exc_info.value.error_code == AMAZON_OAUTH_SELLER_MISMATCH
        _assert_session_usable_after_oauth_failure(fail_session)
    finally:
        fail_session.close()

    _assert_for_update_lock_released(oauth_tx_session_factory, account_id=account_id)


def test_reauthorize_active_lease_cleans_transaction_and_releases_lock(
    oauth_tx_session_factory,
) -> None:
    seller_id = "TxCleanupReauthLease1"
    user_id, account_id = _create_committed_oauth_account(
        oauth_tx_session_factory,
        email="oauth-tx-reauth-lease@example.com",
        seller_id=seller_id,
    )
    clock = FixedClock(datetime(2026, 3, 1, 12, 0, tzinfo=UTC))
    lease_session = oauth_tx_session_factory()
    try:
        account = lease_session.get(AmazonAccount, account_id)
        assert account is not None
        account.sync_lease_id = uuid.uuid4()
        account.sync_lease_expires_at = clock() + timedelta(minutes=5)
        lease_session.commit()
    finally:
        lease_session.close()

    fail_session = oauth_tx_session_factory()
    try:
        service = AmazonAccountService(fail_session, _encryption_service(), clock=clock)
        with pytest.raises(AmazonError) as exc_info:
            service.reauthorize_account_from_oauth(
                user_id=user_id,
                account_id=account_id,
                selling_partner_id=seller_id,
                plaintext_refresh_token=OTHER_OAUTH_TOKEN,
            )
        assert exc_info.value.error_code == AMAZON_SYNC_IN_PROGRESS
        _assert_session_usable_after_oauth_failure(fail_session)
    finally:
        fail_session.close()

    _assert_for_update_lock_released(oauth_tx_session_factory, account_id=account_id)
