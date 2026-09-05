"""Tests for administrative user-account deletion."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.models.amazon_account import AmazonAccount
from app.models.amazon_listing import AmazonListing
from app.models.generation import Generation
from app.models.listing_audit_snapshot import ListingAuditSnapshot
from app.models.user import User
from app.services.amazon_account_service import AmazonAccountService
from app.services.user_account_deletion_service import UserAccountDeletionService
from tests.fixtures.amazon_a32 import FAKE_A32_REFRESH_TOKEN, create_account_via_service


def test_delete_user_account_removes_amazon_data_and_audits(
    db_session,
    user_factory,
    token_encryption_service,
):
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
        seller_sku="ADMIN-DELETE-SKU",
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
        title="Delete me",
        bullets=["one"],
        description="Delete me",
        specifications={},
        image_urls=[],
        content_hash="b" * 64,
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
            input={"snapshot_id": str(snapshot.id)},
            output={"report_id": str(report_id)},
            tokens_used=1,
        )
    )
    db_session.commit()
    user_id = user.id

    service = UserAccountDeletionService(db_session, token_encryption_service)
    result = service.delete_user_account(
        user_id=user_id,
        request_reference="support-ticket-001",
    )

    assert result.already_deleted is False
    assert result.amazon_accounts_removed == 1
    assert result.deleted_at is not None
    assert db_session.get(User, user_id) is None
    assert db_session.get(AmazonAccount, summary.id) is None
    assert db_session.get(ListingAuditSnapshot, snapshot.id) is None
    assert db_session.get(Generation, report_id) is None


def test_delete_user_account_is_idempotent(db_session, user_factory, token_encryption_service):
    user = user_factory("admin-delete-idempotent@example.com")
    service = UserAccountDeletionService(db_session, token_encryption_service)
    first = service.delete_user_account(user_id=user.id)
    second = service.delete_user_account(user_id=user.id)
    assert first.already_deleted is False
    assert second.already_deleted is True


def test_delete_user_by_email_is_tenant_scoped(
    db_session,
    user_factory,
    token_encryption_service,
):
    owner = user_factory("admin-delete-owner@example.com")
    other = user_factory("admin-delete-other@example.com")
    service = UserAccountDeletionService(db_session, token_encryption_service)
    result = service.delete_user_by_email(email=owner.email)
    assert result.already_deleted is False
    assert db_session.get(User, owner.id) is None
    assert db_session.get(User, other.id) is not None


def test_delete_user_dry_run_does_not_mutate(
    db_session,
    user_factory,
    token_encryption_service,
):
    user, summary = create_account_via_service(
        db_session,
        user_factory,
        token_encryption_service,
        token=f"{FAKE_A32_REFRESH_TOKEN}-dry-run",
    )
    service = UserAccountDeletionService(db_session, token_encryption_service)
    result = service.delete_user_account(user_id=user.id, dry_run=True)
    assert result.amazon_accounts_removed == 1
    assert result.deleted_at is None
    assert db_session.get(User, user.id) is not None
    assert db_session.get(AmazonAccount, summary.id) is not None


def test_delete_user_rejects_cross_user_amazon_account(
    db_session,
    user_factory,
    token_encryption_service,
):
    owner, summary = create_account_via_service(
        db_session,
        user_factory,
        token_encryption_service,
        token=f"{FAKE_A32_REFRESH_TOKEN}-cross-user",
    )
    intruder = user_factory("admin-delete-intruder@example.com")
    amazon_service = AmazonAccountService(db_session, token_encryption_service)
    disconnect = amazon_service.disconnect_account(user_id=intruder.id, account_id=summary.id)
    assert disconnect.already_disconnected is True
    assert db_session.get(AmazonAccount, summary.id) is not None
    del owner
