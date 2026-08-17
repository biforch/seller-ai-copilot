"""Dependencies for Amazon catalog snapshot reads and enrichment."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.config import settings
from app.database.session import SessionLocal, get_db
from app.integrations.amazon.catalog_items import CatalogItemsClient
from app.integrations.amazon.client import SpApiClient
from app.integrations.amazon.config import AmazonEndpointMode
from app.integrations.amazon.lwa import CachingRefreshTokenProvider, LwaTokenClient
from app.integrations.amazon.token_encryption_loader import build_token_encryption_service
from app.integrations.amazon.transport import HttpxTransport
from app.services.amazon_catalog_enrichment_service import AmazonCatalogEnrichmentService
from app.services.amazon_catalog_read_service import AmazonCatalogReadService

CatalogEnrichmentServiceFactory = Callable[[str, str], AmazonCatalogEnrichmentService]


def get_amazon_catalog_read_service(
    db: Session = Depends(get_db),
) -> AmazonCatalogReadService:
    return AmazonCatalogReadService(db)


def build_amazon_catalog_enrichment_service(
    *, region: str, endpoint_mode: str
) -> AmazonCatalogEnrichmentService:
    amazon_settings = settings.amazon_settings.model_copy(
        update={
            "sp_api_region": region,
            "endpoint_mode": AmazonEndpointMode(endpoint_mode),
        }
    )
    encryption_service = build_token_encryption_service(settings)

    def catalog_client_factory(plaintext_refresh_token: str) -> CatalogItemsClient:
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
        return CatalogItemsClient(sp_client)

    return AmazonCatalogEnrichmentService(
        session_factory=SessionLocal,
        encryption_service=encryption_service,
        catalog_client_factory=catalog_client_factory,
    )


def get_amazon_catalog_enrichment_service_factory() -> CatalogEnrichmentServiceFactory:
    def factory(region: str, endpoint_mode: str) -> AmazonCatalogEnrichmentService:
        return build_amazon_catalog_enrichment_service(
            region=region, endpoint_mode=endpoint_mode
        )

    return factory
