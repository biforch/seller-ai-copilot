from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import pytest

from app.integrations.amazon.client import (
    SpApiClient,
    build_sp_api_headers,
    utc_amz_date,
    validate_sp_api_path,
)
from app.integrations.amazon.config import AmazonSettings
from app.integrations.amazon.constants import resolve_marketplace_id, resolve_sp_api_base_url
from app.integrations.amazon.exceptions import (
    AMAZON_CONFIG_INVALID,
    AMAZON_DISABLED,
    AMAZON_RESPONSE_INVALID,
    AMAZON_SP_API_CLIENT_ERROR,
    AMAZON_SP_API_FORBIDDEN,
    AMAZON_SP_API_RATE_LIMITED,
    AMAZON_SP_API_SERVER_ERROR,
    AMAZON_SP_API_UNAUTHORIZED,
    AmazonError,
)
from app.integrations.amazon.lwa import CachingRefreshTokenProvider, LwaTokenClient
from app.integrations.amazon.token_cache import InMemoryTokenCache
from tests.integrations.amazon.conftest import (
    TEST_ACCESS_TOKEN,
    lwa_success_handler,
    make_transport,
)


def test_resolve_sp_api_base_urls_for_regions():
    assert resolve_sp_api_base_url(region="na", endpoint_mode="mock") == "https://mock.sp-api.local"
    assert "eu" in resolve_sp_api_base_url(region="eu", endpoint_mode="sandbox")
    assert "fe" in resolve_sp_api_base_url(region="fe", endpoint_mode="production")


def test_marketplace_mapping_is_not_display_string():
    assert resolve_marketplace_id("US") == "ATVPDKIKX0DER"
    with pytest.raises(KeyError):
        resolve_marketplace_id("Amazon")


def test_utc_amz_date_format():
    fixed = datetime(2026, 1, 15, 12, 30, 45, tzinfo=UTC)
    assert utc_amz_date(now=fixed) == "20260115T123045Z"


def test_build_sp_api_headers_required_fields():
    headers = build_sp_api_headers(
        access_token=TEST_ACCESS_TOKEN,
        user_agent="SellerAI-Test/1.0",
        host="mock.sp-api.local",
        amz_date="20260101T120000Z",
    )
    assert headers["x-amz-access-token"] == TEST_ACCESS_TOKEN
    assert headers["user-agent"] == "SellerAI-Test/1.0"
    assert headers["x-amz-date"] == "20260101T120000Z"
    assert headers["host"] == "mock.sp-api.local"


@pytest.mark.parametrize(
    "bad_path",
    ["orders/v0/orders", "//evil.com/path", "https://evil.com/orders"],
)
def test_validate_sp_api_path_rejects_invalid_paths(bad_path):
    with pytest.raises(AmazonError) as exc_info:
        validate_sp_api_path(bad_path)
    assert exc_info.value.error_code == AMAZON_CONFIG_INVALID


@pytest.mark.asyncio
async def test_sp_api_client_end_to_end_mock(amazon_settings, async_refresh_resolver):
    sp_api_calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "mock.lwa.local" in url:
            return lwa_success_handler()(request)
        sp_api_calls.append(request)
        return httpx.Response(200, json={"payload": {"orders": []}})

    transport = make_transport(handler)
    lwa_client = LwaTokenClient(settings=amazon_settings, transport=transport)
    provider = CachingRefreshTokenProvider(
        client=lwa_client,
        cache=InMemoryTokenCache(clock=lambda: 1000.0),
        refresh_token_resolver=async_refresh_resolver,
    )
    sp_client = SpApiClient(
        settings=amazon_settings,
        transport=transport,
        token_provider=provider,
        amz_date_factory=lambda: "20260101T120000Z",
    )

    response = await sp_client.request(
        "GET",
        "/orders/v0/orders",
        account_key="seller-1",
        params={"MarketplaceIds": resolve_marketplace_id("US")},
    )
    assert response.payload == {"payload": {"orders": []}}
    assert len(sp_api_calls) == 1
    req = sp_api_calls[0]
    assert req.headers["x-amz-access-token"] == TEST_ACCESS_TOKEN
    assert req.headers["x-amz-date"] == "20260101T120000Z"
    assert str(req.url).startswith("https://mock.sp-api.local/orders/v0/orders")


@pytest.mark.asyncio
async def test_sp_api_client_reuses_cached_token(amazon_settings, async_refresh_resolver):
    lwa_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal lwa_calls
        if "mock.lwa.local" in str(request.url):
            lwa_calls += 1
            return lwa_success_handler()(request)
        return httpx.Response(200, json={"ok": True}, headers={"content-type": "application/json"})

    transport = make_transport(handler)
    lwa_client = LwaTokenClient(settings=amazon_settings, transport=transport)
    provider = CachingRefreshTokenProvider(
        client=lwa_client,
        cache=InMemoryTokenCache(clock=lambda: 1000.0),
        refresh_token_resolver=async_refresh_resolver,
    )
    sp_client = SpApiClient(settings=amazon_settings, transport=transport, token_provider=provider)

    await sp_client.request("GET", "/orders/v0/orders", account_key="seller-1")
    await sp_client.request("GET", "/orders/v0/orders", account_key="seller-1")
    assert lwa_calls == 1


@pytest.mark.asyncio
async def test_sp_api_client_disabled(amazon_settings, async_refresh_resolver):
    disabled = AmazonSettings(
        enabled=False,
        lwa_client_id="id",
        lwa_client_secret="secret",
        environment="development",
    )
    provider = CachingRefreshTokenProvider(
        client=LwaTokenClient(settings=disabled, transport=make_transport(lwa_success_handler())),
        refresh_token_resolver=async_refresh_resolver,
    )
    sp_client = SpApiClient(
        settings=disabled,
        transport=make_transport(lwa_success_handler()),
        token_provider=provider,
    )
    with pytest.raises(AmazonError) as exc_info:
        await sp_client.request("GET", "/orders/v0/orders", account_key="seller-1")
    assert exc_info.value.error_code == AMAZON_DISABLED


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "code"),
    [
        (401, AMAZON_SP_API_UNAUTHORIZED),
        (403, AMAZON_SP_API_FORBIDDEN),
        (429, AMAZON_SP_API_RATE_LIMITED),
        (418, AMAZON_SP_API_CLIENT_ERROR),
        (500, AMAZON_SP_API_SERVER_ERROR),
    ],
)
async def test_sp_api_client_maps_status_codes(
    amazon_settings,
    async_refresh_resolver,
    status,
    code,
):
    def handler(request: httpx.Request) -> httpx.Response:
        if "mock.lwa.local" in str(request.url):
            return lwa_success_handler()(request)
        return httpx.Response(
            status,
            json={"errors": [{"code": "Test"}]},
            headers={"x-amzn-requestid": "req-123"},
        )

    transport = make_transport(handler)
    provider = CachingRefreshTokenProvider(
        client=LwaTokenClient(settings=amazon_settings, transport=transport),
        cache=InMemoryTokenCache(clock=lambda: 1000.0),
        refresh_token_resolver=async_refresh_resolver,
    )
    sp_client = SpApiClient(settings=amazon_settings, transport=transport, token_provider=provider)
    with pytest.raises(AmazonError) as exc_info:
        await sp_client.request("GET", "/orders/v0/orders", account_key="seller-1")
    assert exc_info.value.error_code == code
    assert exc_info.value.request_id == "req-123"


@pytest.mark.asyncio
async def test_sp_api_client_invalid_json_response(amazon_settings, async_refresh_resolver):
    def handler(request: httpx.Request) -> httpx.Response:
        if "mock.lwa.local" in str(request.url):
            return lwa_success_handler()(request)
        return httpx.Response(200, content=b"{not-json", headers={"content-type": "application/json"})

    transport = make_transport(handler)
    provider = CachingRefreshTokenProvider(
        client=LwaTokenClient(settings=amazon_settings, transport=transport),
        cache=InMemoryTokenCache(clock=lambda: 1000.0),
        refresh_token_resolver=async_refresh_resolver,
    )
    sp_client = SpApiClient(settings=amazon_settings, transport=transport, token_provider=provider)
    with pytest.raises(AmazonError) as exc_info:
        await sp_client.request("GET", "/orders/v0/orders", account_key="seller-1")
    assert exc_info.value.error_code == AMAZON_RESPONSE_INVALID


@pytest.mark.asyncio
async def test_sp_api_client_timeout(amazon_settings, async_refresh_resolver):
    def handler(request: httpx.Request) -> httpx.Response:
        if "mock.lwa.local" in str(request.url):
            return lwa_success_handler()(request)
        raise httpx.ReadTimeout("timeout")

    transport = make_transport(handler)
    provider = CachingRefreshTokenProvider(
        client=LwaTokenClient(settings=amazon_settings, transport=transport),
        cache=InMemoryTokenCache(clock=lambda: 1000.0),
        refresh_token_resolver=async_refresh_resolver,
    )
    sp_client = SpApiClient(settings=amazon_settings, transport=transport, token_provider=provider)
    with pytest.raises(AmazonError) as exc_info:
        await sp_client.request("GET", "/orders/v0/orders", account_key="seller-1")
    assert exc_info.value.error_code == "AMAZON_SP_API_TRANSPORT_ERROR"


@pytest.mark.asyncio
async def test_sp_api_logs_do_not_include_access_token(amazon_settings, async_refresh_resolver, caplog):
    def handler(request: httpx.Request) -> httpx.Response:
        if "mock.lwa.local" in str(request.url):
            return lwa_success_handler()(request)
        return httpx.Response(
            401,
            text=json.dumps({"detail": TEST_ACCESS_TOKEN}),
            headers={"content-type": "application/json"},
        )

    transport = make_transport(handler)
    provider = CachingRefreshTokenProvider(
        client=LwaTokenClient(settings=amazon_settings, transport=transport),
        cache=InMemoryTokenCache(clock=lambda: 1000.0),
        refresh_token_resolver=async_refresh_resolver,
    )
    sp_client = SpApiClient(settings=amazon_settings, transport=transport, token_provider=provider)
    with caplog.at_level("WARNING"):
        with pytest.raises(AmazonError):
            await sp_client.request("GET", "/orders/v0/orders", account_key="seller-1")

    combined = " ".join(record.message for record in caplog.records)
    assert TEST_ACCESS_TOKEN not in combined
