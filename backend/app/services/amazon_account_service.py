"""Amazon account persistence and tenant-scoped access."""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.integrations.amazon.exceptions import (
    AMAZON_ACCOUNT_DISABLED,
    AmazonError,
    amazon_account_already_exists_error,
    amazon_account_not_found_error,
    amazon_config_invalid_error,
    amazon_oauth_account_persist_failed_error,
    amazon_oauth_seller_already_linked_error,
    amazon_oauth_seller_invalid_error,
    amazon_oauth_seller_mismatch_error,
    amazon_oauth_token_exchange_failed_error,
    amazon_oauth_user_not_found_error,
    amazon_sync_in_progress_error,
)
from app.integrations.amazon.token_encryption import TokenEncryptionService
from app.models.amazon_account import (
    SELLING_PARTNER_ID_UNIQUE_CONSTRAINT,
    AmazonAccount,
    AmazonAccountStatus,
)
from app.models.amazon_listing import AmazonListing
from app.models.amazon_sync_log import AmazonSyncLog, AmazonSyncStatus
from app.models.generation import Generation
from app.models.listing_audit_snapshot import ListingAuditSnapshot
from app.models.user import User
from app.services.amazon_account_read_service import (
    AmazonAccountReadService,
    AmazonAccountSummary,
)
from app.services.amazon_account_read_service import (
    to_account_summary as _to_summary,
)
from app.services.amazon_sync_log_service import AmazonSyncLogService

logger = logging.getLogger(__name__)

LISTING_AUDIT_GENERATION_TYPE = "listing_audit"


@dataclass(frozen=True)
class AmazonAccountDisconnectResult:
    account_id: uuid.UUID
    already_disconnected: bool
    disconnected_at: datetime | None


VALID_REGIONS = frozenset({"na", "eu", "fe"})
VALID_ENDPOINT_MODES = frozenset({"sandbox", "production"})
OAUTH_ACCOUNT_ENDPOINT_MODE = "production"
FINGERPRINT_UNIQUE_CONSTRAINT = "uq_amazon_accounts_user_fingerprint"
MAX_OAUTH_REFRESH_TOKEN_LENGTH = 8192
_SELLER_ID_PATTERN = re.compile(r"^[A-Za-z0-9]{1,32}$")

Clock = Callable[[], datetime]


def _is_fingerprint_unique_violation(exc: IntegrityError) -> bool:
    orig = exc.orig
    if orig is None:
        return FINGERPRINT_UNIQUE_CONSTRAINT in str(exc)
    diag = getattr(orig, "diag", None)
    constraint_name = getattr(diag, "constraint_name", None) if diag is not None else None
    if constraint_name == FINGERPRINT_UNIQUE_CONSTRAINT:
        return True
    return FINGERPRINT_UNIQUE_CONSTRAINT in str(orig)


def _is_seller_unique_violation(exc: IntegrityError) -> bool:
    orig = exc.orig
    if orig is None:
        return SELLING_PARTNER_ID_UNIQUE_CONSTRAINT in str(exc)
    diag = getattr(orig, "diag", None)
    constraint_name = getattr(diag, "constraint_name", None) if diag is not None else None
    if constraint_name == SELLING_PARTNER_ID_UNIQUE_CONSTRAINT:
        return True
    return SELLING_PARTNER_ID_UNIQUE_CONSTRAINT in str(orig)


def _validate_oauth_region(value: object) -> str:
    if not isinstance(value, str) or value != value.strip():
        raise amazon_config_invalid_error("Amazon account region is invalid")
    normalized = value.lower()
    if normalized not in VALID_REGIONS:
        raise amazon_config_invalid_error("Amazon account region is invalid")
    return normalized


def _validate_oauth_selling_partner_id(value: object) -> str:
    if not isinstance(value, str):
        raise amazon_oauth_seller_invalid_error()
    if not _SELLER_ID_PATTERN.fullmatch(value):
        raise amazon_oauth_seller_invalid_error()
    return value


def _validate_oauth_plaintext_refresh_token(value: object) -> str:
    if not isinstance(value, str):
        raise amazon_oauth_token_exchange_failed_error()
    if not value or value != value.strip():
        raise amazon_oauth_token_exchange_failed_error()
    if len(value) > MAX_OAUTH_REFRESH_TOKEN_LENGTH:
        raise amazon_oauth_token_exchange_failed_error()
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise amazon_oauth_token_exchange_failed_error()
    return value


def _utc_now() -> datetime:
    return datetime.now(UTC)


class AmazonAccountService(AmazonAccountReadService):
    def __init__(
        self,
        db: Session,
        encryption_service: TokenEncryptionService,
        *,
        clock: Clock | None = None,
    ) -> None:
        super().__init__(db)
        self._encryption = encryption_service
        self._clock = clock or _utc_now

    def _now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None:
            return now.replace(tzinfo=UTC)
        return now

    @staticmethod
    def _validate_region_endpoint(*, region: str, endpoint_mode: str) -> None:
        if region not in VALID_REGIONS or endpoint_mode not in VALID_ENDPOINT_MODES:
            raise amazon_config_invalid_error("Amazon account region or endpoint mode is invalid")

    def create_account(
        self,
        *,
        user_id: uuid.UUID,
        region: str,
        endpoint_mode: str,
        plaintext_refresh_token: str,
    ) -> AmazonAccountSummary:
        self._validate_region_endpoint(region=region, endpoint_mode=endpoint_mode)
        if not plaintext_refresh_token.strip():
            raise amazon_config_invalid_error("Refresh token is required")

        account_id = uuid.uuid4()
        fingerprint = self._encryption.fingerprint_refresh_token(plaintext_refresh_token)
        ciphertext, key_version = self._encryption.encrypt_refresh_token(
            plaintext_refresh_token,
            user_id=user_id,
            account_id=account_id,
        )

        account = AmazonAccount(
            id=account_id,
            user_id=user_id,
            region=region,
            endpoint_mode=endpoint_mode,
            status=AmazonAccountStatus.ACTIVE,
            refresh_token_ciphertext=ciphertext,
            refresh_token_key_version=key_version,
            refresh_token_fingerprint=fingerprint,
        )
        self._db.add(account)
        try:
            self._db.commit()
        except IntegrityError as exc:
            self._db.rollback()
            if _is_fingerprint_unique_violation(exc):
                raise amazon_account_already_exists_error() from None
            raise
        self._db.refresh(account)
        return _to_summary(account)

    def _ensure_oauth_user_exists(self, user_id: uuid.UUID) -> None:
        if self._db.get(User, user_id) is None:
            raise amazon_oauth_user_not_found_error()

    def _ensure_no_active_sync_lease(self, account: AmazonAccount) -> None:
        now = self._now()
        if (
            account.sync_lease_id is not None
            and account.sync_lease_expires_at is not None
            and account.sync_lease_expires_at > now
        ):
            raise amazon_sync_in_progress_error()

    def _map_oauth_integrity_error(self, exc: IntegrityError) -> AmazonError:
        if _is_seller_unique_violation(exc) or _is_fingerprint_unique_violation(exc):
            return amazon_oauth_seller_already_linked_error()
        return amazon_oauth_account_persist_failed_error()

    def _commit_oauth_account(self, account: AmazonAccount, *, operation: str) -> AmazonAccountSummary:
        try:
            self._db.commit()
        except IntegrityError as exc:
            self._db.rollback()
            raise self._map_oauth_integrity_error(exc) from None
        except AmazonError:
            self._db.rollback()
            raise
        except Exception:
            self._db.rollback()
            logger.warning(
                "OAuth account persistence failure operation=%s category=db account_id=%s",
                operation,
                account.id,
            )
            raise amazon_oauth_account_persist_failed_error() from None
        self._db.refresh(account)
        return _to_summary(account)

    def _apply_oauth_refresh_token(
        self,
        account: AmazonAccount,
        *,
        plaintext_refresh_token: str,
    ) -> None:
        fingerprint = self._encryption.fingerprint_refresh_token(plaintext_refresh_token)
        ciphertext, key_version = self._encryption.encrypt_refresh_token(
            plaintext_refresh_token,
            user_id=account.user_id,
            account_id=account.id,
        )
        account.refresh_token_ciphertext = ciphertext
        account.refresh_token_fingerprint = fingerprint
        account.refresh_token_key_version = key_version
        account.status = AmazonAccountStatus.ACTIVE

    def _rollback_oauth_transaction(self) -> None:
        self._db.rollback()

    def connect_account_from_oauth(
        self,
        *,
        user_id: uuid.UUID,
        region: str,
        selling_partner_id: str,
        plaintext_refresh_token: str,
    ) -> AmazonAccountSummary:
        try:
            return self._connect_account_from_oauth(
                user_id=user_id,
                region=region,
                selling_partner_id=selling_partner_id,
                plaintext_refresh_token=plaintext_refresh_token,
            )
        except AmazonError:
            self._rollback_oauth_transaction()
            raise
        except IntegrityError as exc:
            self._rollback_oauth_transaction()
            raise self._map_oauth_integrity_error(exc) from None
        except Exception:
            self._rollback_oauth_transaction()
            logger.warning(
                "OAuth account persistence failure operation=oauth_connect category=unexpected",
            )
            raise amazon_oauth_account_persist_failed_error() from None

    def _connect_account_from_oauth(
        self,
        *,
        user_id: uuid.UUID,
        region: str,
        selling_partner_id: str,
        plaintext_refresh_token: str,
    ) -> AmazonAccountSummary:
        normalized_region = _validate_oauth_region(region)
        normalized_seller_id = _validate_oauth_selling_partner_id(selling_partner_id)
        validated_token = _validate_oauth_plaintext_refresh_token(plaintext_refresh_token)
        self._ensure_oauth_user_exists(user_id)

        existing = (
            self._db.query(AmazonAccount)
            .filter(AmazonAccount.selling_partner_id == normalized_seller_id)
            .with_for_update()
            .one_or_none()
        )
        if existing is None:
            account_id = uuid.uuid4()
            fingerprint = self._encryption.fingerprint_refresh_token(validated_token)
            ciphertext, key_version = self._encryption.encrypt_refresh_token(
                validated_token,
                user_id=user_id,
                account_id=account_id,
            )
            account = AmazonAccount(
                id=account_id,
                user_id=user_id,
                region=normalized_region,
                endpoint_mode=OAUTH_ACCOUNT_ENDPOINT_MODE,
                selling_partner_id=normalized_seller_id,
                status=AmazonAccountStatus.ACTIVE,
                refresh_token_ciphertext=ciphertext,
                refresh_token_key_version=key_version,
                refresh_token_fingerprint=fingerprint,
            )
            self._db.add(account)
            return self._commit_oauth_account(account, operation="oauth_connect_create")

        if existing.user_id != user_id:
            raise amazon_oauth_seller_already_linked_error()
        if (
            existing.region != normalized_region
            or existing.endpoint_mode != OAUTH_ACCOUNT_ENDPOINT_MODE
        ):
            raise amazon_oauth_seller_already_linked_error()

        self._ensure_no_active_sync_lease(existing)
        self._apply_oauth_refresh_token(existing, plaintext_refresh_token=validated_token)
        self._db.add(existing)
        return self._commit_oauth_account(existing, operation="oauth_connect_rotate")

    def reauthorize_account_from_oauth(
        self,
        *,
        user_id: uuid.UUID,
        account_id: uuid.UUID,
        selling_partner_id: str,
        plaintext_refresh_token: str,
    ) -> AmazonAccountSummary:
        try:
            return self._reauthorize_account_from_oauth(
                user_id=user_id,
                account_id=account_id,
                selling_partner_id=selling_partner_id,
                plaintext_refresh_token=plaintext_refresh_token,
            )
        except AmazonError:
            self._rollback_oauth_transaction()
            raise
        except IntegrityError as exc:
            self._rollback_oauth_transaction()
            raise self._map_oauth_integrity_error(exc) from None
        except Exception:
            self._rollback_oauth_transaction()
            logger.warning(
                "OAuth account persistence failure operation=oauth_reauthorize category=unexpected",
            )
            raise amazon_oauth_account_persist_failed_error() from None

    def _reauthorize_account_from_oauth(
        self,
        *,
        user_id: uuid.UUID,
        account_id: uuid.UUID,
        selling_partner_id: str,
        plaintext_refresh_token: str,
    ) -> AmazonAccountSummary:
        normalized_seller_id = _validate_oauth_selling_partner_id(selling_partner_id)
        validated_token = _validate_oauth_plaintext_refresh_token(plaintext_refresh_token)

        account = (
            self._db.query(AmazonAccount)
            .filter(
                AmazonAccount.id == account_id,
                AmazonAccount.user_id == user_id,
            )
            .with_for_update()
            .one_or_none()
        )
        if account is None:
            raise amazon_account_not_found_error()
        if account.endpoint_mode != OAUTH_ACCOUNT_ENDPOINT_MODE:
            raise amazon_config_invalid_error("Amazon account endpoint mode is invalid")
        if (
            account.selling_partner_id is None
            or account.selling_partner_id != normalized_seller_id
        ):
            raise amazon_oauth_seller_mismatch_error()

        self._ensure_no_active_sync_lease(account)
        self._apply_oauth_refresh_token(account, plaintext_refresh_token=validated_token)
        self._db.add(account)
        return self._commit_oauth_account(account, operation="oauth_reauthorize")

    def get_account_model_for_user(
        self,
        *,
        user_id: uuid.UUID,
        account_id: uuid.UUID,
    ) -> AmazonAccount:
        account = self._get_account_row_for_user(user_id=user_id, account_id=account_id)
        if account is None:
            raise amazon_account_not_found_error()
        return account

    def disable_account(
        self,
        *,
        user_id: uuid.UUID,
        account_id: uuid.UUID,
    ) -> AmazonAccountSummary:
        account = (
            self._db.query(AmazonAccount)
            .filter(
                AmazonAccount.id == account_id,
                AmazonAccount.user_id == user_id,
            )
            .with_for_update()
            .one_or_none()
        )
        if account is None:
            raise amazon_account_not_found_error()

        if account.status == AmazonAccountStatus.DISABLED:
            return _to_summary(account)

        now = datetime.now(UTC)
        processing_logs = (
            self._db.query(AmazonSyncLog)
            .filter(
                AmazonSyncLog.amazon_account_id == account_id,
                AmazonSyncLog.status == AmazonSyncStatus.PROCESSING,
            )
            .with_for_update()
            .all()
        )
        for sync_log in processing_logs:
            AmazonSyncLogService.finalize_failed(
                self._db,
                account_id=account_id,
                sync_log_id=sync_log.id,
                error_code=AMAZON_ACCOUNT_DISABLED,
                finished_at=now,
            )

        account.status = AmazonAccountStatus.DISABLED
        account.sync_lease_id = None
        account.sync_lease_expires_at = None
        self._db.add(account)
        self._db.commit()
        self._db.refresh(account)
        return _to_summary(account)

    def disconnect_account(
        self,
        *,
        user_id: uuid.UUID,
        account_id: uuid.UUID,
    ) -> AmazonAccountDisconnectResult:
        account = (
            self._db.query(AmazonAccount)
            .filter(
                AmazonAccount.id == account_id,
                AmazonAccount.user_id == user_id,
            )
            .with_for_update()
            .one_or_none()
        )
        if account is None:
            return AmazonAccountDisconnectResult(
                account_id=account_id,
                already_disconnected=True,
                disconnected_at=None,
            )

        now = datetime.now(UTC)
        processing_logs = (
            self._db.query(AmazonSyncLog)
            .filter(
                AmazonSyncLog.amazon_account_id == account_id,
                AmazonSyncLog.status == AmazonSyncStatus.PROCESSING,
            )
            .with_for_update()
            .all()
        )
        for sync_log in processing_logs:
            AmazonSyncLogService.finalize_failed(
                self._db,
                account_id=account_id,
                sync_log_id=sync_log.id,
                error_code=AMAZON_ACCOUNT_DISABLED,
                finished_at=now,
            )

        listing_ids = [
            row[0]
            for row in self._db.query(AmazonListing.id)
            .filter(AmazonListing.amazon_account_id == account_id)
            .all()
        ]
        if listing_ids:
            snapshot_ids = [
                row[0]
                for row in self._db.query(ListingAuditSnapshot.id)
                .filter(ListingAuditSnapshot.amazon_listing_id.in_(listing_ids))
                .all()
            ]
            if snapshot_ids:
                snapshot_id_values = {str(snapshot_id) for snapshot_id in snapshot_ids}
                linked_generations = (
                    self._db.query(Generation)
                    .filter(
                        Generation.user_id == user_id,
                        Generation.type == LISTING_AUDIT_GENERATION_TYPE,
                    )
                    .all()
                )
                for generation in linked_generations:
                    payload = generation.input if isinstance(generation.input, dict) else {}
                    if payload.get("snapshot_id") in snapshot_id_values:
                        self._db.delete(generation)
                (
                    self._db.query(ListingAuditSnapshot)
                    .filter(ListingAuditSnapshot.id.in_(snapshot_ids))
                    .delete(synchronize_session=False)
                )

        region = account.region
        self._db.delete(account)
        self._db.commit()
        logger.info(
            "amazon_account_disconnected user_id=%s account_id=%s region=%s",
            user_id,
            account_id,
            region,
        )
        return AmazonAccountDisconnectResult(
            account_id=account_id,
            already_disconnected=False,
            disconnected_at=now,
        )
