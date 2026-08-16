"""LWA authorization-code exchange unit tests."""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest

from app.integrations.amazon.config import AmazonEndpointMode, AmazonSettings
from app.integrations.amazon.exceptions import (
    AMAZON_LWA_RATE_LIMITED,
    AMAZON_LWA_TOKEN_INVALID,
    AMAZON_LWA_UNAVAILABLE,
    AMAZON_OAUTH_DISABLED,
    AMAZON_OAUTH_TOKEN_EXCHANGE_FAILED,
    AMAZON_RESPONSE_INVALID,
    AMAZON_RESPONSE_TOO_LARGE,
    AmazonError,
)
from app.integrations.amazon.lwa import (
    AUTHORIZATION_CODE_MAX_LEN,
    LwaAuthorizationCodeResponse,
    LwaTokenClient,
    LwaTokenResponse,
)
from app.integrations.amazon.transport import (
    ResponseTooLargeError,
    TransportError,
    TransportFailureKind,
)
from tests.integrations.amazon.conftest import (
    TEST_ACCESS_TOKEN,
    TEST_CLIENT_ID,
    TEST_CLIENT_SECRET,
    TEST_REFRESH_TOKEN,
    lwa_success_handler,
    make_transport,
)

CANARY_CODE = "CANARY_OAUTH_CODE_SECRET_MARKER"
CANARY_ACCESS = "CANARY_ACCESS_TOKEN_MARKER"
CANARY_REFRESH = "CANARY_REFRESH_TOKEN_MARKER"
CANARY_CLIENT_SECRET = "CANARY_CLIENT_SECRET_MARKER"
CANARY_ERROR_BODY = f'{{"error":"invalid","error_description":"{CANARY_CODE}"}}'

TEST_AUTH_CODE = "ANspapi-oauth-code-placeholder-value"
TEST_OAUTH_REFRESH_TOKEN = "Atzr|oauth|refresh=token-placeholder"
TEST_OAUTH_ACCESS_TOKEN = "Atza|oauth|access=token-placeholder"
OAUTH_REDIRECT_URI = "https://api.oauth.test/api/v1/amazon/oauth/callback"
LWA_TOKEN_URL = "https://mock.lwa.local/auth/o2/token"


@pytest.fixture
def oauth_amazon_settings() -> AmazonSettings:
    return AmazonSettings(
        enabled=True,
        oauth_enabled=True,
        lwa_client_id=TEST_CLIENT_ID,
        lwa_client_secret=TEST_CLIENT_SECRET,
        lwa_token_url=LWA_TOKEN_URL,
        sp_api_region="na",
        endpoint_mode=AmazonEndpointMode.MOCK,
        user_agent="SellerAI-Copilot-Test/1.0.0 (Language=Python)",
        environment="testing",
        application_id="amzn1.sp.solution.test-app",
        oauth_redirect_uri=OAUTH_REDIRECT_URI,
        oauth_frontend_success_url="https://app.oauth.test/oauth/success",
        oauth_frontend_error_url="https://app.oauth.test/oauth/error",
    )


def _auth_code_success_payload(**overrides: Any) -> dict[str, Any]:
    payload = {
        "access_token": TEST_OAUTH_ACCESS_TOKEN,
        "refresh_token": TEST_OAUTH_REFRESH_TOKEN,
        "token_type": "bearer",
        "expires_in": 3600,
    }
    payload.update(overrides)
    return payload


def _auth_code_success_handler(
    *,
    expected_code: str = TEST_AUTH_CODE,
) -> Any:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["content_type"] = request.headers.get("content-type", "")
        captured["body"] = request.content.decode()
        return httpx.Response(200, json=_auth_code_success_payload())

    handler.captured = captured  # type: ignore[attr-defined]
    handler.expected_code = expected_code  # type: ignore[attr-defined]
    return handler


@pytest.mark.asyncio
async def test_exchange_authorization_code_success(oauth_amazon_settings: AmazonSettings) -> None:
    handler = _auth_code_success_handler()
    client = LwaTokenClient(settings=oauth_amazon_settings, transport=make_transport(handler))
    token = await client.exchange_authorization_code(TEST_AUTH_CODE)

    assert isinstance(token, LwaAuthorizationCodeResponse)
    assert token.access_token == TEST_OAUTH_ACCESS_TOKEN
    assert token.refresh_token == TEST_OAUTH_REFRESH_TOKEN
    assert token.token_type == "bearer"
    assert token.expires_in == 3600

    captured = handler.captured
    assert captured["method"] == "POST"
    assert captured["url"] == LWA_TOKEN_URL
    assert captured["content_type"] == "application/x-www-form-urlencoded;charset=UTF-8"

    form = parse_qs(captured["body"], keep_blank_values=True)
    assert form["grant_type"] == ["authorization_code"]
    assert form["code"] == [TEST_AUTH_CODE]
    assert form["redirect_uri"] == [OAUTH_REDIRECT_URI]
    assert form["client_id"] == [TEST_CLIENT_ID]
    assert form["client_secret"] == [TEST_CLIENT_SECRET]
    assert "code=" not in captured["url"]


@pytest.mark.asyncio
async def test_authorization_code_response_repr_hides_tokens(
    oauth_amazon_settings: AmazonSettings,
) -> None:
    client = LwaTokenClient(
        settings=oauth_amazon_settings,
        transport=make_transport(_auth_code_success_handler()),
    )
    token = await client.exchange_authorization_code(TEST_AUTH_CODE)
    rendered = repr(token)
    assert TEST_OAUTH_ACCESS_TOKEN not in rendered
    assert TEST_OAUTH_REFRESH_TOKEN not in rendered
    assert TEST_OAUTH_ACCESS_TOKEN not in str(token)
    assert TEST_OAUTH_REFRESH_TOKEN not in str(token)


@pytest.mark.asyncio
async def test_lwa_token_response_repr_hides_tokens(amazon_settings: AmazonSettings) -> None:
    client = LwaTokenClient(settings=amazon_settings, transport=make_transport(lwa_success_handler()))
    token = await client.exchange_refresh_token(TEST_REFRESH_TOKEN)
    assert isinstance(token, LwaTokenResponse)
    assert TEST_ACCESS_TOKEN not in repr(token)
    assert TEST_ACCESS_TOKEN not in str(token)


@pytest.mark.asyncio
async def test_authorization_code_response_ignores_extra_fields(
    oauth_amazon_settings: AmazonSettings,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                **_auth_code_success_payload(),
                "scope": "sellingpartnerapi::migration",
            },
        )

    client = LwaTokenClient(settings=oauth_amazon_settings, transport=make_transport(handler))
    token = await client.exchange_authorization_code(TEST_AUTH_CODE)
    assert token.access_token == TEST_OAUTH_ACCESS_TOKEN


@pytest.mark.asyncio
async def test_exchange_authorization_code_oauth_disabled(amazon_settings: AmazonSettings) -> None:
    client = LwaTokenClient(settings=amazon_settings, transport=make_transport(_auth_code_success_handler()))
    with pytest.raises(AmazonError) as exc_info:
        await client.exchange_authorization_code(TEST_AUTH_CODE)
    assert exc_info.value.error_code == AMAZON_OAUTH_DISABLED


@pytest.mark.parametrize("code", [123, None, [], {}])
@pytest.mark.asyncio
async def test_exchange_authorization_code_rejects_non_string_code(
    oauth_amazon_settings: AmazonSettings,
    code: object,
) -> None:
    client = LwaTokenClient(settings=oauth_amazon_settings, transport=make_transport(_auth_code_success_handler()))
    with pytest.raises(AmazonError) as exc_info:
        await client.exchange_authorization_code(code)  # type: ignore[arg-type]
    assert exc_info.value.error_code == AMAZON_OAUTH_TOKEN_EXCHANGE_FAILED
    assert CANARY_CODE not in str(exc_info.value)


@pytest.mark.parametrize("code", ["", "   "])
@pytest.mark.asyncio
async def test_exchange_authorization_code_rejects_empty_code(
    oauth_amazon_settings: AmazonSettings,
    code: str,
) -> None:
    client = LwaTokenClient(settings=oauth_amazon_settings, transport=make_transport(_auth_code_success_handler()))
    with pytest.raises(AmazonError) as exc_info:
        await client.exchange_authorization_code(code)
    assert exc_info.value.error_code == AMAZON_OAUTH_TOKEN_EXCHANGE_FAILED


@pytest.mark.asyncio
async def test_exchange_authorization_code_rejects_overlong_code(
    oauth_amazon_settings: AmazonSettings,
) -> None:
    client = LwaTokenClient(settings=oauth_amazon_settings, transport=make_transport(_auth_code_success_handler()))
    with pytest.raises(AmazonError) as exc_info:
        await client.exchange_authorization_code("A" * (AUTHORIZATION_CODE_MAX_LEN + 1))
    assert exc_info.value.error_code == AMAZON_OAUTH_TOKEN_EXCHANGE_FAILED


@pytest.mark.asyncio
async def test_exchange_authorization_code_rejects_control_characters(
    oauth_amazon_settings: AmazonSettings,
) -> None:
    client = LwaTokenClient(settings=oauth_amazon_settings, transport=make_transport(_auth_code_success_handler()))
    with pytest.raises(AmazonError) as exc_info:
        await client.exchange_authorization_code("valid-code\u0000bad")
    assert exc_info.value.error_code == AMAZON_OAUTH_TOKEN_EXCHANGE_FAILED


@pytest.mark.asyncio
async def test_exchange_authorization_code_rejects_missing_redirect_uri(
    oauth_amazon_settings: AmazonSettings,
) -> None:
    settings = AmazonSettings.model_construct(
        oauth_enabled=True,
        oauth_redirect_uri="",
        lwa_token_url=LWA_TOKEN_URL,
        lwa_client_id=TEST_CLIENT_ID,
        lwa_client_secret=TEST_CLIENT_SECRET,
    )
    client = LwaTokenClient(settings=settings, transport=make_transport(_auth_code_success_handler()))
    with pytest.raises(AmazonError) as exc_info:
        await client.exchange_authorization_code(TEST_AUTH_CODE)
    assert exc_info.value.error_code == AMAZON_OAUTH_TOKEN_EXCHANGE_FAILED


@pytest.mark.parametrize(
    "response_json",
    [
        {"access_token": TEST_OAUTH_ACCESS_TOKEN, "refresh_token": None, "token_type": "bearer", "expires_in": 3600},
        {"access_token": TEST_OAUTH_ACCESS_TOKEN, "refresh_token": "", "token_type": "bearer", "expires_in": 3600},
        {"access_token": TEST_OAUTH_ACCESS_TOKEN, "refresh_token": "   ", "token_type": "bearer", "expires_in": 3600},
        {"access_token": "", "refresh_token": TEST_OAUTH_REFRESH_TOKEN, "token_type": "bearer", "expires_in": 3600},
        {"refresh_token": TEST_OAUTH_REFRESH_TOKEN, "token_type": "bearer", "expires_in": 3600},
        {
            "access_token": TEST_OAUTH_ACCESS_TOKEN,
            "refresh_token": TEST_OAUTH_REFRESH_TOKEN,
            "token_type": "bearer",
            "expires_in": 0,
        },
    ],
)
@pytest.mark.asyncio
async def test_exchange_authorization_code_rejects_invalid_success_payload(
    oauth_amazon_settings: AmazonSettings,
    response_json: dict[str, Any],
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=response_json)

    client = LwaTokenClient(settings=oauth_amazon_settings, transport=make_transport(handler))
    with pytest.raises(AmazonError) as exc_info:
        await client.exchange_authorization_code(TEST_AUTH_CODE)
    assert exc_info.value.error_code == AMAZON_OAUTH_TOKEN_EXCHANGE_FAILED


@pytest.mark.asyncio
async def test_exchange_authorization_code_rejects_malformed_json(
    oauth_amazon_settings: AmazonSettings,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not-json")

    client = LwaTokenClient(settings=oauth_amazon_settings, transport=make_transport(handler))
    with pytest.raises(AmazonError) as exc_info:
        await client.exchange_authorization_code(TEST_AUTH_CODE)
    assert exc_info.value.error_code == AMAZON_OAUTH_TOKEN_EXCHANGE_FAILED


@pytest.mark.asyncio
async def test_exchange_authorization_code_rejects_non_object_json(
    oauth_amazon_settings: AmazonSettings,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=["not", "an", "object"])

    client = LwaTokenClient(settings=oauth_amazon_settings, transport=make_transport(handler))
    with pytest.raises(AmazonError) as exc_info:
        await client.exchange_authorization_code(TEST_AUTH_CODE)
    assert exc_info.value.error_code == AMAZON_OAUTH_TOKEN_EXCHANGE_FAILED


@pytest.mark.parametrize("status_code", [400, 401, 403, 418])
@pytest.mark.asyncio
async def test_exchange_authorization_code_maps_client_errors(
    oauth_amazon_settings: AmazonSettings,
    status_code: int,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, text=CANARY_ERROR_BODY)

    client = LwaTokenClient(settings=oauth_amazon_settings, transport=make_transport(handler))
    with pytest.raises(AmazonError) as exc_info:
        await client.exchange_authorization_code(TEST_AUTH_CODE)
    assert exc_info.value.error_code == AMAZON_OAUTH_TOKEN_EXCHANGE_FAILED
    assert CANARY_CODE not in str(exc_info.value)
    assert exc_info.value.__cause__ is None


@pytest.mark.asyncio
async def test_exchange_authorization_code_maps_rate_limited(
    oauth_amazon_settings: AmazonSettings,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text=CANARY_ERROR_BODY)

    client = LwaTokenClient(settings=oauth_amazon_settings, transport=make_transport(handler))
    with pytest.raises(AmazonError) as exc_info:
        await client.exchange_authorization_code(TEST_AUTH_CODE)
    assert exc_info.value.error_code == AMAZON_LWA_RATE_LIMITED


@pytest.mark.parametrize("status_code", [500, 503])
@pytest.mark.asyncio
async def test_exchange_authorization_code_maps_server_errors(
    oauth_amazon_settings: AmazonSettings,
    status_code: int,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, text=CANARY_ERROR_BODY)

    client = LwaTokenClient(settings=oauth_amazon_settings, transport=make_transport(handler))
    with pytest.raises(AmazonError) as exc_info:
        await client.exchange_authorization_code(TEST_AUTH_CODE)
    assert exc_info.value.error_code == AMAZON_LWA_UNAVAILABLE


@pytest.mark.asyncio
async def test_exchange_authorization_code_maps_timeout(
    oauth_amazon_settings: AmazonSettings,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout with CANARY_OAUTH_CODE_SECRET_MARKER")

    client = LwaTokenClient(settings=oauth_amazon_settings, transport=make_transport(handler))
    with pytest.raises(AmazonError) as exc_info:
        await client.exchange_authorization_code(TEST_AUTH_CODE)
    assert exc_info.value.error_code == AMAZON_LWA_UNAVAILABLE
    assert exc_info.value.cause is None
    assert exc_info.value.__cause__ is None


@pytest.mark.asyncio
async def test_exchange_authorization_code_maps_response_too_large(
    oauth_amazon_settings: AmazonSettings,
) -> None:
    class OversizeTransport:
        async def request(self, *_args: object, **_kwargs: object) -> None:
            raise ResponseTooLargeError(max_bytes=1024)

    client = LwaTokenClient(settings=oauth_amazon_settings, transport=OversizeTransport())
    with pytest.raises(AmazonError) as exc_info:
        await client.exchange_authorization_code(TEST_AUTH_CODE)
    assert exc_info.value.error_code == AMAZON_RESPONSE_TOO_LARGE
    assert exc_info.value.__cause__ is None


@pytest.mark.asyncio
async def test_exchange_authorization_code_error_response_does_not_leak_canary(
    oauth_amazon_settings: AmazonSettings,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            text=(
                f'{{"error":"invalid_grant","error_description":"{CANARY_CODE}",'
                f'"access_token":"{CANARY_ACCESS}","refresh_token":"{CANARY_REFRESH}"}}'
            ),
        )

    client = LwaTokenClient(settings=oauth_amazon_settings, transport=make_transport(handler))
    with caplog.at_level("WARNING"):
        with pytest.raises(AmazonError) as exc_info:
            await client.exchange_authorization_code(CANARY_CODE)

    assert exc_info.value.error_code == AMAZON_OAUTH_TOKEN_EXCHANGE_FAILED
    assert CANARY_CODE not in str(exc_info.value)
    assert CANARY_CODE not in repr(exc_info.value)
    assert CANARY_ACCESS not in str(exc_info.value)
    assert CANARY_REFRESH not in str(exc_info.value)
    assert exc_info.value.cause is None
    combined = " ".join(record.message for record in caplog.records)
    for marker in (CANARY_CODE, CANARY_ACCESS, CANARY_REFRESH, CANARY_CLIENT_SECRET, TEST_CLIENT_SECRET):
        assert marker not in combined


@pytest.mark.asyncio
async def test_exchange_authorization_code_transport_error_logs_safely(
    oauth_amazon_settings: AmazonSettings,
    caplog: pytest.LogCaptureFixture,
) -> None:
    class FailingTransport:
        async def request(self, *_args: object, **_kwargs: object) -> None:
            raise TransportError(kind=TransportFailureKind.NETWORK, message=f"network {CANARY_CODE}")

    client = LwaTokenClient(settings=oauth_amazon_settings, transport=FailingTransport())
    with caplog.at_level("WARNING"):
        with pytest.raises(AmazonError) as exc_info:
            await client.exchange_authorization_code(TEST_AUTH_CODE)

    assert exc_info.value.error_code == AMAZON_LWA_UNAVAILABLE
    combined = " ".join(record.message for record in caplog.records)
    assert CANARY_CODE not in combined
    assert TEST_AUTH_CODE not in combined
    assert "authorization_code_exchange" in combined


@pytest.mark.asyncio
async def test_input_validation_errors_do_not_send_http(
    oauth_amazon_settings: AmazonSettings,
) -> None:
    calls = {"count": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(200, json=_auth_code_success_payload())

    client = LwaTokenClient(settings=oauth_amazon_settings, transport=make_transport(handler))
    with pytest.raises(AmazonError):
        await client.exchange_authorization_code("")
    assert calls["count"] == 0


@pytest.mark.asyncio
async def test_refresh_token_exchange_still_allows_missing_refresh_token_in_response(
    amazon_settings: AmazonSettings,
) -> None:
    client = LwaTokenClient(settings=amazon_settings, transport=make_transport(lwa_success_handler()))
    token = await client.exchange_refresh_token(TEST_REFRESH_TOKEN)
    assert token.refresh_token is None


@pytest.mark.asyncio
async def test_client_credentials_still_allows_missing_refresh_token_in_response(
    amazon_settings: AmazonSettings,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"access_token": "grantless-token", "token_type": "bearer", "expires_in": 3600},
        )

    client = LwaTokenClient(settings=amazon_settings, transport=make_transport(handler))
    token = await client.exchange_client_credentials("sellingpartnerapi::notifications")
    assert token.refresh_token is None


@pytest.mark.asyncio
async def test_refresh_token_400_still_maps_to_token_invalid(amazon_settings: AmazonSettings) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "invalid_grant"})

    client = LwaTokenClient(settings=amazon_settings, transport=make_transport(handler))
    with pytest.raises(AmazonError) as exc_info:
        await client.exchange_refresh_token(TEST_REFRESH_TOKEN)
    assert exc_info.value.error_code == AMAZON_LWA_TOKEN_INVALID


@pytest.mark.asyncio
async def test_refresh_token_malformed_200_still_maps_to_response_invalid(
    amazon_settings: AmazonSettings,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"token_type": "bearer"})

    client = LwaTokenClient(settings=amazon_settings, transport=make_transport(handler))
    with pytest.raises(AmazonError) as exc_info:
        await client.exchange_refresh_token(TEST_REFRESH_TOKEN)
    assert exc_info.value.error_code == AMAZON_RESPONSE_INVALID
