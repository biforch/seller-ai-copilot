"""FastAPI dependencies for Amazon marketplace reads and refreshes."""

from __future__ import annotations

import uuid
from collections.abc import Callable

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.config import settings
from app.database.session import SessionLocal, get_db
from app.integrations.amazon.client import SpApiClient
from app.integrations.amazon.config import AmazonEndpointMode
from app.integrations.amazon.lwa import CachingRefreshTokenProvider, LwaTokenClient
from app.integrations.amazon.sellers import SellersClient
from app.integrations.amazon.token_encryption_loader import build_token_encryption_service
from app.integrations.amazon.transport import HttpxTransport
from app.services.amazon_account_read_service import AmazonAccountReadService, AmazonAccountSummary
from app.services.amazon_marketplace_read_service import AmazonMarketplaceReadService
from app.services.amazon_marketplace_refresh_service import AmazonMarketplaceRefreshService

MarketplaceRefreshServiceFactory = Callable[[str, str], AmazonMarketplaceRefreshService]
AccountRuntimeResolver = Callable[[uuid.UUID, uuid.UUID], AmazonAccountSummary]


def get_amazon_marketplace_read_service(
    db: Session = Depends(get_db),
) -> AmazonMarketplaceReadService:
    return AmazonMarketplaceReadService(db)


def build_amazon_account_runtime_resolver(
    db: Session,
) -> AccountRuntimeResolver:
    def resolve(user_id: uuid.UUID, account_id: uuid.UUID) -> AmazonAccountSummary:
        try:
            return AmazonAccountReadService(db).get_account_for_user(
                user_id=user_id,
                account_id=account_id,
            )
        finally:
            db.rollback()

    return resolve


def get_amazon_account_runtime_resolver(
    db: Session = Depends(get_db),
) -> AccountRuntimeResolver:
    return build_amazon_account_runtime_resolver(db)


def build_amazon_marketplace_refresh_service(
    *,
    region: str,
    endpoint_mode: str,
) -> AmazonMarketplaceRefreshService:
    amazon_settings = settings.amazon_settings.model_copy(
        update={
            "sp_api_region": region,
            "endpoint_mode": AmazonEndpointMode(endpoint_mode),
        }
    )
    encryption_service = build_token_encryption_service(settings)

    def sellers_client_factory(plaintext_refresh_token: str) -> SellersClient:
        transport = HttpxTransport()
        lwa_client = LwaTokenClient(settings=amazon_settings, transport=transport)

        async def resolve_refresh_token(_account_key: str) -> str:
            return plaintext_refresh_token

        token_provider = CachingRefreshTokenProvider(
            client=lwa_client,
            refresh_token_resolver=resolve_refresh_token,
        )
        sp_client = SpApiClient(
            settings=amazon_settings,
            transport=transport,
            token_provider=token_provider,
        )
        return SellersClient(sp_client)

    return AmazonMarketplaceRefreshService(
        session_factory=SessionLocal,
        encryption_service=encryption_service,
        sellers_client_factory=sellers_client_factory,
    )


def get_amazon_marketplace_refresh_service_factory() -> MarketplaceRefreshServiceFactory:
    def factory(region: str, endpoint_mode: str) -> AmazonMarketplaceRefreshService:
        return build_amazon_marketplace_refresh_service(
            region=region,
            endpoint_mode=endpoint_mode,
        )

    return factory
