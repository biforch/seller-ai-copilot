from __future__ import annotations

import httpx
import pytest

from app.integrations.amazon.exceptions import (
    AMAZON_LWA_UNAVAILABLE,
    AMAZON_RESPONSE_TOO_LARGE,
    AMAZON_SP_API_TRANSPORT_ERROR,
    AmazonError,
)
from app.integrations.amazon.lwa import LwaTokenClient
from app.integrations.amazon.transport import (
    HttpxTransport,
    ResponseTooLargeError,
    TransportError,
    TransportFailureKind,
)
from tests.integrations.amazon.conftest import (
    TEST_REFRESH_TOKEN,
    lwa_success_handler,
    make_transport,
)

SENSITIVE_ACCESS = "Atza|SENSITIVE_ACCESS_TOKEN"
SENSITIVE_REFRESH = "Atzr|SENSITIVE_REFRESH_TOKEN"
SENSITIVE_SECRET = "SUPER_SECRET_CLIENT_VALUE"
SENSITIVE_SECRETS = (SENSITIVE_ACCESS, SENSITIVE_REFRESH, SENSITIVE_SECRET)


def _assert_text_has_no_secrets(text: str) -> None:
    for secret in SENSITIVE_SECRETS:
        assert secret not in text


def _scan_value(value: object, *, seen: set[int]) -> None:
    if value is None or isinstance(value, bool | int | float):
        return
    if isinstance(value, str | bytes):
        text = value if isinstance(value, str) else value.decode("utf-8", errors="replace")
        _assert_text_has_no_secrets(text)
        return

    obj_id = id(value)
    if obj_id in seen:
        return
    seen.add(obj_id)

    _assert_text_has_no_secrets(str(value))
    _assert_text_has_no_secrets(repr(value))

    if isinstance(value, httpx.Request):
        for header_value in value.headers.values():
            _scan_value(header_value, seen=seen)
        _scan_value(value.content, seen=seen)
        return

    if isinstance(value, httpx.Response):
        for header_value in value.headers.values():
            _scan_value(header_value, seen=seen)
        _scan_value(value.content, seen=seen)
        return

    if isinstance(value, BaseException):
        _scan_exception_chain(value, seen=seen)
        return

    if isinstance(value, dict):
        for item_key, item_value in value.items():
            _scan_value(item_key, seen=seen)
            _scan_value(item_value, seen=seen)
        return

    if isinstance(value, list | tuple | set | frozenset):
        for item in value:
            _scan_value(item, seen=seen)
        return

    if hasattr(value, "__dict__"):
        for item_value in vars(value).values():
            _scan_value(item_value, seen=seen)


def _scan_exception_chain(exc: BaseException, *, seen: set[int]) -> None:
    current: BaseException | None = exc
    chain_seen: set[int] = set()
    while current is not None and id(current) not in chain_seen:
        chain_seen.add(id(current))
        _scan_value(current, seen=seen)
        current = current.__cause__ or current.__context__


def _assert_transport_error_isolated(transport_error: TransportError) -> None:
    assert transport_error.__cause__ is None
    assert transport_error.__context__ is None
    assert not isinstance(getattr(transport_error, "cause", None), BaseException)
    for value in vars(transport_error).values():
        assert not isinstance(value, httpx.Request | httpx.Response | httpx.HTTPError)


def _assert_amazon_error_has_no_httpx_secrets(
    exc_info: pytest.ExceptionInfo[AmazonError],
    *,
    caplog: pytest.LogCaptureFixture,
) -> None:
    assert exc_info.value.error_code == AMAZON_LWA_UNAVAILABLE
    assert exc_info.value.message == "Login with Amazon token service is unavailable"

    transport_error = exc_info.value.__cause__
    assert isinstance(transport_error, TransportError)
    _assert_transport_error_isolated(transport_error)

    _scan_exception_chain(exc_info.value, seen=set())
    log_text = " ".join(record.message for record in caplog.records)
    _assert_text_has_no_secrets(log_text)


def _sensitive_request() -> httpx.Request:
    return httpx.Request(
        "POST",
        "https://mock.lwa.local/auth/o2/token",
        headers={
            "x-amz-access-token": SENSITIVE_ACCESS,
            "Content-Type": "application/x-www-form-urlencoded",
        },
        content=(
            f"refresh_token={SENSITIVE_REFRESH}&client_secret={SENSITIVE_SECRET}"
        ).encode(),
    )


@pytest.mark.asyncio
async def test_httpx_transport_returns_response_from_mock():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        return httpx.Response(200, json={"ok": True})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    transport = HttpxTransport(client=client)
    response = await transport.request("GET", "https://mock.example/ping")
    assert response.status_code == 200
    assert response.json() == {"ok": True}
    await client.aclose()


@pytest.mark.asyncio
async def test_httpx_transport_posts_form_data():
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.content.decode()
        return httpx.Response(204)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    transport = HttpxTransport(client=client)
    response = await transport.request(
        "POST",
        "https://mock.example/token",
        headers={"Content-Type": "application/x-form-urlencoded"},
        data={"grant_type": "refresh_token", "client_id": "id"},
    )
    assert response.status_code == 204
    assert "grant_type=refresh_token" in captured["body"]
    await client.aclose()


@pytest.mark.asyncio
async def test_httpx_transport_timeout_raises_transport_error_not_amazon_error():
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    transport = HttpxTransport(client=client)
    with pytest.raises(TransportError) as exc_info:
        await transport.request("GET", "https://mock.example/slow", timeout=0.001)
    assert exc_info.value.kind is TransportFailureKind.TIMEOUT
    _assert_transport_error_isolated(exc_info.value)
    await client.aclose()


@pytest.mark.asyncio
async def test_httpx_transport_does_not_follow_redirects():
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(302, headers={"Location": "https://mock.example/final"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)
    transport = HttpxTransport(client=client)
    response = await transport.request("GET", "https://mock.example/redirect")
    assert response.status_code == 302
    assert len(seen) == 1
    await client.aclose()


@pytest.mark.asyncio
async def test_httpx_transport_accepts_body_at_exact_limit():
    limit = 64

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * limit)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    transport = HttpxTransport(client=client, max_response_bytes=limit)
    response = await transport.request("GET", "https://mock.example/exact")
    assert len(response.content) == limit
    await client.aclose()


@pytest.mark.asyncio
async def test_httpx_transport_rejects_body_over_limit():
    limit = 32

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"y" * (limit + 1))

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    transport = HttpxTransport(client=client, max_response_bytes=limit)
    with pytest.raises(ResponseTooLargeError) as exc_info:
        await transport.request("GET", "https://mock.example/too-large")
    assert exc_info.value.max_bytes == limit
    await client.aclose()


@pytest.mark.asyncio
async def test_httpx_transport_rejects_multi_chunk_cumulative_overflow():
    limit = 48
    body = b"m" * 96

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    transport = HttpxTransport(client=client, max_response_bytes=limit)
    with pytest.raises(ResponseTooLargeError) as exc_info:
        await transport.request("GET", "https://mock.example/chunks")
    assert exc_info.value.max_bytes == limit
    await client.aclose()


@pytest.mark.asyncio
async def test_lwa_maps_transport_timeout_to_lwa_unavailable(amazon_settings):
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout")

    client = LwaTokenClient(settings=amazon_settings, transport=make_transport(handler))
    with pytest.raises(AmazonError) as exc_info:
        await client.exchange_refresh_token(TEST_REFRESH_TOKEN)
    assert exc_info.value.error_code == AMAZON_LWA_UNAVAILABLE


@pytest.mark.asyncio
async def test_sp_api_client_maps_transport_timeout(amazon_settings, async_refresh_resolver):
    from app.integrations.amazon.client import SpApiClient
    from app.integrations.amazon.lwa import CachingRefreshTokenProvider, LwaTokenClient
    from app.integrations.amazon.token_cache import InMemoryTokenCache

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
    assert exc_info.value.error_code == AMAZON_SP_API_TRANSPORT_ERROR


@pytest.mark.asyncio
async def test_lwa_maps_oversized_response(amazon_settings, caplog):
    secret = "Atza|SECRET_TOKEN_VALUE"

    def oversized_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=(secret * 10).encode())

    client = httpx.AsyncClient(transport=httpx.MockTransport(oversized_handler))
    transport = HttpxTransport(client=client, max_response_bytes=32)
    lwa_client = LwaTokenClient(settings=amazon_settings, transport=transport)
    with caplog.at_level("WARNING"):
        with pytest.raises(AmazonError) as exc_info:
            await lwa_client.exchange_refresh_token(TEST_REFRESH_TOKEN)
    assert exc_info.value.error_code == AMAZON_RESPONSE_TOO_LARGE
    assert secret not in str(exc_info.value)
    assert secret not in " ".join(record.message for record in caplog.records)
    await client.aclose()


@pytest.mark.asyncio
async def test_domain_errors_do_not_retain_httpx_transport_error_with_sensitive_request(
    amazon_settings,
    caplog,
):
    httpx_failure = httpx.TransportError("network failed", request=_sensitive_request())

    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx_failure

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    lwa_client = LwaTokenClient(settings=amazon_settings, transport=HttpxTransport(client=client))

    with caplog.at_level("WARNING"):
        with pytest.raises(AmazonError) as exc_info:
            await lwa_client.exchange_refresh_token(TEST_REFRESH_TOKEN)

    _assert_amazon_error_has_no_httpx_secrets(exc_info, caplog=caplog)
    await client.aclose()


@pytest.mark.asyncio
async def test_domain_errors_do_not_retain_httpx_read_timeout_with_sensitive_request(
    amazon_settings,
    caplog,
):
    httpx_failure = httpx.ReadTimeout("timed out", request=_sensitive_request())

    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx_failure

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    lwa_client = LwaTokenClient(settings=amazon_settings, transport=HttpxTransport(client=client))

    with caplog.at_level("WARNING"):
        with pytest.raises(AmazonError) as exc_info:
            await lwa_client.exchange_refresh_token(TEST_REFRESH_TOKEN)

    _assert_amazon_error_has_no_httpx_secrets(exc_info, caplog=caplog)
    transport_error = exc_info.value.__cause__
    assert isinstance(transport_error, TransportError)
    assert transport_error.kind is TransportFailureKind.TIMEOUT
    await client.aclose()
