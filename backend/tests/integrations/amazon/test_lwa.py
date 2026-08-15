from __future__ import annotations

import httpx
import pytest

from app.integrations.amazon.exceptions import (
    AMAZON_LWA_RATE_LIMITED,
    AMAZON_LWA_TOKEN_INVALID,
    AMAZON_LWA_UNAVAILABLE,
    AMAZON_RESPONSE_INVALID,
    AmazonError,
)
from app.integrations.amazon.lwa import LwaTokenClient
from tests.integrations.amazon.conftest import (
    TEST_REFRESH_TOKEN,
    lwa_success_handler,
    make_transport,
)


@pytest.mark.asyncio
async def test_exchange_refresh_token_success(amazon_settings):
    transport = make_transport(lwa_success_handler())
    client = LwaTokenClient(settings=amazon_settings, transport=transport)
    token = await client.exchange_refresh_token(TEST_REFRESH_TOKEN)
    assert token.access_token == "TEST_ACCESS_TOKEN_PLACEHOLDER"
    assert token.token_type == "bearer"
    assert token.expires_in == 3600


@pytest.mark.asyncio
async def test_exchange_client_credentials_sends_scope(amazon_settings):
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.content.decode()
        return httpx.Response(
            200,
            json={"access_token": "grantless-token", "token_type": "bearer", "expires_in": 3600},
        )

    client = LwaTokenClient(settings=amazon_settings, transport=make_transport(handler))
    token = await client.exchange_client_credentials("sellingpartnerapi::notifications")
    assert token.access_token == "grantless-token"
    assert "grant_type=client_credentials" in captured["body"]
    assert "scope=sellingpartnerapi%3A%3Anotifications" in captured["body"]


@pytest.mark.asyncio
async def test_exchange_refresh_token_invalid_grant(amazon_settings):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "invalid_grant"})

    client = LwaTokenClient(settings=amazon_settings, transport=make_transport(handler))
    with pytest.raises(AmazonError) as exc_info:
        await client.exchange_refresh_token(TEST_REFRESH_TOKEN)
    assert exc_info.value.error_code == AMAZON_LWA_TOKEN_INVALID


@pytest.mark.asyncio
async def test_exchange_refresh_token_rate_limited(amazon_settings):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "rate_limited"})

    client = LwaTokenClient(settings=amazon_settings, transport=make_transport(handler))
    with pytest.raises(AmazonError) as exc_info:
        await client.exchange_refresh_token(TEST_REFRESH_TOKEN)
    assert exc_info.value.error_code == AMAZON_LWA_RATE_LIMITED


@pytest.mark.asyncio
async def test_exchange_refresh_token_server_error(amazon_settings):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "server"})

    client = LwaTokenClient(settings=amazon_settings, transport=make_transport(handler))
    with pytest.raises(AmazonError) as exc_info:
        await client.exchange_refresh_token(TEST_REFRESH_TOKEN)
    assert exc_info.value.error_code == AMAZON_LWA_UNAVAILABLE


@pytest.mark.asyncio
async def test_exchange_refresh_token_timeout(amazon_settings):
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout")

    client = LwaTokenClient(settings=amazon_settings, transport=make_transport(handler))
    with pytest.raises(AmazonError) as exc_info:
        await client.exchange_refresh_token(TEST_REFRESH_TOKEN)
    assert exc_info.value.error_code == AMAZON_LWA_UNAVAILABLE


@pytest.mark.asyncio
async def test_exchange_refresh_token_non_json(amazon_settings):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not-json")

    client = LwaTokenClient(settings=amazon_settings, transport=make_transport(handler))
    with pytest.raises(AmazonError) as exc_info:
        await client.exchange_refresh_token(TEST_REFRESH_TOKEN)
    assert exc_info.value.error_code == AMAZON_RESPONSE_INVALID


@pytest.mark.asyncio
async def test_exchange_refresh_token_missing_fields(amazon_settings):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"token_type": "bearer"})

    client = LwaTokenClient(settings=amazon_settings, transport=make_transport(handler))
    with pytest.raises(AmazonError) as exc_info:
        await client.exchange_refresh_token(TEST_REFRESH_TOKEN)
    assert exc_info.value.error_code == AMAZON_RESPONSE_INVALID


@pytest.mark.asyncio
async def test_lwa_errors_do_not_include_refresh_token(amazon_settings, caplog):
    secret = TEST_REFRESH_TOKEN

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text=f'{{"error":"invalid","refresh_token":"{secret}"}}')

    client = LwaTokenClient(settings=amazon_settings, transport=make_transport(handler))
    with caplog.at_level("WARNING"):
        with pytest.raises(AmazonError):
            await client.exchange_refresh_token(secret)

    combined = " ".join(record.message for record in caplog.records)
    assert secret not in combined
