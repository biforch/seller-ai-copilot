from __future__ import annotations

import secrets
import uuid

import pytest
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.orm import Session

from app.models.amazon_account import AmazonAccount, AmazonAccountStatus, new_account_key
from app.models.amazon_marketplace_participation import AmazonMarketplaceParticipation
from app.models.amazon_sync_log import AmazonSyncLog, AmazonSyncOperation, AmazonSyncStatus

FAKE_PLAINTEXT_MARKER = "fake-refresh-token-for-unit-test-only"


def _encrypt_stub(*, version: int = 1) -> tuple[bytes, str]:
    ciphertext = secrets.token_bytes(48)
    fingerprint = secrets.token_hex(32)
    return ciphertext, fingerprint


def _make_account(
    user_id: uuid.UUID,
    *,
    fingerprint: str | None = None,
    account_key: str | None = None,
    selling_partner_id: str | None = None,
    status: str = AmazonAccountStatus.ACTIVE,
) -> AmazonAccount:
    ciphertext, default_fingerprint = _encrypt_stub()
    return AmazonAccount(
        user_id=user_id,
        account_key=account_key or new_account_key(),
        region="na",
        endpoint_mode="sandbox",
        status=status,
        refresh_token_ciphertext=ciphertext,
        refresh_token_key_version=1,
        refresh_token_fingerprint=fingerprint or default_fingerprint,
        selling_partner_id=selling_partner_id,
    )


def test_account_key_default_is_unique_per_instance() -> None:
    first = new_account_key()
    second = new_account_key()
    assert first != second


def test_amazon_account_orm_default_account_key_is_unique(db_session: Session, user_factory) -> None:
    user = user_factory("amazon-account-key-default@example.com")
    ciphertext, fingerprint = _encrypt_stub()

    def _account_without_explicit_key() -> AmazonAccount:
        return AmazonAccount(
            user_id=user.id,
            region="na",
            endpoint_mode="sandbox",
            status=AmazonAccountStatus.ACTIVE,
            refresh_token_ciphertext=ciphertext,
            refresh_token_key_version=1,
            refresh_token_fingerprint=secrets.token_hex(32),
        )

    first = _account_without_explicit_key()
    second = _account_without_explicit_key()
    db_session.add_all([first, second])
    db_session.commit()
    assert first.account_key
    assert second.account_key
    assert first.account_key != second.account_key


def test_same_user_duplicate_fingerprint_rejected(db_session: Session, user_factory) -> None:
    user = user_factory("amazon-fingerprint-dup@example.com")
    shared_fingerprint = secrets.token_hex(32)
    db_session.add(_make_account(user.id, fingerprint=shared_fingerprint))
    db_session.flush()
    with pytest.raises(IntegrityError):
        db_session.add(_make_account(user.id, fingerprint=shared_fingerprint))
        db_session.flush()


def test_different_users_may_share_fingerprint(db_session: Session, user_factory) -> None:
    shared_fingerprint = secrets.token_hex(32)
    user_a = user_factory("amazon-fingerprint-a@example.com")
    user_b = user_factory("amazon-fingerprint-b@example.com")
    db_session.add(_make_account(user_a.id, fingerprint=shared_fingerprint))
    db_session.add(_make_account(user_b.id, fingerprint=shared_fingerprint))
    db_session.commit()


def test_amazon_account_repr_excludes_sensitive_fields(db_session: Session, user_factory) -> None:
    user = user_factory("amazon-repr@example.com")
    account = _make_account(user.id)
    account.refresh_token_ciphertext = secrets.token_bytes(48)
    account.refresh_token_fingerprint = secrets.token_hex(32)
    account.account_key = str(uuid.uuid4())
    db_session.add(account)
    db_session.commit()

    rendered = repr(account)
    assert str(account.id) in rendered
    assert account.refresh_token_ciphertext.hex() not in rendered
    assert account.refresh_token_fingerprint not in rendered
    assert account.account_key not in rendered
    assert FAKE_PLAINTEXT_MARKER not in rendered
    account.selling_partner_id = "SellerIdentity123"
    assert account.selling_partner_id not in rendered


def test_multiple_null_selling_partner_ids_allowed(db_session: Session, user_factory) -> None:
    user = user_factory("amazon-seller-null-a@example.com")
    db_session.add(_make_account(user.id, selling_partner_id=None))
    db_session.add(_make_account(user.id, selling_partner_id=None))
    db_session.commit()


def test_valid_selling_partner_id_allowed(db_session: Session, user_factory) -> None:
    user = user_factory("amazon-seller-valid@example.com")
    db_session.add(_make_account(user.id, selling_partner_id="A1B2C3D4E5"))
    db_session.commit()


@pytest.mark.parametrize(
    "invalid_selling_partner_id",
    [
        "",
        "   ",
        "seller-with-dash",
        "seller.with.dot",
        "seller/id",
        "seller\x00id",
        "a" * 33,
    ],
)
def test_invalid_selling_partner_id_rejected(
    db_session: Session,
    user_factory,
    invalid_selling_partner_id: str,
) -> None:
    user = user_factory(f"amazon-seller-invalid-{abs(hash(invalid_selling_partner_id))}@example.com")
    db_session.add(_make_account(user.id, selling_partner_id=invalid_selling_partner_id))
    with pytest.raises((IntegrityError, DataError, ValueError)):
        db_session.flush()


def test_same_user_duplicate_selling_partner_id_rejected(db_session: Session, user_factory) -> None:
    user = user_factory("amazon-seller-dup-same-user@example.com")
    db_session.add(_make_account(user.id, selling_partner_id="SameSeller123"))
    db_session.flush()
    with pytest.raises(IntegrityError):
        db_session.add(_make_account(user.id, selling_partner_id="SameSeller123"))
        db_session.flush()


def test_different_users_duplicate_selling_partner_id_rejected(
    db_session: Session,
    user_factory,
) -> None:
    user_a = user_factory("amazon-seller-dup-user-a@example.com")
    user_b = user_factory("amazon-seller-dup-user-b@example.com")
    db_session.add(_make_account(user_a.id, selling_partner_id="SharedSeller123"))
    db_session.flush()
    with pytest.raises(IntegrityError):
        db_session.add(_make_account(user_b.id, selling_partner_id="SharedSeller123"))
        db_session.flush()


def test_disabled_account_retains_seller_identity(
    db_session: Session,
    user_factory,
) -> None:
    owner = user_factory("amazon-seller-disabled-owner@example.com")
    challenger = user_factory("amazon-seller-disabled-challenger@example.com")
    db_session.add(
        _make_account(
            owner.id,
            selling_partner_id="DisabledSeller1",
            status=AmazonAccountStatus.DISABLED,
        )
    )
    db_session.flush()
    with pytest.raises(IntegrityError):
        db_session.add(
            _make_account(challenger.id, selling_partner_id="DisabledSeller1")
        )
        db_session.flush()


def test_marketplace_sync_eligible_property(db_session: Session, user_factory) -> None:
    user = user_factory("amazon-sync-eligible@example.com")
    account = _make_account(user.id)
    db_session.add(account)
    db_session.flush()

    participation = AmazonMarketplaceParticipation(
        amazon_account_id=account.id,
        marketplace_id="ATVPDKIKX0DER",
        marketplace_name="Amazon.com",
        country_code="US",
        participating=True,
        suspended_listings=False,
    )
    db_session.add(participation)
    db_session.commit()

    assert participation.sync_eligible is True
    participation_inactive = AmazonMarketplaceParticipation(
        amazon_account_id=account.id,
        marketplace_id="A2EUQ1WTGCTBG2",
        marketplace_name="Amazon.ca",
        country_code="CA",
        participating=False,
        suspended_listings=False,
    )
    assert participation_inactive.sync_eligible is False
    assert "sync_eligible" not in AmazonMarketplaceParticipation.__table__.columns


def test_user_delete_cascades_amazon_records(db_session: Session, user_factory) -> None:
    user = user_factory("amazon-cascade@example.com")
    account = _make_account(user.id)
    account.endpoint_mode = "production"
    db_session.add(account)
    db_session.flush()

    participation = AmazonMarketplaceParticipation(
        amazon_account_id=account.id,
        marketplace_id="ATVPDKIKX0DER",
        marketplace_name="Amazon.com",
        country_code="US",
        participating=True,
        suspended_listings=False,
    )
    sync_log = AmazonSyncLog(
        amazon_account_id=account.id,
        operation=AmazonSyncOperation.VERIFY_ACCOUNT,
        status=AmazonSyncStatus.SUCCEEDED,
    )
    db_session.add_all([participation, sync_log])
    db_session.commit()

    account_id = account.id
    db_session.delete(user)
    db_session.commit()

    assert db_session.get(AmazonAccount, account_id) is None
    assert (
        db_session.query(AmazonMarketplaceParticipation)
        .filter_by(amazon_account_id=account_id)
        .count()
        == 0
    )
    assert db_session.query(AmazonSyncLog).filter_by(amazon_account_id=account_id).count() == 0


def test_sync_log_repr_excludes_safe_detail(db_session: Session, user_factory) -> None:
    user = user_factory("amazon-log-repr@example.com")
    account = _make_account(user.id)
    db_session.add(account)
    db_session.flush()

    sync_log = AmazonSyncLog(
        amazon_account_id=account.id,
        operation=AmazonSyncOperation.MARKETPLACE_REFRESH,
        status=AmazonSyncStatus.FAILED,
        safe_detail={"participation_count": 2},
        error_code="AMAZON_RESPONSE_INVALID",
    )
    db_session.add(sync_log)
    db_session.commit()

    rendered = repr(sync_log)
    assert "participation_count" not in rendered
    assert "safe_detail" not in rendered
