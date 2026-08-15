from __future__ import annotations

import asyncio

import httpx
import pytest

from app.integrations.amazon.exceptions import (
    AMAZON_CONFIG_INVALID,
    AMAZON_LWA_TOKEN_INVALID,
    AmazonError,
)
from app.integrations.amazon.lwa import CachingRefreshTokenProvider, LwaTokenClient
from app.integrations.amazon.token_cache import CachedAccessToken, InMemoryTokenCache
from tests.integrations.amazon.conftest import (
    TEST_ACCESS_TOKEN,
    TEST_REFRESH_TOKEN,
    lwa_success_handler,
    make_transport,
)


def test_cached_access_token_respects_skew_without_sleep():
    now = 1_000_000.0
    token = CachedAccessToken.from_token(
        access_token="at",
        expires_in=3600,
        now=now,
    )
    assert token.is_expired(skew_seconds=60, now=now + 3500) is False
    assert token.is_expired(skew_seconds=60, now=now + 3541) is True


def test_in_memory_cache_get_set_invalidate():
    now = 1000.0
    cache = InMemoryTokenCache(clock=lambda: now)
    token = CachedAccessToken(access_token="cached", expires_at=now + 60)
    cache.set("acct-1", token)
    assert cache.get("acct-1") == token
    cache.invalidate("acct-1")
    assert cache.get("acct-1") is None


@pytest.mark.asyncio
async def test_provider_resolver_empty_fails_closed(amazon_settings):
    async def empty(_key: str) -> None:
        return None

    client = LwaTokenClient(settings=amazon_settings, transport=make_transport(lwa_success_handler()))
    provider = CachingRefreshTokenProvider(
        client=client,
        refresh_token_resolver=empty,
    )
    with pytest.raises(AmazonError) as exc_info:
        await provider.get_access_token(account_key="acct-1")
    assert exc_info.value.error_code == AMAZON_LWA_TOKEN_INVALID


@pytest.mark.asyncio
async def test_provider_resolver_whitespace_refresh_token_fails_closed(amazon_settings):
    async def whitespace(_key: str) -> str:
        return "   "

    client = LwaTokenClient(settings=amazon_settings, transport=make_transport(lwa_success_handler()))
    provider = CachingRefreshTokenProvider(
        client=client,
        refresh_token_resolver=whitespace,
    )
    with pytest.raises(AmazonError) as exc_info:
        await provider.get_access_token(account_key="acct-1")
    assert exc_info.value.error_code == AMAZON_LWA_TOKEN_INVALID


@pytest.mark.asyncio
async def test_provider_blank_account_key_fails_closed(amazon_settings):
    async def resolve(_key: str) -> str:
        return TEST_REFRESH_TOKEN

    client = LwaTokenClient(settings=amazon_settings, transport=make_transport(lwa_success_handler()))
    provider = CachingRefreshTokenProvider(client=client, refresh_token_resolver=resolve)
    with pytest.raises(AmazonError) as exc_info:
        await provider.get_access_token(account_key="   ")
    assert exc_info.value.error_code == AMAZON_CONFIG_INVALID


@pytest.mark.asyncio
async def test_provider_does_not_cache_failed_lwa(amazon_settings):
    calls = 0

    async def resolve(_key: str) -> str:
        return TEST_REFRESH_TOKEN

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(400, json={"error": "invalid_grant"})

    client = LwaTokenClient(settings=amazon_settings, transport=make_transport(handler))
    cache = InMemoryTokenCache()
    provider = CachingRefreshTokenProvider(
        client=client,
        cache=cache,
        refresh_token_resolver=resolve,
    )
    with pytest.raises(AmazonError):
        await provider.get_access_token(account_key="acct-1")
    assert cache.get("acct-1") is None
    assert calls == 1


@pytest.mark.asyncio
async def test_single_flight_only_one_lwa_exchange(amazon_settings):
    lwa_calls = 0

    async def resolve(_key: str) -> str:
        return TEST_REFRESH_TOKEN

    def counting_handler(request: httpx.Request) -> httpx.Response:
        nonlocal lwa_calls
        if "mock.lwa.local" in str(request.url):
            lwa_calls += 1
        return lwa_success_handler()(request)

    transport = make_transport(counting_handler)
    client = LwaTokenClient(settings=amazon_settings, transport=transport)
    provider = CachingRefreshTokenProvider(
        client=client,
        cache=InMemoryTokenCache(clock=lambda: 1000.0),
        refresh_token_resolver=resolve,
    )

    results = await asyncio.gather(
        provider.get_access_token(account_key="same"),
        provider.get_access_token(account_key="same"),
        provider.get_access_token(account_key="same"),
    )
    assert results == [TEST_ACCESS_TOKEN, TEST_ACCESS_TOKEN, TEST_ACCESS_TOKEN]
    assert lwa_calls == 1


@pytest.mark.asyncio
async def test_different_account_keys_refresh_independently(amazon_settings):
    lwa_calls = 0

    async def resolve(key: str) -> str:
        return f"{TEST_REFRESH_TOKEN}-{key}"

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal lwa_calls
        if "mock.lwa.local" in str(request.url):
            lwa_calls += 1
            return httpx.Response(
                200,
                json={
                    "access_token": f"{TEST_ACCESS_TOKEN}-{lwa_calls}",
                    "token_type": "bearer",
                    "expires_in": 3600,
                },
            )
        return httpx.Response(200)

    client = LwaTokenClient(settings=amazon_settings, transport=make_transport(handler))
    provider = CachingRefreshTokenProvider(
        client=client,
        cache=InMemoryTokenCache(clock=lambda: 1000.0),
        refresh_token_resolver=resolve,
    )
    first = await provider.get_access_token(account_key="a1")
    second = await provider.get_access_token(account_key="a2")
    assert first != second
    assert lwa_calls == 2
