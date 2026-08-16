"""Shared fixtures for Amazon A4.2 product sync service tests."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

import httpx

from app.integrations.amazon.client import SpApiClient
from app.integrations.amazon.config import AmazonEndpointMode, AmazonSettings
from app.integrations.amazon.listings_items import ListingsItemsClient
from app.integrations.amazon.lwa import CachingRefreshTokenProvider, LwaTokenClient
from app.integrations.amazon.token_cache import InMemoryTokenCache
from app.integrations.amazon.token_encryption import TokenEncryptionService
from app.models.amazon_account import AmazonAccount, AmazonAccountStatus
from app.models.amazon_marketplace_participation import AmazonMarketplaceParticipation
from app.services.amazon_product_sync_service import AmazonProductSyncService
from tests.fixtures.amazon_a32 import (
    FAKE_A32_REFRESH_TOKEN,
    OTHER_FAKE_A32_REFRESH_TOKEN,
    create_committed_account,
)
from tests.integrations.amazon.conftest import (
    TEST_CLIENT_ID,
    TEST_CLIENT_SECRET,
    lwa_success_handler,
    make_transport,
)
from tests.integrations.amazon.test_listings_items import (
    CANARY,
    FAKE_MARKETPLACE_ID,
    FAKE_PAGE_TOKEN,
    FAKE_SELLER_ID,
    _wire_item,
    _wire_page,
    _wire_summary,
)

FAKE_A42_REFRESH_TOKEN = FAKE_A32_REFRESH_TOKEN
OTHER_FAKE_A42_REFRESH_TOKEN = OTHER_FAKE_A32_REFRESH_TOKEN
DEFAULT_MARKETPLACE_ID = FAKE_MARKETPLACE_ID
DEFAULT_SELLER_ID = FAKE_SELLER_ID
SENSITIVE_MARKERS = (FAKE_A42_REFRESH_TOKEN, FAKE_PAGE_TOKEN, CANARY)


def wire_listings_page(*items: dict[str, Any], next_token: str | None = None) -> dict[str, Any]:
    return _wire_page(*items, next_token=next_token)


def wire_listings_item(
    *,
    sku: str = "SKU-001",
    marketplace_id: str = DEFAULT_MARKETPLACE_ID,
    asin: str = "B012345678",
    product_type: str = "PRODUCT",
    status: list[str] | None = None,
) -> dict[str, Any]:
    return _wire_item(
        sku=sku,
        summaries=[
            _wire_summary(
                marketplace_id=marketplace_id,
                asin=asin,
                product_type=product_type,
                status=status,
            )
        ],
    )


def build_listings_client_factory(
    *,
    refresh_token: str,
    sp_api_handler: Callable[[httpx.Request], httpx.Response],
    amazon_settings: AmazonSettings | None = None,
    lwa_handler: Callable[[httpx.Request], httpx.Response] | None = None,
) -> Callable[[str], ListingsItemsClient]:
    settings = amazon_settings or AmazonSettings(
        enabled=True,
        lwa_client_id=TEST_CLIENT_ID,
        lwa_client_secret=TEST_CLIENT_SECRET,
        lwa_token_url="https://mock.lwa.local/auth/o2/token",
        sp_api_region="na",
        endpoint_mode=AmazonEndpointMode.MOCK,
        user_agent="SellerAI-Copilot-Test/1.0.0 (Language=Python)",
        environment="development",
    )

    def factory(plaintext_refresh_token: str) -> ListingsItemsClient:
        assert plaintext_refresh_token == refresh_token

        async def resolve(_account_key: str) -> str:
            return plaintext_refresh_token

        def combined_handler(request: httpx.Request) -> httpx.Response:
            if "mock.lwa.local" in str(request.url):
                if lwa_handler is not None:
                    return lwa_handler(request)
                return lwa_success_handler(refresh_token=plaintext_refresh_token)(request)
            return sp_api_handler(request)

        transport = make_transport(combined_handler)
        lwa_client = LwaTokenClient(settings=settings, transport=transport)
        provider = CachingRefreshTokenProvider(
            client=lwa_client,
            cache=InMemoryTokenCache(clock=lambda: 1000.0),
            refresh_token_resolver=resolve,
        )
        sp_client = SpApiClient(
            settings=settings,
            transport=transport,
            token_provider=provider,
            amz_date_factory=lambda: "20260101T120000Z",
        )
        return ListingsItemsClient(sp_client)

    return factory


def seed_participation(
    session_factory,
    *,
    account_id: uuid.UUID,
    marketplace_id: str = DEFAULT_MARKETPLACE_ID,
    participating: bool = True,
    suspended_listings: bool = False,
    is_active: bool = True,
) -> None:
    db = session_factory()
    try:
        db.add(
            AmazonMarketplaceParticipation(
                amazon_account_id=account_id,
                marketplace_id=marketplace_id,
                marketplace_name="Amazon.com",
                country_code="US",
                participating=participating,
                suspended_listings=suspended_listings,
                is_active=is_active,
            )
        )
        db.commit()
    finally:
        db.close()


def create_sync_ready_account(
    session_factory,
    token_encryption_service: TokenEncryptionService,
    *,
    token: str = FAKE_A42_REFRESH_TOKEN,
    selling_partner_id: str = DEFAULT_SELLER_ID,
    marketplace_id: str = DEFAULT_MARKETPLACE_ID,
    participating: bool = True,
    suspended_listings: bool = False,
    participation_active: bool = True,
    email: str | None = None,
):
    user, summary = create_committed_account(
        session_factory,
        token_encryption_service,
        token=token,
        email=email,
    )
    db = session_factory()
    try:
        account = db.get(AmazonAccount, summary.id)
        assert account is not None
        account.selling_partner_id = selling_partner_id
        account.status = AmazonAccountStatus.ACTIVE
        db.add(account)
        db.add(
            AmazonMarketplaceParticipation(
                amazon_account_id=summary.id,
                marketplace_id=marketplace_id,
                marketplace_name="Amazon.com",
                country_code="US",
                participating=participating,
                suspended_listings=suspended_listings,
                is_active=participation_active,
            )
        )
        db.commit()
    finally:
        db.close()
    return user, summary


def make_product_sync_service(
    token_encryption_service: TokenEncryptionService,
    session_factory,
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    refresh_token: str = FAKE_A42_REFRESH_TOKEN,
    clock=None,
) -> AmazonProductSyncService:
    return AmazonProductSyncService(
        session_factory=session_factory,
        encryption_service=token_encryption_service,
        listings_client_factory=build_listings_client_factory(
            refresh_token=refresh_token,
            sp_api_handler=handler,
        ),
        min_lease_seconds=1,
        max_lease_seconds=3600,
        clock=clock,
    )


def single_page_success_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json=wire_listings_page(wire_listings_item()),
        headers={"x-amzn-requestid": "req-success-123"},
    )
