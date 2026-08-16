"""Amazon OAuth account connect and reauthorize persistence tests."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.integrations.amazon.exceptions import (
    AMAZON_ACCOUNT_NOT_FOUND,
    AMAZON_CONFIG_INVALID,
    AMAZON_OAUTH_ACCOUNT_PERSIST_FAILED,
    AMAZON_OAUTH_SELLER_ALREADY_LINKED,
    AMAZON_OAUTH_SELLER_INVALID,
    AMAZON_OAUTH_SELLER_MISMATCH,
    AMAZON_OAUTH_TOKEN_EXCHANGE_FAILED,
    AMAZON_OAUTH_USER_NOT_FOUND,
    AMAZON_SYNC_IN_PROGRESS,
    AmazonError,
    amazon_config_invalid_error,
)
from app.integrations.amazon.token_encryption import TokenEncryptionService
from app.models.amazon_account import (
    SELLING_PARTNER_ID_UNIQUE_CONSTRAINT,
    AmazonAccount,
    AmazonAccountStatus,
)
from app.models.amazon_listing import AmazonListing
from app.models.amazon_marketplace_participation import AmazonMarketplaceParticipation
from app.models.amazon_sync_log import AmazonSyncLog, AmazonSyncOperation, AmazonSyncStatus
from app.models.product import Product
from app.models.project import Project
from app.services.amazon_account_service import (
    FINGERPRINT_UNIQUE_CONSTRAINT,
    AmazonAccountService,
    AmazonAccountSummary,
)
from tests.fixtures.amazon_a32 import FAKE_A32_REFRESH_TOKEN

CANARY_TOKEN = "CANARY_OAUTH_REFRESH_TOKEN_XYZ"
CANARY_SELLER = "CANARYSELLER123456"
OTHER_OAUTH_TOKEN = "other-oauth-refresh-token-valid"
OAUTH_SELLER_ID = "OAuthSeller12345"
EU_OAUTH_SELLER_ID = "OAuthSellerEU1234"


class FixedClock:
    def __init__(self, current: datetime) -> None:
        if current.tzinfo is None:
            current = current.replace(tzinfo=UTC)
        self._current = current

    def __call__(self) -> datetime:
        return self._current


def _service(
    db_session: Session,
    token_encryption_service: TokenEncryptionService,
    *,
    clock: FixedClock | None = None,
) -> AmazonAccountService:
    return AmazonAccountService(
        db_session,
        token_encryption_service,
        clock=clock or FixedClock(datetime(2026, 3, 1, 12, 0, tzinfo=UTC)),
    )


def _connect(
    service: AmazonAccountService,
    user_id: uuid.UUID,
    *,
    region: str = "na",
    seller_id: str = OAUTH_SELLER_ID,
    token: str = FAKE_A32_REFRESH_TOKEN,
) -> AmazonAccountSummary:
    return service.connect_account_from_oauth(
        user_id=user_id,
        region=region,
        selling_partner_id=seller_id,
        plaintext_refresh_token=token,
    )


def test_oauth_connect_creates_production_account(
    db_session: Session,
    token_encryption_service: TokenEncryptionService,
    user_factory,
) -> None:
    user = user_factory("oauth-connect-create@example.com")
    service = _service(db_session, token_encryption_service)
    summary = _connect(service, user.id)
    stored = db_session.get(AmazonAccount, summary.id)
    assert stored is not None
    assert stored.endpoint_mode == "production"
    assert stored.region == "na"
    assert stored.selling_partner_id == OAUTH_SELLER_ID
    assert stored.status == AmazonAccountStatus.ACTIVE
    assert stored.last_verified_at is None


def test_oauth_connect_encrypts_token_and_fingerprint(
    db_session: Session,
    token_encryption_service: TokenEncryptionService,
    user_factory,
) -> None:
    user = user_factory("oauth-connect-crypto@example.com")
    service = _service(db_session, token_encryption_service)
    summary = _connect(service, user.id, token=OTHER_OAUTH_TOKEN)
    stored = db_session.get(AmazonAccount, summary.id)
    assert stored is not None
    assert stored.refresh_token_ciphertext != OTHER_OAUTH_TOKEN.encode()
    decrypted = token_encryption_service.decrypt_refresh_token(
        stored.refresh_token_ciphertext,
        key_version=stored.refresh_token_key_version,
        user_id=user.id,
        account_id=stored.id,
    )
    assert decrypted == OTHER_OAUTH_TOKEN
    assert stored.refresh_token_fingerprint == token_encryption_service.fingerprint_refresh_token(
        OTHER_OAUTH_TOKEN
    )
    assert stored.refresh_token_key_version == token_encryption_service.active_key_version


def test_oauth_connect_summary_excludes_sensitive_fields(
    db_session: Session,
    token_encryption_service: TokenEncryptionService,
    user_factory,
) -> None:
    user = user_factory("oauth-connect-summary@example.com")
    service = _service(db_session, token_encryption_service)
    summary = _connect(service, user.id, token=CANARY_TOKEN, seller_id=CANARY_SELLER)
    rendered = repr(summary)
    assert CANARY_TOKEN not in rendered
    assert CANARY_SELLER not in rendered
    assert not hasattr(summary, "account_key")
    assert not hasattr(summary, "selling_partner_id")
    assert not hasattr(summary, "refresh_token_ciphertext")


def test_oauth_connect_user_not_found(
    db_session: Session,
    token_encryption_service: TokenEncryptionService,
) -> None:
    service = _service(db_session, token_encryption_service)
    with pytest.raises(AmazonError) as exc_info:
        _connect(service, uuid.uuid4())
    assert exc_info.value.error_code == AMAZON_OAUTH_USER_NOT_FOUND


@pytest.mark.parametrize("region", ["", "  ", "ap", "NA "])
def test_oauth_connect_invalid_region(
    db_session: Session,
    token_encryption_service: TokenEncryptionService,
    user_factory,
    region: str,
) -> None:
    user = user_factory(f"oauth-invalid-region-{abs(hash(region))}@example.com")
    service = _service(db_session, token_encryption_service)
    with pytest.raises(AmazonError) as exc_info:
        _connect(service, user.id, region=region)
    assert exc_info.value.error_code == AMAZON_CONFIG_INVALID


@pytest.mark.parametrize(
    "seller_id",
    ["", "   ", "seller-dash", "seller.dot", "a" * 33, "bad space"],
)
def test_oauth_connect_invalid_seller_id(
    db_session: Session,
    token_encryption_service: TokenEncryptionService,
    user_factory,
    seller_id: str,
) -> None:
    user = user_factory(f"oauth-invalid-seller-{abs(hash(seller_id))}@example.com")
    service = _service(db_session, token_encryption_service)
    with pytest.raises(AmazonError) as exc_info:
        _connect(service, user.id, seller_id=seller_id)
    assert exc_info.value.error_code == AMAZON_OAUTH_SELLER_INVALID
    if seller_id.strip():
        assert seller_id not in str(exc_info.value)


@pytest.mark.parametrize(
    "token",
    ["", "   ", " padded", "padded ", "a" * 8193, "bad\x01token"],
)
def test_oauth_connect_invalid_token(
    db_session: Session,
    token_encryption_service: TokenEncryptionService,
    user_factory,
    token: str,
) -> None:
    user = user_factory(f"oauth-invalid-token-{abs(hash(token))}@example.com")
    service = _service(db_session, token_encryption_service)
    with pytest.raises(AmazonError) as exc_info:
        _connect(service, user.id, token=token)
    assert exc_info.value.error_code == AMAZON_OAUTH_TOKEN_EXCHANGE_FAILED
    if token.strip():
        assert token not in str(exc_info.value)


def test_oauth_connect_same_user_rotates_token_and_preserves_identity(
    db_session: Session,
    token_encryption_service: TokenEncryptionService,
    user_factory,
) -> None:
    user = user_factory("oauth-connect-rotate@example.com")
    service = _service(db_session, token_encryption_service)
    first = _connect(service, user.id)
    stored = db_session.get(AmazonAccount, first.id)
    assert stored is not None
    original_key = stored.account_key
    original_created_at = stored.created_at
    stored.last_verified_at = datetime(2026, 1, 1, tzinfo=UTC)
    db_session.add(
        AmazonMarketplaceParticipation(
            amazon_account_id=stored.id,
            marketplace_id="ATVPDKIKX0DER",
            marketplace_name="Amazon.com",
            country_code="US",
            participating=True,
            suspended_listings=False,
        )
    )
    project = Project(
        user_id=user.id,
        name="oauth project",
        platform="Amazon",
        market="USA",
    )
    db_session.add(project)
    db_session.flush()
    product = Product(
        user_id=user.id,
        project_id=project.id,
        name="oauth product",
        category="Electronics",
        platform="Amazon",
        market="USA",
    )
    db_session.add(product)
    db_session.flush()
    now = datetime.now(UTC)
    listing = AmazonListing(
        amazon_account_id=stored.id,
        marketplace_id="ATVPDKIKX0DER",
        seller_sku="SKU-OAUTH-1",
        asin="B012345678",
        product_id=product.id,
        status_codes=["BUYABLE"],
        product_type="PRODUCT",
        upstream_created_at=now,
        upstream_last_updated_at=now,
        first_seen_at=now,
        last_seen_at=now,
    )
    db_session.add(listing)
    db_session.commit()

    second = _connect(service, user.id, token=OTHER_OAUTH_TOKEN)
    refreshed = db_session.get(AmazonAccount, first.id)
    assert refreshed is not None
    assert second.id == first.id
    assert refreshed.account_key == original_key
    assert refreshed.created_at == original_created_at
    assert refreshed.last_verified_at == datetime(2026, 1, 1, tzinfo=UTC)
    assert refreshed.selling_partner_id == OAUTH_SELLER_ID
    decrypted = token_encryption_service.decrypt_refresh_token(
        refreshed.refresh_token_ciphertext,
        key_version=refreshed.refresh_token_key_version,
        user_id=user.id,
        account_id=refreshed.id,
    )
    assert decrypted == OTHER_OAUTH_TOKEN
    assert (
        db_session.query(AmazonMarketplaceParticipation)
        .filter_by(amazon_account_id=first.id)
        .count()
        == 1
    )
    persisted_listing = db_session.query(AmazonListing).filter_by(amazon_account_id=first.id).one()
    assert persisted_listing.product_id == product.id


@pytest.mark.parametrize(
    "status",
    [
        AmazonAccountStatus.DISABLED,
        AmazonAccountStatus.REAUTHORIZATION_REQUIRED,
        AmazonAccountStatus.ERROR,
    ],
)
def test_oauth_connect_restores_non_active_status(
    db_session: Session,
    token_encryption_service: TokenEncryptionService,
    user_factory,
    status: str,
) -> None:
    user = user_factory(f"oauth-connect-restore-{status}@example.com")
    service = _service(db_session, token_encryption_service)
    summary = _connect(service, user.id)
    stored = db_session.get(AmazonAccount, summary.id)
    assert stored is not None
    stored.status = status
    db_session.commit()
    _connect(service, user.id, token=OTHER_OAUTH_TOKEN)
    db_session.refresh(stored)
    assert stored.status == AmazonAccountStatus.ACTIVE


def test_oauth_connect_same_user_different_region_rejected(
    db_session: Session,
    token_encryption_service: TokenEncryptionService,
    user_factory,
) -> None:
    user = user_factory("oauth-connect-region-mismatch@example.com")
    service = _service(db_session, token_encryption_service)
    _connect(service, user.id, region="na", seller_id=EU_OAUTH_SELLER_ID)
    with pytest.raises(AmazonError) as exc_info:
        _connect(service, user.id, region="eu", seller_id=EU_OAUTH_SELLER_ID)
    assert exc_info.value.error_code == AMAZON_OAUTH_SELLER_ALREADY_LINKED


def test_oauth_connect_different_user_same_seller_rejected(
    db_session: Session,
    token_encryption_service: TokenEncryptionService,
    user_factory,
) -> None:
    owner = user_factory("oauth-connect-owner@example.com")
    challenger = user_factory("oauth-connect-challenger@example.com")
    service = _service(db_session, token_encryption_service)
    _connect(service, owner.id)
    with pytest.raises(AmazonError) as exc_info:
        _connect(service, challenger.id)
    assert exc_info.value.error_code == AMAZON_OAUTH_SELLER_ALREADY_LINKED


def test_oauth_connect_rejects_active_lease(
    db_session: Session,
    token_encryption_service: TokenEncryptionService,
    user_factory,
) -> None:
    user = user_factory("oauth-connect-active-lease@example.com")
    clock = FixedClock(datetime(2026, 3, 1, 12, 0, tzinfo=UTC))
    service = _service(db_session, token_encryption_service, clock=clock)
    summary = _connect(service, user.id)
    stored = db_session.get(AmazonAccount, summary.id)
    assert stored is not None
    stored.sync_lease_id = uuid.uuid4()
    stored.sync_lease_expires_at = clock() + timedelta(minutes=5)
    db_session.commit()
    with pytest.raises(AmazonError) as exc_info:
        _connect(service, user.id, token=OTHER_OAUTH_TOKEN)
    assert exc_info.value.error_code == AMAZON_SYNC_IN_PROGRESS


def test_oauth_connect_allows_expired_lease_without_clearing(
    db_session: Session,
    token_encryption_service: TokenEncryptionService,
    user_factory,
) -> None:
    user = user_factory("oauth-connect-expired-lease@example.com")
    clock = FixedClock(datetime(2026, 3, 1, 12, 0, tzinfo=UTC))
    service = _service(db_session, token_encryption_service, clock=clock)
    summary = _connect(service, user.id)
    stored = db_session.get(AmazonAccount, summary.id)
    assert stored is not None
    lease_id = uuid.uuid4()
    stored.sync_lease_id = lease_id
    stored.sync_lease_expires_at = clock() - timedelta(minutes=1)
    db_session.add(
        AmazonSyncLog(
            amazon_account_id=stored.id,
            operation=AmazonSyncOperation.PRODUCT_SYNC,
            status=AmazonSyncStatus.PROCESSING,
        )
    )
    db_session.commit()
    _connect(service, user.id, token=OTHER_OAUTH_TOKEN)
    db_session.refresh(stored)
    assert stored.sync_lease_id == lease_id
    assert stored.sync_lease_expires_at == clock() - timedelta(minutes=1)
    assert (
        db_session.query(AmazonSyncLog)
        .filter_by(amazon_account_id=stored.id, status=AmazonSyncStatus.PROCESSING)
        .count()
        == 1
    )


def test_oauth_reauthorize_rotates_token(
    db_session: Session,
    token_encryption_service: TokenEncryptionService,
    user_factory,
) -> None:
    user = user_factory("oauth-reauth-success@example.com")
    service = _service(db_session, token_encryption_service)
    created = _connect(service, user.id)
    summary = service.reauthorize_account_from_oauth(
        user_id=user.id,
        account_id=created.id,
        selling_partner_id=OAUTH_SELLER_ID,
        plaintext_refresh_token=OTHER_OAUTH_TOKEN,
    )
    stored = db_session.get(AmazonAccount, summary.id)
    assert stored is not None
    decrypted = token_encryption_service.decrypt_refresh_token(
        stored.refresh_token_ciphertext,
        key_version=stored.refresh_token_key_version,
        user_id=user.id,
        account_id=stored.id,
    )
    assert decrypted == OTHER_OAUTH_TOKEN
    assert stored.status == AmazonAccountStatus.ACTIVE


def test_oauth_reauthorize_tenant_mismatch_not_found(
    db_session: Session,
    token_encryption_service: TokenEncryptionService,
    user_factory,
) -> None:
    owner = user_factory("oauth-reauth-owner@example.com")
    other = user_factory("oauth-reauth-other@example.com")
    service = _service(db_session, token_encryption_service)
    created = _connect(service, owner.id, seller_id="ReauthSeller1234")
    with pytest.raises(AmazonError) as exc_info:
        service.reauthorize_account_from_oauth(
            user_id=other.id,
            account_id=created.id,
            selling_partner_id="ReauthSeller1234",
            plaintext_refresh_token=OTHER_OAUTH_TOKEN,
        )
    assert exc_info.value.error_code == AMAZON_ACCOUNT_NOT_FOUND


def test_oauth_reauthorize_empty_account_seller_rejected(
    db_session: Session,
    token_encryption_service: TokenEncryptionService,
    user_factory,
) -> None:
    user = user_factory("oauth-reauth-empty-seller@example.com")
    service = _service(db_session, token_encryption_service)
    created = _connect(service, user.id, seller_id="EmptySellerCase1")
    stored = db_session.get(AmazonAccount, created.id)
    assert stored is not None
    stored.selling_partner_id = None
    db_session.commit()
    with pytest.raises(AmazonError) as exc_info:
        service.reauthorize_account_from_oauth(
            user_id=user.id,
            account_id=created.id,
            selling_partner_id="EmptySellerCase1",
            plaintext_refresh_token=OTHER_OAUTH_TOKEN,
        )
    assert exc_info.value.error_code == AMAZON_OAUTH_SELLER_MISMATCH


def test_oauth_reauthorize_seller_mismatch_rejected(
    db_session: Session,
    token_encryption_service: TokenEncryptionService,
    user_factory,
) -> None:
    user = user_factory("oauth-reauth-mismatch@example.com")
    service = _service(db_session, token_encryption_service)
    created = _connect(service, user.id, seller_id="ReauthMatchSeller1")
    with pytest.raises(AmazonError) as exc_info:
        service.reauthorize_account_from_oauth(
            user_id=user.id,
            account_id=created.id,
            selling_partner_id="DifferentSeller1",
            plaintext_refresh_token=OTHER_OAUTH_TOKEN,
        )
    assert exc_info.value.error_code == AMAZON_OAUTH_SELLER_MISMATCH


def test_oauth_reauthorize_sandbox_account_rejected(
    db_session: Session,
    token_encryption_service: TokenEncryptionService,
    user_factory,
) -> None:
    user = user_factory("oauth-reauth-sandbox@example.com")
    legacy = AmazonAccountService(db_session, token_encryption_service)
    sandbox = legacy.create_account(
        user_id=user.id,
        region="na",
        endpoint_mode="sandbox",
        plaintext_refresh_token=FAKE_A32_REFRESH_TOKEN,
    )
    stored = db_session.get(AmazonAccount, sandbox.id)
    assert stored is not None
    stored.selling_partner_id = "SandboxSeller1234"
    db_session.commit()
    service = _service(db_session, token_encryption_service)
    with pytest.raises(AmazonError) as exc_info:
        service.reauthorize_account_from_oauth(
            user_id=user.id,
            account_id=sandbox.id,
            selling_partner_id="SandboxSeller1234",
            plaintext_refresh_token=OTHER_OAUTH_TOKEN,
        )
    assert exc_info.value.error_code == AMAZON_CONFIG_INVALID


def test_oauth_reauthorize_rejects_active_lease(
    db_session: Session,
    token_encryption_service: TokenEncryptionService,
    user_factory,
) -> None:
    user = user_factory("oauth-reauth-active-lease@example.com")
    clock = FixedClock(datetime(2026, 3, 1, 12, 0, tzinfo=UTC))
    service = _service(db_session, token_encryption_service, clock=clock)
    created = _connect(service, user.id, seller_id="ReauthLeaseSeller1")
    stored = db_session.get(AmazonAccount, created.id)
    assert stored is not None
    stored.sync_lease_id = uuid.uuid4()
    stored.sync_lease_expires_at = clock() + timedelta(minutes=5)
    db_session.commit()
    with pytest.raises(AmazonError) as exc_info:
        service.reauthorize_account_from_oauth(
            user_id=user.id,
            account_id=created.id,
            selling_partner_id="ReauthLeaseSeller1",
            plaintext_refresh_token=OTHER_OAUTH_TOKEN,
        )
    assert exc_info.value.error_code == AMAZON_SYNC_IN_PROGRESS


@pytest.mark.parametrize(
    "status",
    [
        AmazonAccountStatus.DISABLED,
        AmazonAccountStatus.REAUTHORIZATION_REQUIRED,
        AmazonAccountStatus.ERROR,
    ],
)
def test_oauth_reauthorize_restores_non_active_status(
    db_session: Session,
    token_encryption_service: TokenEncryptionService,
    user_factory,
    status: str,
) -> None:
    user = user_factory(f"oauth-reauth-restore-{status}@example.com")
    service = _service(db_session, token_encryption_service)
    seller = f"ReauthRestore{status[:4]}"
    created = _connect(service, user.id, seller_id=seller)
    stored = db_session.get(AmazonAccount, created.id)
    assert stored is not None
    stored.status = status
    db_session.commit()
    service.reauthorize_account_from_oauth(
        user_id=user.id,
        account_id=created.id,
        selling_partner_id=seller,
        plaintext_refresh_token=OTHER_OAUTH_TOKEN,
    )
    db_session.refresh(stored)
    assert stored.status == AmazonAccountStatus.ACTIVE


def test_oauth_reauthorize_preserves_last_verified_at(
    db_session: Session,
    token_encryption_service: TokenEncryptionService,
    user_factory,
) -> None:
    user = user_factory("oauth-reauth-last-verified@example.com")
    service = _service(db_session, token_encryption_service)
    seller = "ReauthVerified1234"
    created = _connect(service, user.id, seller_id=seller)
    stored = db_session.get(AmazonAccount, created.id)
    assert stored is not None
    verified_at = datetime(2026, 2, 1, 8, 30, tzinfo=UTC)
    stored.last_verified_at = verified_at
    db_session.commit()
    service.reauthorize_account_from_oauth(
        user_id=user.id,
        account_id=created.id,
        selling_partner_id=seller,
        plaintext_refresh_token=OTHER_OAUTH_TOKEN,
    )
    db_session.refresh(stored)
    assert stored.last_verified_at == verified_at


def test_oauth_connect_encryption_failure_rolls_back(
    db_session: Session,
    token_encryption_service: TokenEncryptionService,
    user_factory,
) -> None:
    user = user_factory("oauth-connect-encrypt-fail@example.com")
    user_id = user.id
    failing_encryption = MagicMock(spec=TokenEncryptionService)

    def _raise_config_error(_token: str) -> str:
        raise amazon_config_invalid_error("encryption config invalid")

    failing_encryption.fingerprint_refresh_token.side_effect = _raise_config_error
    service = _service(db_session, failing_encryption)
    with pytest.raises(AmazonError):
        _connect(service, user_id, seller_id="EncryptFailSeller1")
    assert db_session.query(AmazonAccount).filter_by(user_id=user_id).count() == 0


def _integrity_error(constraint_name: str) -> IntegrityError:
    exc = IntegrityError("insert", {}, Exception("duplicate"))
    exc.orig = Exception("duplicate")
    exc.orig.diag = MagicMock(constraint_name=constraint_name)
    return exc


@pytest.mark.parametrize(
    ("constraint_name", "seller_id"),
    [
        (SELLING_PARTNER_ID_UNIQUE_CONSTRAINT, "SellerUniqueConflict1"),
        (FINGERPRINT_UNIQUE_CONSTRAINT, "SellerFingerprintConflict1"),
    ],
)
def test_oauth_connect_integrity_error_maps_to_seller_already_linked(
    db_session: Session,
    token_encryption_service: TokenEncryptionService,
    user_factory,
    monkeypatch: pytest.MonkeyPatch,
    constraint_name: str,
    seller_id: str,
) -> None:
    user = user_factory(f"oauth-connect-integrity-{seller_id.lower()}@example.com")
    user_id = user.id
    service = _service(db_session, token_encryption_service)

    def _commit_raises() -> None:
        raise _integrity_error(constraint_name)

    monkeypatch.setattr(db_session, "commit", _commit_raises)
    with pytest.raises(AmazonError) as exc_info:
        _connect(service, user.id, seller_id=seller_id)
    assert exc_info.value.error_code == AMAZON_OAUTH_SELLER_ALREADY_LINKED
    assert exc_info.value.__cause__ is None
    assert db_session.query(AmazonAccount).filter_by(user_id=user_id).count() == 0


def test_oauth_connect_unknown_integrity_error_maps_to_persist_failed(
    db_session: Session,
    token_encryption_service: TokenEncryptionService,
    user_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = user_factory("oauth-connect-unknown-integrity@example.com")
    user_id = user.id
    service = _service(db_session, token_encryption_service)

    def _commit_raises() -> None:
        raise _integrity_error("uq_unknown_constraint_xyz")

    monkeypatch.setattr(db_session, "commit", _commit_raises)
    with pytest.raises(AmazonError) as exc_info:
        _connect(service, user.id, seller_id="UnknownIntegrity1")
    assert exc_info.value.error_code == AMAZON_OAUTH_ACCOUNT_PERSIST_FAILED
    assert exc_info.value.__cause__ is None
    assert "uq_unknown_constraint_xyz" not in str(exc_info.value)
    assert db_session.query(AmazonAccount).filter_by(user_id=user_id).count() == 0


def test_oauth_connect_commit_failure_maps_to_persist_failed(
    db_session: Session,
    token_encryption_service: TokenEncryptionService,
    user_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = user_factory("oauth-connect-commit-fail@example.com")
    service = _service(db_session, token_encryption_service)

    def _commit_raises() -> None:
        raise RuntimeError("db unavailable")

    monkeypatch.setattr(db_session, "commit", _commit_raises)
    with pytest.raises(AmazonError) as exc_info:
        _connect(service, user.id, seller_id="CommitFailSeller1")
    assert exc_info.value.error_code == AMAZON_OAUTH_ACCOUNT_PERSIST_FAILED
    assert exc_info.value.__cause__ is None


def test_oauth_errors_do_not_leak_canary_values(
    db_session: Session,
    token_encryption_service: TokenEncryptionService,
    user_factory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    user = user_factory("oauth-connect-canary@example.com")
    service = _service(db_session, token_encryption_service)
    with pytest.raises(AmazonError):
        _connect(
            service,
            user.id,
            seller_id="bad seller",
            token=CANARY_TOKEN,
        )
    assert CANARY_TOKEN not in caplog.text
    assert CANARY_SELLER not in caplog.text
