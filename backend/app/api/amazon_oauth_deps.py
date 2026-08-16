"""FastAPI dependencies for Amazon OAuth orchestration."""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy.orm import Session

from app.core.config import settings
from app.database.session import SessionLocal
from app.integrations.amazon.config import AmazonSettings
from app.integrations.amazon.lwa import LwaTokenClient
from app.integrations.amazon.token_encryption import TokenEncryptionService
from app.integrations.amazon.token_encryption_loader import build_token_encryption_service
from app.integrations.amazon.transport import HttpxTransport
from app.services.amazon_account_service import AmazonAccountService
from app.services.amazon_oauth_service import AmazonOAuthService

SessionFactory = Callable[[], Session]
LwaClientFactory = Callable[[], LwaTokenClient]
AccountServiceFactory = Callable[[Session], AmazonAccountService]
AmazonOAuthServiceFactory = Callable[[], AmazonOAuthService]


def build_amazon_oauth_service(
    *,
    session_factory: SessionFactory | None = None,
    amazon_settings: AmazonSettings | None = None,
    encryption_service: TokenEncryptionService | None = None,
    lwa_client_factory: LwaClientFactory | None = None,
    account_service_factory: AccountServiceFactory | None = None,
) -> AmazonOAuthService:
    resolved_settings = amazon_settings or settings.amazon_settings
    resolved_encryption = encryption_service or build_token_encryption_service(settings)
    resolved_session_factory = session_factory or SessionLocal

    def default_lwa_client_factory() -> LwaTokenClient:
        return LwaTokenClient(
            settings=resolved_settings,
            transport=HttpxTransport(),
        )

    def default_account_service_factory(db: Session) -> AmazonAccountService:
        return AmazonAccountService(db, resolved_encryption)

    return AmazonOAuthService(
        resolved_session_factory,
        settings=resolved_settings,
        encryption_service=resolved_encryption,
        lwa_client_factory=lwa_client_factory or default_lwa_client_factory,
        account_service_factory=account_service_factory or default_account_service_factory,
    )


def get_amazon_oauth_service() -> AmazonOAuthService:
    return build_amazon_oauth_service()


def get_amazon_oauth_service_factory() -> AmazonOAuthServiceFactory:
    """Return a lazy factory; heavy OAuth dependencies are created only on invocation."""

    def factory() -> AmazonOAuthService:
        return build_amazon_oauth_service()

    return factory
