"""Shared fixtures for Amazon integration tests."""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from app.integrations.amazon.config import AmazonEndpointMode, AmazonSettings
from app.integrations.amazon.transport import HttpxTransport

TEST_REFRESH_TOKEN = "TEST_REFRESH_TOKEN_PLACEHOLDER"
TEST_ACCESS_TOKEN = "TEST_ACCESS_TOKEN_PLACEHOLDER"
TEST_CLIENT_ID = "TEST_CLIENT_ID"
TEST_CLIENT_SECRET = "TEST_CLIENT_SECRET"


@pytest.fixture
def amazon_settings() -> AmazonSettings:
    return AmazonSettings(
        enabled=True,
        lwa_client_id=TEST_CLIENT_ID,
        lwa_client_secret=TEST_CLIENT_SECRET,
        lwa_token_url="https://mock.lwa.local/auth/o2/token",
        sp_api_region="na",
        endpoint_mode=AmazonEndpointMode.MOCK,
        user_agent="SellerAI-Copilot-Test/1.0.0 (Language=Python)",
        environment="development",
    )


def lwa_success_handler(
    refresh_token: str = TEST_REFRESH_TOKEN,
) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        body = request.content.decode()
        assert "grant_type=refresh_token" in body
        assert f"refresh_token={refresh_token}" in body
        assert f"client_id={TEST_CLIENT_ID}" in body
        assert f"client_secret={TEST_CLIENT_SECRET}" in body
        return httpx.Response(
            200,
            json={
                "access_token": TEST_ACCESS_TOKEN,
                "token_type": "bearer",
                "expires_in": 3600,
            },
        )

    return handler


def make_transport(handler: Callable[[httpx.Request], httpx.Response]) -> HttpxTransport:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return HttpxTransport(client=client)


@pytest.fixture
def lwa_transport() -> HttpxTransport:
    return make_transport(lwa_success_handler())


@pytest.fixture
async def async_refresh_resolver():
    async def resolve(_account_key: str) -> str:
        return TEST_REFRESH_TOKEN

    return resolve
