"""Amazon OAuth start and callback orchestration."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.integrations.amazon.config import OAUTH_ACCOUNT_ENDPOINT_MODE, AmazonSettings
from app.integrations.amazon.exceptions import (
    AmazonError,
    amazon_account_not_found_error,
    amazon_config_invalid_error,
    amazon_oauth_account_persist_failed_error,
    amazon_oauth_disabled_error,
    amazon_oauth_intent_invalid_error,
    amazon_oauth_state_invalid_error,
)
from app.integrations.amazon.lwa import LwaTokenClient
from app.integrations.amazon.oauth_urls import build_seller_central_authorization_url
from app.integrations.amazon.token_encryption import TokenEncryptionService
from app.models.amazon_account import AmazonAccount
from app.models.amazon_oauth_state import OAuthStateIntent
from app.services.amazon_account_service import (
    AmazonAccountService,
    AmazonAccountSummary,
    _validate_oauth_selling_partner_id,
)
from app.services.amazon_oauth_state_store import AmazonOAuthStateStore

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], Session]
StateStoreFactory = Callable[[Session], AmazonOAuthStateStore]
AccountServiceFactory = Callable[[Session], AmazonAccountService]
LwaClientFactory = Callable[[], LwaTokenClient]
Clock = Callable[[], datetime]

AmazonOAuthCallbackResult = AmazonAccountSummary


@dataclass(frozen=True)
class AmazonOAuthStartResult:
    authorization_url: str
    marketplace_code: str
    region: str
    expires_at: datetime

    def __repr__(self) -> str:
        return (
            "AmazonOAuthStartResult("
            f"marketplace_code={self.marketplace_code!r}, "
            f"region={self.region!r}, "
            f"expires_at={self.expires_at!r})"
        )


class AmazonOAuthService:
    def __init__(
        self,
        session_factory: SessionFactory,
        *,
        settings: AmazonSettings,
        encryption_service: TokenEncryptionService,
        lwa_client_factory: LwaClientFactory,
        state_store_factory: StateStoreFactory | None = None,
        account_service_factory: AccountServiceFactory | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._settings = settings
        self._encryption_service = encryption_service
        self._clock = clock
        self._lwa_client_factory = lwa_client_factory
        self._state_store_factory = state_store_factory or self._default_state_store_factory
        self._account_service_factory = account_service_factory

    def _default_state_store_factory(self, db: Session) -> AmazonOAuthStateStore:
        return AmazonOAuthStateStore(
            db,
            ttl_seconds=self._settings.oauth_state_ttl_seconds,
            clock=self._clock,
        )

    def _ensure_oauth_enabled(self) -> None:
        if not self._settings.oauth_enabled:
            raise amazon_oauth_disabled_error()

    def _consent_version(self) -> str | None:
        normalized = self._settings.oauth_consent_version.strip()
        return normalized or None

    def _preflight_callback_dependencies(self) -> None:
        if self._lwa_client_factory is None:
            raise amazon_config_invalid_error("Amazon OAuth LWA client is not configured")
        if self._account_service_factory is None:
            raise amazon_config_invalid_error("Amazon OAuth account service is not configured")
        if not self._settings.lwa_token_url.strip():
            raise amazon_config_invalid_error("Amazon OAuth LWA token URL is not configured")
        if not self._settings.oauth_redirect_uri.strip():
            raise amazon_config_invalid_error("Amazon OAuth redirect URI is not configured")
        if not self._settings.lwa_client_id.strip():
            raise amazon_config_invalid_error("Amazon OAuth LWA client id is not configured")
        if not self._settings.lwa_client_secret.strip():
            raise amazon_config_invalid_error("Amazon OAuth LWA client secret is not configured")

        session = self._session_factory()
        try:
            return
        finally:
            session.close()

    def _validate_reauthorize_target_for_start(
        self,
        db: Session,
        *,
        user_id: uuid.UUID,
        target_account_id: uuid.UUID,
    ) -> None:
        account = (
            db.query(AmazonAccount)
            .filter(
                AmazonAccount.id == target_account_id,
                AmazonAccount.user_id == user_id,
            )
            .one_or_none()
        )
        if account is None:
            raise amazon_account_not_found_error()
        if account.endpoint_mode != OAUTH_ACCOUNT_ENDPOINT_MODE:
            raise amazon_config_invalid_error("Amazon account endpoint mode is invalid")

    def start_authorization(
        self,
        *,
        user_id: uuid.UUID,
        marketplace_code: str,
        intent: str,
        target_account_id: uuid.UUID | None = None,
    ) -> AmazonOAuthStartResult:
        self._ensure_oauth_enabled()
        db = self._session_factory()
        try:
            if intent.strip().lower() == OAuthStateIntent.REAUTHORIZE:
                if target_account_id is None:
                    raise amazon_oauth_intent_invalid_error()
                self._validate_reauthorize_target_for_start(
                    db,
                    user_id=user_id,
                    target_account_id=target_account_id,
                )

            store = self._state_store_factory(db)
            issue = store.create_state(
                user_id=user_id,
                marketplace_code=marketplace_code,
                intent=intent,
                target_account_id=target_account_id,
            )
            target = build_seller_central_authorization_url(
                marketplace_code=issue.marketplace_code,
                application_id=self._settings.application_id,
                state=issue.raw_state_token,
                consent_version=self._consent_version(),
            )
            db.commit()
            return AmazonOAuthStartResult(
                authorization_url=target.authorization_url,
                marketplace_code=issue.marketplace_code,
                region=issue.region,
                expires_at=issue.expires_at,
            )
        except AmazonError:
            db.rollback()
            raise
        except Exception:
            db.rollback()
            logger.warning(
                "OAuth start failure operation=oauth_start category=unexpected user_id=%s",
                user_id,
            )
            raise amazon_oauth_account_persist_failed_error() from None
        finally:
            db.close()

    async def complete_authorization(
        self,
        *,
        state: str,
        spapi_oauth_code: str,
        selling_partner_id: str,
    ) -> AmazonOAuthCallbackResult:
        self._ensure_oauth_enabled()
        normalized_seller_id = _validate_oauth_selling_partner_id(selling_partner_id)
        self._preflight_callback_dependencies()

        db = self._session_factory()
        consumed = None
        try:
            store = self._state_store_factory(db)
            consumed = store.consume_state(state)
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                raise amazon_oauth_state_invalid_error() from None
            except Exception:
                db.rollback()
                raise amazon_oauth_state_invalid_error() from None
        except AmazonError:
            db.rollback()
            raise
        finally:
            db.close()

        plaintext_refresh_token: str | None = None
        try:
            lwa_client = self._lwa_client_factory()
            exchange = await lwa_client.exchange_authorization_code(spapi_oauth_code)
            plaintext_refresh_token = exchange.refresh_token

            account_db = self._session_factory()
            try:
                account_factory = self._account_service_factory
                assert account_factory is not None
                account_service = account_factory(account_db)
                if consumed.intent == OAuthStateIntent.CONNECT:
                    summary = account_service.connect_account_from_oauth(
                        user_id=consumed.user_id,
                        region=consumed.region,
                        selling_partner_id=normalized_seller_id,
                        plaintext_refresh_token=plaintext_refresh_token,
                    )
                else:
                    if consumed.target_account_id is None:
                        raise amazon_oauth_state_invalid_error()
                    summary = account_service.reauthorize_account_from_oauth(
                        user_id=consumed.user_id,
                        account_id=consumed.target_account_id,
                        selling_partner_id=normalized_seller_id,
                        plaintext_refresh_token=plaintext_refresh_token,
                    )
                return summary
            finally:
                account_db.close()
        finally:
            plaintext_refresh_token = None
