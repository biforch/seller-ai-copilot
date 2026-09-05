from __future__ import annotations

import uuid

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.integrations.amazon.exceptions import (
    AMAZON_ACCOUNT_ALREADY_EXISTS,
    AMAZON_ACCOUNT_NOT_FOUND,
    AMAZON_CONFIG_INVALID,
    AmazonError,
)
from app.integrations.amazon.token_encryption import TokenEncryptionService
from app.models.amazon_account import AmazonAccount, AmazonAccountStatus
from app.services.amazon_account_service import AmazonAccountService, AmazonAccountSummary
from tests.fixtures.amazon_a32 import (
    FAKE_A32_REFRESH_TOKEN,
    OTHER_FAKE_A32_REFRESH_TOKEN,
    create_account_via_service,
)


def test_create_account_round_trip(db_session: Session, token_encryption_service: TokenEncryptionService, user_factory) -> None:
    user = user_factory("amazon-create@example.com")
    service = AmazonAccountService(db_session, token_encryption_service)
    summary = service.create_account(
        user_id=user.id,
        region="na",
        endpoint_mode="sandbox",
        plaintext_refresh_token=FAKE_A32_REFRESH_TOKEN,
    )
    assert isinstance(summary, AmazonAccountSummary)
    stored = db_session.get(AmazonAccount, summary.id)
    assert stored is not None
    assert stored.refresh_token_ciphertext
    assert stored.refresh_token_ciphertext != FAKE_A32_REFRESH_TOKEN.encode()


def test_create_account_summary_excludes_sensitive_fields(
    db_session: Session,
    token_encryption_service: TokenEncryptionService,
    user_factory,
) -> None:
    user = user_factory("amazon-summary@example.com")
    service = AmazonAccountService(db_session, token_encryption_service)
    summary = service.create_account(
        user_id=user.id,
        region="na",
        endpoint_mode="production",
        plaintext_refresh_token=FAKE_A32_REFRESH_TOKEN,
    )
    rendered = repr(summary)
    assert FAKE_A32_REFRESH_TOKEN not in rendered
    assert not hasattr(summary, "refresh_token_ciphertext")
    assert not hasattr(summary, "refresh_token_fingerprint")
    assert not hasattr(summary, "account_key")


def test_duplicate_same_user_same_token_rejected(
    db_session: Session,
    token_encryption_service: TokenEncryptionService,
    user_factory,
) -> None:
    user = user_factory("amazon-dup@example.com")
    service = AmazonAccountService(db_session, token_encryption_service)
    service.create_account(
        user_id=user.id,
        region="na",
        endpoint_mode="sandbox",
        plaintext_refresh_token=FAKE_A32_REFRESH_TOKEN,
    )
    with pytest.raises(AmazonError) as exc_info:
        service.create_account(
            user_id=user.id,
            region="eu",
            endpoint_mode="production",
            plaintext_refresh_token=FAKE_A32_REFRESH_TOKEN,
        )
    assert exc_info.value.error_code == AMAZON_ACCOUNT_ALREADY_EXISTS


def test_different_users_may_use_same_fake_token(
    db_session: Session,
    token_encryption_service: TokenEncryptionService,
    user_factory,
) -> None:
    user_a = user_factory("amazon-user-a@example.com")
    user_b = user_factory("amazon-user-b@example.com")
    service = AmazonAccountService(db_session, token_encryption_service)
    service.create_account(
        user_id=user_a.id,
        region="na",
        endpoint_mode="sandbox",
        plaintext_refresh_token=FAKE_A32_REFRESH_TOKEN,
    )
    service.create_account(
        user_id=user_b.id,
        region="na",
        endpoint_mode="sandbox",
        plaintext_refresh_token=FAKE_A32_REFRESH_TOKEN,
    )


def test_get_and_list_are_tenant_scoped(
    db_session: Session,
    token_encryption_service: TokenEncryptionService,
    user_factory,
) -> None:
    owner = user_factory("amazon-owner@example.com")
    other = user_factory("amazon-other@example.com")
    service = AmazonAccountService(db_session, token_encryption_service)
    created = service.create_account(
        user_id=owner.id,
        region="na",
        endpoint_mode="sandbox",
        plaintext_refresh_token=FAKE_A32_REFRESH_TOKEN,
    )
    assert service.get_account_for_user(user_id=owner.id, account_id=created.id).id == created.id
    with pytest.raises(AmazonError) as exc_info:
        service.get_account_for_user(user_id=other.id, account_id=created.id)
    assert exc_info.value.error_code == AMAZON_ACCOUNT_NOT_FOUND

    listed = service.list_accounts_for_user(user_id=owner.id)
    assert len(listed) == 1
    assert listed[0].id == created.id
    assert service.list_accounts_for_user(user_id=other.id) == []


def test_disable_account_is_tenant_scoped(
    db_session: Session,
    token_encryption_service: TokenEncryptionService,
    user_factory,
) -> None:
    owner = user_factory("amazon-disable-owner@example.com")
    other = user_factory("amazon-disable-other@example.com")
    service = AmazonAccountService(db_session, token_encryption_service)
    created = service.create_account(
        user_id=owner.id,
        region="na",
        endpoint_mode="sandbox",
        plaintext_refresh_token=OTHER_FAKE_A32_REFRESH_TOKEN,
    )
    disabled = service.disable_account(user_id=owner.id, account_id=created.id)
    assert disabled.status == AmazonAccountStatus.DISABLED
    with pytest.raises(AmazonError) as exc_info:
        service.disable_account(user_id=other.id, account_id=created.id)
    assert exc_info.value.error_code == AMAZON_ACCOUNT_NOT_FOUND


def test_invalid_crypto_config_fail_closed() -> None:
    with pytest.raises(ValueError):
        from app.integrations.amazon.token_encryption import TokenEncryptionConfig

        TokenEncryptionConfig(
            active_key_version=1,
            keys={},
            fingerprint_pepper=b"x" * 32,
        )


def test_other_integrity_error_is_not_mapped(
    db_session: Session,
    token_encryption_service: TokenEncryptionService,
    user_factory,
    monkeypatch,
) -> None:
    user = user_factory("amazon-integrity@example.com")
    service = AmazonAccountService(db_session, token_encryption_service)

    def boom(*args, **kwargs):
        raise IntegrityError("insert", {}, Exception("some other constraint"))

    monkeypatch.setattr(db_session, "commit", boom)
    with pytest.raises(IntegrityError):
        service.create_account(
            user_id=user.id,
            region="na",
            endpoint_mode="sandbox",
            plaintext_refresh_token=FAKE_A32_REFRESH_TOKEN,
        )


def test_disable_account_finalizes_processing_log(
    db_session: Session,
    token_encryption_service: TokenEncryptionService,
    user_factory,
) -> None:
    from app.integrations.amazon.exceptions import AMAZON_ACCOUNT_DISABLED
    from app.models.amazon_sync_log import AmazonSyncLog, AmazonSyncOperation, AmazonSyncStatus

    user, summary = create_account_via_service(
        db_session,
        user_factory,
        token_encryption_service,
        token=FAKE_A32_REFRESH_TOKEN,
    )
    log = AmazonSyncLog(
        amazon_account_id=summary.id,
        operation=AmazonSyncOperation.MARKETPLACE_REFRESH,
        status=AmazonSyncStatus.PROCESSING,
    )
    db_session.add(log)
    db_session.commit()

    service = AmazonAccountService(db_session, token_encryption_service)
    disabled = service.disable_account(user_id=user.id, account_id=summary.id)
    assert disabled.status == AmazonAccountStatus.DISABLED
    again = service.disable_account(user_id=user.id, account_id=summary.id)
    assert again.status == AmazonAccountStatus.DISABLED

    refreshed = db_session.get(AmazonSyncLog, log.id)
    assert refreshed is not None
    assert refreshed.status == AmazonSyncStatus.FAILED
    assert refreshed.error_code == AMAZON_ACCOUNT_DISABLED


def test_invalid_region_rejected(
    db_session: Session,
    token_encryption_service: TokenEncryptionService,
    user_factory,
) -> None:
    user = user_factory("amazon-bad-region@example.com")
    service = AmazonAccountService(db_session, token_encryption_service)
    with pytest.raises(AmazonError) as exc_info:
        service.create_account(
            user_id=user.id,
            region="xx",
            endpoint_mode="sandbox",
            plaintext_refresh_token=FAKE_A32_REFRESH_TOKEN,
        )
    assert exc_info.value.error_code == AMAZON_CONFIG_INVALID


def test_disconnect_account_removes_tokens_listings_and_snapshots(
    db_session: Session,
    token_encryption_service: TokenEncryptionService,
    user_factory,
) -> None:
    from datetime import UTC, datetime

    from app.models.amazon_listing import AmazonListing
    from app.models.generation import Generation
    from app.models.listing_audit_snapshot import ListingAuditSnapshot

    user, summary = create_account_via_service(
        db_session,
        user_factory,
        token_encryption_service,
        token=FAKE_A32_REFRESH_TOKEN,
    )
    now = datetime.now(UTC)
    listing = AmazonListing(
        amazon_account_id=summary.id,
        marketplace_id="ATVPDKIKX0DER",
        seller_sku="DISCONNECT-SKU",
        asin="B012345678",
        status_codes=["BUYABLE"],
        product_type="PRODUCT",
        is_active=True,
        first_seen_at=now,
        last_seen_at=now,
        created_at=now,
        updated_at=now,
    )
    db_session.add(listing)
    db_session.commit()
    db_session.refresh(listing)

    snapshot = ListingAuditSnapshot(
        user_id=user.id,
        amazon_listing_id=listing.id,
        source="amazon",
        marketplace="US",
        asin=listing.asin,
        seller_sku=listing.seller_sku,
        title="Disconnect title",
        bullets=["one"],
        description="Disconnect description",
        specifications={},
        image_urls=[],
        content_hash="a" * 64,
    )
    db_session.add(snapshot)
    db_session.commit()
    db_session.refresh(snapshot)

    report_id = uuid.uuid4()
    db_session.add(
        Generation(
            id=report_id,
            user_id=user.id,
            type="listing_audit",
            input={"snapshot_id": str(snapshot.id), "listing": {"title": "Disconnect title"}},
            output={"report_id": str(report_id)},
            tokens_used=100,
        )
    )
    db_session.commit()

    listing_id = listing.id
    snapshot_id = snapshot.id
    service = AmazonAccountService(db_session, token_encryption_service)
    result = service.disconnect_account(user_id=user.id, account_id=summary.id)
    assert result.already_disconnected is False
    assert result.disconnected_at is not None
    assert db_session.get(AmazonAccount, summary.id) is None
    assert db_session.get(AmazonListing, listing_id) is None
    assert db_session.get(ListingAuditSnapshot, snapshot_id) is None
    assert db_session.get(Generation, report_id) is None


def test_disconnect_account_is_idempotent_for_missing_account(
    db_session: Session,
    token_encryption_service: TokenEncryptionService,
    user_factory,
) -> None:
    user = user_factory("amazon-disconnect-idempotent@example.com")
    missing_id = uuid.uuid4()
    service = AmazonAccountService(db_session, token_encryption_service)
    result = service.disconnect_account(user_id=user.id, account_id=missing_id)
    assert result.account_id == missing_id
    assert result.already_disconnected is True
    assert result.disconnected_at is None


def test_disconnect_account_is_tenant_scoped(
    db_session: Session,
    token_encryption_service: TokenEncryptionService,
    user_factory,
) -> None:
    owner, summary = create_account_via_service(
        db_session,
        user_factory,
        token_encryption_service,
        token=FAKE_A32_REFRESH_TOKEN,
    )
    other = user_factory("amazon-disconnect-other@example.com")
    service = AmazonAccountService(db_session, token_encryption_service)
    result = service.disconnect_account(user_id=other.id, account_id=summary.id)
    assert result.already_disconnected is True
    assert db_session.get(AmazonAccount, summary.id) is not None
    owner_result = service.disconnect_account(user_id=owner.id, account_id=summary.id)
    assert owner_result.already_disconnected is False
