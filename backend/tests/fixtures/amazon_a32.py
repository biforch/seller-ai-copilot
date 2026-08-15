"""Shared fixtures for Amazon A3.2 service tests."""

from __future__ import annotations

import base64
import secrets
import uuid
from dataclasses import dataclass

import httpx
import pytest
from sqlalchemy.orm import sessionmaker

from app.integrations.amazon.config import AmazonEndpointMode, AmazonSettings
from app.integrations.amazon.lwa import CachingRefreshTokenProvider, LwaTokenClient
from app.integrations.amazon.sellers import SellersClient
from app.integrations.amazon.token_cache import InMemoryTokenCache
from app.integrations.amazon.token_encryption import TokenEncryptionConfig, TokenEncryptionService
from app.services.amazon_marketplace_refresh_service import AmazonMarketplaceRefreshService
from tests.integrations.amazon.conftest import (
    TEST_CLIENT_ID,
    TEST_CLIENT_SECRET,
    lwa_success_handler,
    make_transport,
)

FAKE_A32_REFRESH_TOKEN = "fake-refresh-token-a3-2-never-log"
OTHER_FAKE_A32_REFRESH_TOKEN = "other-fake-refresh-token-a3-2-never-log"


@dataclass
class EncryptionSettingsStub:
    AMAZON_TOKEN_ACTIVE_KEY_VERSION: int
    AMAZON_TOKEN_KEY_V1: str
    AMAZON_TOKEN_KEY_V0: str
    AMAZON_TOKEN_FINGERPRINT_PEPPER: str


def _b64_key(raw: bytes | None = None) -> str:
    payload = raw or secrets.token_bytes(32)
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


@pytest.fixture
def encryption_keys() -> tuple[bytes, bytes]:
    return secrets.token_bytes(32), secrets.token_bytes(32)


@pytest.fixture
def fingerprint_pepper_bytes() -> bytes:
    return secrets.token_bytes(32)


@pytest.fixture
def test_encryption_settings(
    encryption_keys: tuple[bytes, bytes],
    fingerprint_pepper_bytes: bytes,
) -> EncryptionSettingsStub:
    key_v1, key_v0 = encryption_keys
    return EncryptionSettingsStub(
        AMAZON_TOKEN_ACTIVE_KEY_VERSION=1,
        AMAZON_TOKEN_KEY_V1=_b64_key(key_v1),
        AMAZON_TOKEN_KEY_V0=_b64_key(key_v0),
        AMAZON_TOKEN_FINGERPRINT_PEPPER=_b64_key(fingerprint_pepper_bytes),
    )


@pytest.fixture
def token_encryption_service(
    encryption_keys: tuple[bytes, bytes],
    fingerprint_pepper_bytes: bytes,
) -> TokenEncryptionService:
    key_v1, _key_v0 = encryption_keys
    config = TokenEncryptionConfig(
        active_key_version=1,
        keys={1: key_v1},
        fingerprint_pepper=fingerprint_pepper_bytes,
    )
    return TokenEncryptionService(config)


def wire_item(
    *,
    marketplace_id: str = "ATVPDKIKX0DER",
    country_code: str = "US",
    name: str = "Amazon.com",
    participating: bool = True,
    suspended_listings: bool = False,
) -> dict:
    return {
        "marketplace": {
            "id": marketplace_id,
            "countryCode": country_code,
            "name": name,
            "defaultCurrencyCode": "USD",
            "defaultLanguageCode": "en_US",
            "domainName": "www.amazon.com",
        },
        "participation": {
            "isParticipating": participating,
            "hasSuspendedListings": suspended_listings,
        },
    }


def wire_response(*items: dict) -> dict:
    return {"payload": list(items)}


def build_sellers_client_factory(
    *,
    refresh_token: str,
    sp_api_handler,
    amazon_settings: AmazonSettings | None = None,
):
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

    def factory(plaintext_refresh_token: str) -> SellersClient:
        assert plaintext_refresh_token == refresh_token

        async def resolve(_account_key: str) -> str:
            return plaintext_refresh_token

        def combined_handler(request: httpx.Request) -> httpx.Response:
            if "mock.lwa.local" in str(request.url):
                return lwa_success_handler(refresh_token=plaintext_refresh_token)(request)
            return sp_api_handler(request)

        transport = make_transport(combined_handler)
        lwa_client = LwaTokenClient(settings=settings, transport=transport)
        provider = CachingRefreshTokenProvider(
            client=lwa_client,
            cache=InMemoryTokenCache(clock=lambda: 1000.0),
            refresh_token_resolver=resolve,
        )
        from app.integrations.amazon.client import SpApiClient

        sp_client = SpApiClient(
            settings=settings,
            transport=transport,
            token_provider=provider,
            amz_date_factory=lambda: "20260101T120000Z",
        )
        return SellersClient(sp_client)

    return factory


@pytest.fixture
def a32_session_factory(engine):
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


def create_committed_account(session_factory, token_encryption_service, *, token: str, email: str | None = None):
    from app.core.security import get_password_hash
    from app.models.user import User
    from app.services.amazon_account_service import AmazonAccountService

    db = session_factory()
    try:
        user = User(
            email=email or f"amazon-a32-{uuid.uuid4()}@example.com",
            password_hash=get_password_hash("Password1"),
            plan="free",
            monthly_tokens=100_000,
            used_tokens=0,
        )
        db.add(user)
        db.flush()
        service = AmazonAccountService(db, token_encryption_service)
        summary = service.create_account(
            user_id=user.id,
            region="na",
            endpoint_mode="sandbox",
            plaintext_refresh_token=token,
        )
        db.refresh(user)
        db.expunge(user)
        return user, summary
    finally:
        db.close()


@pytest.fixture
def refresh_service(token_encryption_service, a32_session_factory) -> AmazonMarketplaceRefreshService:
    return AmazonMarketplaceRefreshService(
        session_factory=a32_session_factory,
        encryption_service=token_encryption_service,
        sellers_client_factory=build_sellers_client_factory(
            refresh_token=FAKE_A32_REFRESH_TOKEN,
            sp_api_handler=lambda request: httpx.Response(
                200,
                json=wire_response(wire_item()),
                headers={"x-amzn-requestid": "req-success-123"},
            ),
        ),
        min_lease_seconds=1,
        max_lease_seconds=3600,
    )


def create_account_via_service(db, user_factory, token_encryption_service, *, token: str):
    from app.services.amazon_account_service import AmazonAccountService

    user = user_factory(f"amazon-a32-{uuid.uuid4()}@example.com")
    service = AmazonAccountService(db, token_encryption_service)
    summary = service.create_account(
        user_id=user.id,
        region="na",
        endpoint_mode="sandbox",
        plaintext_refresh_token=token,
    )
    return user, summary
