"""Amazon selling_partner_id unique identity concurrency tests."""

from __future__ import annotations

import secrets
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.core.security import get_password_hash
from app.models.amazon_account import AmazonAccount, AmazonAccountStatus, new_account_key
from app.models.user import User

INSERT_TIMEOUT_SECONDS = 10
SHARED_SELLER_ID = "ConcurrentSeller1234"


@pytest.fixture
def seller_identity_session_factory(engine):
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


def _make_account_row(*, user_id, selling_partner_id: str) -> AmazonAccount:
    return AmazonAccount(
        user_id=user_id,
        account_key=new_account_key(),
        region="na",
        endpoint_mode="sandbox",
        status=AmazonAccountStatus.ACTIVE,
        refresh_token_ciphertext=secrets.token_bytes(48),
        refresh_token_key_version=1,
        refresh_token_fingerprint=secrets.token_hex(32),
        selling_partner_id=selling_partner_id,
    )


def test_concurrent_insert_same_selling_partner_id_single_owner(
    seller_identity_session_factory,
) -> None:
    setup_session = seller_identity_session_factory()
    try:
        owner = User(
            email="seller-identity-owner@example.com",
            password_hash=get_password_hash("Password1"),
            plan="free",
            monthly_tokens=100_000,
            used_tokens=0,
        )
        challenger = User(
            email="seller-identity-challenger@example.com",
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

    results: list[str | IntegrityError] = []

    def _worker(user_id) -> None:
        session = seller_identity_session_factory()
        try:
            session.add(
                _make_account_row(
                    user_id=user_id,
                    selling_partner_id=SHARED_SELLER_ID,
                )
            )
            session.commit()
            results.append("success")
        except IntegrityError as exc:
            session.rollback()
            results.append(exc)
        finally:
            session.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(_worker, owner_id),
            executor.submit(_worker, challenger_id),
        ]
        for future in as_completed(futures, timeout=INSERT_TIMEOUT_SECONDS):
            future.result(timeout=INSERT_TIMEOUT_SECONDS)

    successes = [result for result in results if result == "success"]
    failures = [result for result in results if isinstance(result, IntegrityError)]
    assert len(successes) == 1
    assert len(failures) == 1

    verify_session = seller_identity_session_factory()
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
                    "seller-identity-owner@example.com",
                    "seller-identity-challenger@example.com",
                ]
            )
        ).delete(synchronize_session=False)
        verify_session.commit()
    finally:
        verify_session.close()
