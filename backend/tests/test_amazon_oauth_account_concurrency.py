"""Amazon OAuth account connect concurrency tests."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest
from sqlalchemy.orm import sessionmaker

from app.core.security import get_password_hash
from app.integrations.amazon.exceptions import (
    AMAZON_OAUTH_SELLER_ALREADY_LINKED,
    AmazonError,
)
from app.integrations.amazon.token_encryption import TokenEncryptionConfig, TokenEncryptionService
from app.models.amazon_account import AmazonAccount
from app.models.user import User
from app.services.amazon_account_service import AmazonAccountService
from tests.fixtures.amazon_a32 import FAKE_A32_REFRESH_TOKEN

CONNECT_TIMEOUT_SECONDS = 10
SHARED_SELLER_ID = "OAuthConcurrentSeller1"
OTHER_OAUTH_TOKEN = "other-oauth-concurrency-token"


@pytest.fixture
def oauth_account_session_factory(engine):
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


def _encryption_service() -> TokenEncryptionService:
    import secrets

    key = secrets.token_bytes(32)
    pepper = secrets.token_bytes(32)
    config = TokenEncryptionConfig(
        active_key_version=1,
        keys={1: key},
        fingerprint_pepper=pepper,
    )
    return TokenEncryptionService(config)


def test_concurrent_oauth_connect_same_seller_single_owner(
    oauth_account_session_factory,
) -> None:
    encryption = _encryption_service()
    setup_session = oauth_account_session_factory()
    try:
        owner = User(
            email="oauth-concurrency-owner@example.com",
            password_hash=get_password_hash("Password1"),
            plan="free",
            monthly_tokens=100_000,
            used_tokens=0,
        )
        challenger = User(
            email="oauth-concurrency-challenger@example.com",
            password_hash=get_password_hash("Password1"),
            plan="free",
            monthly_tokens=100_000,
            used_tokens=0,
        )
        setup_session.add_all([owner, challenger])
        setup_session.commit()
        owner_id = owner.id
        challenger_id = challenger.id
    finally:
        setup_session.close()

    results: list[str | AmazonError] = []

    def _worker(user_id) -> None:
        session = oauth_account_session_factory()
        try:
            service = AmazonAccountService(session, encryption)
            service.connect_account_from_oauth(
                user_id=user_id,
                region="na",
                selling_partner_id=SHARED_SELLER_ID,
                plaintext_refresh_token=FAKE_A32_REFRESH_TOKEN,
            )
            results.append("success")
        except AmazonError as exc:
            session.rollback()
            results.append(exc)
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(_worker, owner_id),
            executor.submit(_worker, challenger_id),
        ]
        for future in as_completed(futures, timeout=CONNECT_TIMEOUT_SECONDS):
            future.result(timeout=CONNECT_TIMEOUT_SECONDS)

    successes = [result for result in results if result == "success"]
    failures = [result for result in results if isinstance(result, AmazonError)]
    assert len(successes) == 1
    assert len(failures) == 1
    assert failures[0].error_code == AMAZON_OAUTH_SELLER_ALREADY_LINKED

    verify_session = oauth_account_session_factory()
    try:
        rows = (
            verify_session.query(AmazonAccount)
            .filter(AmazonAccount.selling_partner_id == SHARED_SELLER_ID)
            .all()
        )
        assert len(rows) == 1
        verify_session.query(AmazonAccount).filter(
            AmazonAccount.selling_partner_id == SHARED_SELLER_ID
        ).delete(synchronize_session=False)
        verify_session.query(User).filter(
            User.email.in_(
                [
                    "oauth-concurrency-owner@example.com",
                    "oauth-concurrency-challenger@example.com",
                ]
            )
        ).delete(synchronize_session=False)
        verify_session.commit()
    finally:
        verify_session.close()
