from __future__ import annotations

import importlib
import os
import subprocess
import sys
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any
from unittest.mock import patch

import httpx
import pytest
from pydantic import ValidationError

from app.integrations.amazon.client import SpApiClient
from app.integrations.amazon.exceptions import (
    AMAZON_RESPONSE_INVALID,
    AMAZON_RESPONSE_TOO_LARGE,
    AMAZON_SP_API_FORBIDDEN,
    AMAZON_SP_API_RATE_LIMITED,
    AMAZON_SP_API_SERVER_ERROR,
    AMAZON_SP_API_TRANSPORT_ERROR,
    AMAZON_SP_API_UNAUTHORIZED,
    AmazonError,
)
from app.integrations.amazon.lwa import CachingRefreshTokenProvider, LwaTokenClient
from app.integrations.amazon.sellers import (
    MARKETPLACE_PARTICIPATIONS_PATH,
    SellerMarketplaceParticipation,
    SellersClient,
    map_marketplace_participations,
)
from app.integrations.amazon.token_cache import InMemoryTokenCache
from app.integrations.amazon.transport import HttpxTransport
from tests.integrations.amazon.conftest import (
    TEST_ACCESS_TOKEN,
    TEST_REFRESH_TOKEN,
    lwa_success_handler,
    make_transport,
)

CANARY = "CANARY_SECRET_PAYLOAD_MARKER_XYZ"
RESPONSE_CANARY = "SENSITIVE_RESPONSE_CANARY_7f3e"
ACCOUNT_KEY_MARKER = "SENSITIVE_ACCOUNT_KEY_MARKER_abc123"
SENSITIVE_MARKERS = (TEST_ACCESS_TOKEN, TEST_REFRESH_TOKEN, CANARY, RESPONSE_CANARY, ACCOUNT_KEY_MARKER)


def _wire_item(
    *,
    marketplace_id: str = "ATVPDKIKX0DER",
    country_code: str = "US",
    name: str = "Amazon.com",
    default_currency_code: str = "USD",
    default_language_code: str = "en_US",
    domain_name: str = "www.amazon.com",
    participating: bool = True,
    suspended_listings: bool = False,
    extra_marketplace: dict[str, Any] | None = None,
    extra_participation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    marketplace: dict[str, Any] = {
        "id": marketplace_id,
        "countryCode": country_code,
        "name": name,
        "defaultCurrencyCode": default_currency_code,
        "defaultLanguageCode": default_language_code,
        "domainName": domain_name,
    }
    if extra_marketplace:
        marketplace.update(extra_marketplace)
    participation: dict[str, Any] = {
        "isParticipating": participating,
        "hasSuspendedListings": suspended_listings,
    }
    if extra_participation:
        participation.update(extra_participation)
    return {"marketplace": marketplace, "participation": participation}


def _wire_response(*items: dict[str, Any]) -> dict[str, Any]:
    return {"payload": list(items)}


def _combined_output(capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture) -> str:
    captured = capsys.readouterr()
    return " ".join(
        [
            captured.out,
            captured.err,
            " ".join(record.message for record in caplog.records),
        ]
    )


def _assert_no_sensitive_leaks(text: str) -> None:
    for marker in SENSITIVE_MARKERS:
        assert marker not in text


def _scan_value(value: object, *, seen: set[int]) -> None:
    if value is None or isinstance(value, bool | int | float):
        return
    if isinstance(value, str | bytes):
        text = value if isinstance(value, str) else value.decode("utf-8", errors="replace")
        _assert_no_sensitive_leaks(text)
        return

    obj_id = id(value)
    if obj_id in seen:
        return
    seen.add(obj_id)

    _assert_no_sensitive_leaks(str(value))
    _assert_no_sensitive_leaks(repr(value))

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


def _make_sellers_client(
    handler: Any,
    *,
    amazon_settings: Any,
    async_refresh_resolver: Any,
) -> tuple[SellersClient, list[httpx.Request]]:
    sp_api_calls: list[httpx.Request] = []

    def combined_handler(request: httpx.Request) -> httpx.Response:
        if "mock.lwa.local" in str(request.url):
            return lwa_success_handler()(request)
        sp_api_calls.append(request)
        return handler(request)

    transport = make_transport(combined_handler)
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
    return SellersClient(sp_client), sp_api_calls


def test_map_single_us_marketplace():
    payload = _wire_response(_wire_item())
    result = map_marketplace_participations(payload)
    assert len(result) == 1
    item = result[0]
    assert item.marketplace_id == "ATVPDKIKX0DER"
    assert item.country_code == "US"
    assert item.name == "Amazon.com"
    assert item.default_currency_code == "USD"
    assert item.default_language_code == "en_US"
    assert item.domain_name == "www.amazon.com"
    assert item.participating is True
    assert item.suspended_listings is False


def test_map_multiple_marketplaces_preserves_order():
    payload = _wire_response(
        _wire_item(marketplace_id="M1", country_code="US"),
        _wire_item(marketplace_id="M2", country_code="CA"),
        _wire_item(marketplace_id="M3", country_code="MX"),
    )
    result = map_marketplace_participations(payload)
    assert [item.marketplace_id for item in result] == ["M1", "M2", "M3"]


def test_empty_payload_returns_empty_tuple():
    assert map_marketplace_participations({"payload": []}) == ()


@pytest.mark.parametrize(
    ("participating", "suspended", "expected"),
    [
        (True, False, True),
        (False, False, False),
        (True, True, False),
        (False, True, False),
    ],
)
def test_sync_eligible_from_participation_flags(
    participating: bool,
    suspended: bool,
    expected: bool,
):
    payload = _wire_response(
        _wire_item(participating=participating, suspended_listings=suspended),
    )
    result = map_marketplace_participations(payload)[0]
    assert result.sync_eligible is expected


def test_unknown_fields_are_ignored():
    item = _wire_item(
        extra_marketplace={"futureField": "ignored"},
        extra_participation={"futureFlag": "ignored"},
    )
    payload = _wire_response(item)
    payload["futureTopLevel"] = "ignored"
    item["futureItemField"] = "ignored"
    result = map_marketplace_participations(payload)
    assert len(result) == 1


def test_domain_object_is_immutable():
    payload = _wire_response(_wire_item())
    item = map_marketplace_participations(payload)[0]
    with pytest.raises(FrozenInstanceError):
        item.marketplace_id = "changed"  # type: ignore[misc]
    with pytest.raises(AttributeError):
        item.sync_eligible = False  # type: ignore[misc]


def test_constructor_does_not_accept_sync_eligible():
    with pytest.raises(TypeError, match="sync_eligible"):
        SellerMarketplaceParticipation(
            marketplace_id="M1",
            country_code="US",
            name="Amazon.com",
            default_currency_code="USD",
            default_language_code="en_US",
            domain_name="www.amazon.com",
            participating=False,
            suspended_listings=False,
            sync_eligible=True,  # type: ignore[call-arg]
        )


def test_sync_eligible_cannot_contradict_participation_flags():
    item = SellerMarketplaceParticipation(
        marketplace_id="M1",
        country_code="US",
        name="Amazon.com",
        default_currency_code="USD",
        default_language_code="en_US",
        domain_name="www.amazon.com",
        participating=False,
        suspended_listings=False,
    )
    assert item.sync_eligible is False


def test_domain_object_has_no_copy_update_entrypoint():
    item = map_marketplace_participations(_wire_response(_wire_item()))[0]
    assert not hasattr(item, "model_copy")
    assert not hasattr(item, "copy")


@pytest.mark.asyncio
async def test_get_marketplace_participations_uses_exact_path_and_single_request(
    amazon_settings,
    async_refresh_resolver,
):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_wire_response(_wire_item()))

    client, calls = _make_sellers_client(handler, amazon_settings=amazon_settings, async_refresh_resolver=async_refresh_resolver)
    await client.get_marketplace_participations(account_key="test-account")
    assert len(calls) == 1
    assert calls[0].method == "GET"
    assert calls[0].url.path == MARKETPLACE_PARTICIPATIONS_PATH


@pytest.mark.asyncio
async def test_account_key_not_in_http_request(
    amazon_settings,
    async_refresh_resolver,
):
    def handler(request: httpx.Request) -> httpx.Response:
        url_text = str(request.url)
        body_text = request.content.decode(errors="replace")
        header_text = " ".join(request.headers.values())
        combined = " ".join([url_text, body_text, header_text])
        assert ACCOUNT_KEY_MARKER not in combined
        return httpx.Response(200, json=_wire_response(_wire_item()))

    client, _calls = _make_sellers_client(
        handler,
        amazon_settings=amazon_settings,
        async_refresh_resolver=async_refresh_resolver,
    )
    await client.get_marketplace_participations(account_key=ACCOUNT_KEY_MARKER)


@pytest.mark.asyncio
async def test_account_key_not_in_logs_or_exceptions(
    amazon_settings,
    async_refresh_resolver,
    caplog: pytest.LogCaptureFixture,
):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"errors": []}, headers={"x-amzn-requestid": "rid-403"})

    client, _calls = _make_sellers_client(
        handler,
        amazon_settings=amazon_settings,
        async_refresh_resolver=async_refresh_resolver,
    )
    with caplog.at_level("WARNING"):
        with pytest.raises(AmazonError) as exc_info:
            await client.get_marketplace_participations(account_key=ACCOUNT_KEY_MARKER)

    _assert_no_sensitive_leaks(str(exc_info.value))
    _assert_no_sensitive_leaks(repr(exc_info.value))
    for value in vars(exc_info.value).values():
        _scan_value(value, seen=set())
    _scan_exception_chain(exc_info.value, seen=set())
    _assert_no_sensitive_leaks(" ".join(record.message for record in caplog.records))


@pytest.mark.asyncio
async def test_get_marketplace_participations_includes_auth_headers(
    amazon_settings,
    async_refresh_resolver,
):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("x-amz-access-token") == TEST_ACCESS_TOKEN
        return httpx.Response(200, json=_wire_response(_wire_item()))

    client, _calls = _make_sellers_client(handler, amazon_settings=amazon_settings, async_refresh_resolver=async_refresh_resolver)
    await client.get_marketplace_participations(account_key="test-account")


@pytest.mark.asyncio
async def test_request_id_does_not_affect_payload_mapping(
    amazon_settings,
    async_refresh_resolver,
):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_wire_response(_wire_item()),
            headers={"x-amzn-requestid": "req-with-canary-" + CANARY},
        )

    client, _calls = _make_sellers_client(handler, amazon_settings=amazon_settings, async_refresh_resolver=async_refresh_resolver)
    result = await client.get_marketplace_participations(account_key="test-account")
    assert result[0].country_code == "US"


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param([], id="top_level_array"),
        pytest.param("string", id="top_level_string"),
        pytest.param(None, id="top_level_null"),
        pytest.param({}, id="payload_missing"),
        pytest.param({"payload": None}, id="payload_null"),
        pytest.param({"payload": "bad"}, id="payload_not_list"),
        pytest.param({"payload": ["bad"]}, id="item_not_object"),
        pytest.param({"payload": [{"participation": {"isParticipating": True, "hasSuspendedListings": False}}]}, id="marketplace_missing"),
        pytest.param({"payload": [{"marketplace": {"id": "M1", "countryCode": "US", "name": "n", "defaultCurrencyCode": "USD", "defaultLanguageCode": "en", "domainName": "d.com"}}]}, id="participation_missing"),
        pytest.param({"payload": [_wire_item(marketplace_id="")]}, id="marketplace_id_blank"),
        pytest.param({"payload": [_wire_item(marketplace_id="   ")]}, id="marketplace_id_whitespace"),
        pytest.param({"payload": [{"marketplace": {"id": None, "countryCode": "US", "name": "n", "defaultCurrencyCode": "USD", "defaultLanguageCode": "en", "domainName": "d.com"}, "participation": {"isParticipating": True, "hasSuspendedListings": False}}]}, id="marketplace_id_null"),
        pytest.param({"payload": [_wire_item(extra_marketplace={"countryCode": 123})]}, id="country_code_type_error"),
        pytest.param({"payload": [_wire_item(extra_participation={"isParticipating": 1})]}, id="is_participating_int"),
        pytest.param({"payload": [_wire_item(extra_participation={"isParticipating": "true"})]}, id="is_participating_string"),
        pytest.param({"payload": [_wire_item(extra_participation={"hasSuspendedListings": 0})]}, id="has_suspended_int"),
        pytest.param({"payload": [_wire_item(extra_participation={"hasSuspendedListings": "false"})]}, id="has_suspended_string"),
        pytest.param(
            {
                "payload": [
                    _wire_item(marketplace_id="GOOD"),
                    _wire_item(marketplace_id=""),
                ]
            },
            id="partial_invalid_fails_whole_response",
        ),
    ],
)
def test_map_rejects_invalid_payload(payload: Any, caplog: pytest.LogCaptureFixture):
    with caplog.at_level("WARNING"):
        with pytest.raises(AmazonError) as exc_info:
            map_marketplace_participations(payload)
    assert exc_info.value.error_code == AMAZON_RESPONSE_INVALID
    _assert_no_sensitive_leaks(" ".join(record.message for record in caplog.records))


@pytest.mark.asyncio
async def test_client_rejects_invalid_json(
    amazon_settings,
    async_refresh_resolver,
    caplog: pytest.LogCaptureFixture,
):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"{not-json " + CANARY.encode() + b"}",
            headers={"content-type": "application/json", "x-amzn-requestid": "rid-1"},
        )

    client, _calls = _make_sellers_client(handler, amazon_settings=amazon_settings, async_refresh_resolver=async_refresh_resolver)
    with caplog.at_level("WARNING"):
        with pytest.raises(AmazonError) as exc_info:
            await client.get_marketplace_participations(account_key="test-account")
    assert exc_info.value.error_code == AMAZON_RESPONSE_INVALID
    _assert_no_sensitive_leaks(" ".join(record.message for record in caplog.records))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "expected_code"),
    [
        (401, AMAZON_SP_API_UNAUTHORIZED),
        (403, AMAZON_SP_API_FORBIDDEN),
        (429, AMAZON_SP_API_RATE_LIMITED),
        (500, AMAZON_SP_API_SERVER_ERROR),
    ],
)
async def test_http_errors_keep_existing_codes(
    status_code: int,
    expected_code: str,
    amazon_settings,
    async_refresh_resolver,
):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json={"errors": []}, headers={"x-amzn-requestid": "rid-2"})

    client, _calls = _make_sellers_client(handler, amazon_settings=amazon_settings, async_refresh_resolver=async_refresh_resolver)
    with pytest.raises(AmazonError) as exc_info:
        await client.get_marketplace_participations(account_key="test-account")
    assert exc_info.value.error_code == expected_code


@pytest.mark.asyncio
async def test_transport_timeout_maps_to_transport_error(
    amazon_settings,
    async_refresh_resolver,
):
    def handler(request: httpx.Request) -> httpx.Response:
        if "mock.lwa.local" in str(request.url):
            return lwa_success_handler()(request)
        raise httpx.TimeoutException("timeout")

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
    )
    client = SellersClient(sp_client)
    with pytest.raises(AmazonError) as exc_info:
        await client.get_marketplace_participations(account_key="test-account")
    assert exc_info.value.error_code == AMAZON_SP_API_TRANSPORT_ERROR
    assert not isinstance(exc_info.value.cause, httpx.Request)
    assert not isinstance(exc_info.value.cause, httpx.Response)


@pytest.mark.asyncio
async def test_oversize_response_maps_to_response_too_large(
    amazon_settings,
    async_refresh_resolver,
):
    huge = b"x" * 128

    def handler(request: httpx.Request) -> httpx.Response:
        if "mock.lwa.local" in str(request.url):
            return lwa_success_handler()(request)
        return httpx.Response(
            200,
            content=huge,
            headers={"content-type": "application/json"},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    transport = HttpxTransport(client=client, max_response_bytes=32)
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
    )
    sellers = SellersClient(sp_client)
    with pytest.raises(AmazonError) as exc_info:
        await sellers.get_marketplace_participations(account_key="test-account")
    assert exc_info.value.error_code == AMAZON_RESPONSE_TOO_LARGE


def test_domain_model_has_no_can_publish_or_global_auth_fields():
    fields = SellerMarketplaceParticipation.__dataclass_fields__
    assert "can_publish" not in fields
    assert "authorized_for_all_operations" not in fields
    assert "sync_eligible" not in fields
    assert isinstance(getattr(SellerMarketplaceParticipation, "sync_eligible"), property)


def test_atvpdkikx0der_treated_as_generic_data_not_hardcoded():
    payload = _wire_response(_wire_item(marketplace_id="ATVPDKIKX0DER"))
    item = map_marketplace_participations(payload)[0]
    assert item.marketplace_id == "ATVPDKIKX0DER"
    assert item.sync_eligible is True


def test_import_amazon_package_does_not_modify_environ_or_read_env_files():
    env_before = dict(os.environ)
    opened: list[str] = []
    original_open = open

    def tracking_open(file: Any, *args: Any, **kwargs: Any):
        opened.append(str(file))
        return original_open(file, *args, **kwargs)

    with patch("builtins.open", tracking_open):
        importlib.import_module("app.integrations.amazon")

    assert dict(os.environ) == env_before
    assert not any(".env.amazon.sandbox" in path for path in opened)
    assert not any(path.endswith("/backend/.env") or path.endswith("\\backend\\.env") for path in opened)


def test_sellers_module_import_does_not_modify_environ_or_read_env_files():
    env_before = dict(os.environ)
    opened: list[str] = []
    original_open = open

    def tracking_open(file: Any, *args: Any, **kwargs: Any):
        opened.append(str(file))
        return original_open(file, *args, **kwargs)

    with patch("builtins.open", tracking_open):
        importlib.import_module("app.integrations.amazon.sellers")

    assert dict(os.environ) == env_before
    assert not any(".env.amazon.sandbox" in path for path in opened)
    assert not any(path.endswith("/backend/.env") or path.endswith("\\backend\\.env") for path in opened)


def test_sandbox_checker_import_does_not_modify_environ_or_read_env_files():
    backend_dir = Path(__file__).resolve().parents[3]
    script_path = backend_dir / "scripts" / "check_amazon_sp_api_sandbox.py"
    repo_root = backend_dir.parent
    code = f"""
import os
import sys
from pathlib import Path
from unittest.mock import patch

backend = Path({str(backend_dir)!r})
repo = Path({str(repo_root)!r})
sys.path.insert(0, str(backend))
opened = []
original_open = open
def tracking_open(file, *args, **kwargs):
    opened.append(str(file))
    return original_open(file, *args, **kwargs)
env_before = dict(os.environ)
with patch("builtins.open", tracking_open):
    import importlib.util
    spec = importlib.util.spec_from_file_location("sandbox_check", {str(script_path)!r})
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
assert dict(os.environ) == env_before
assert not any(".env.amazon.sandbox" in p for p in opened)
assert not any(p.endswith("/backend/.env") for p in opened)
print("ok")
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout


def test_sandbox_dry_run_subprocess_still_passes_without_network(backend_dir: Path | None = None):
    backend = backend_dir or Path(__file__).resolve().parents[3]
    result = subprocess.run(
        [sys.executable, "scripts/check_amazon_sp_api_sandbox.py"],
        cwd=backend,
        capture_output=True,
        text=True,
        check=False,
    )
    combined = f"{result.stdout}\n{result.stderr}"
    assert result.returncode == 0
    assert "dry-run" in result.stdout
    assert "network: disabled" in result.stdout
    assert CANARY not in combined


@pytest.mark.asyncio
async def test_invalid_schema_logs_do_not_include_canary_payload(
    amazon_settings,
    async_refresh_resolver,
    caplog: pytest.LogCaptureFixture,
):
    invalid = {
        "payload": [
            {
                "marketplace": {
                    "id": "M1",
                    "countryCode": "US",
                    "name": CANARY,
                    "defaultCurrencyCode": "USD",
                    "defaultLanguageCode": "en_US",
                    "domainName": "www.amazon.com",
                },
                "participation": {
                    "isParticipating": "true",
                    "hasSuspendedListings": False,
                },
            }
        ]
    }

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=invalid)

    client, _calls = _make_sellers_client(handler, amazon_settings=amazon_settings, async_refresh_resolver=async_refresh_resolver)
    with caplog.at_level("WARNING"):
        with pytest.raises(AmazonError):
            await client.get_marketplace_participations(account_key="test-account")
    _assert_no_sensitive_leaks(" ".join(record.message for record in caplog.records))


def test_domain_object_does_not_retain_raw_payload():
    payload = _wire_response(_wire_item(name=RESPONSE_CANARY))
    item = map_marketplace_participations(payload)[0]
    assert item.name == RESPONSE_CANARY
    assert not hasattr(item, "payload")
    assert not hasattr(item, "raw_payload")
    assert "payload" not in vars(item)


def test_sensitive_invalid_payload_not_in_exception_chain(caplog: pytest.LogCaptureFixture):
    invalid = {
        "payload": [
            {
                "marketplace": {
                    "id": "M1",
                    "countryCode": "US",
                    "name": RESPONSE_CANARY,
                    "defaultCurrencyCode": "USD",
                    "defaultLanguageCode": "en_US",
                    "domainName": "www.amazon.com",
                },
                "participation": {
                    "isParticipating": RESPONSE_CANARY,
                    "hasSuspendedListings": False,
                },
            }
        ]
    }
    with caplog.at_level("WARNING"):
        with pytest.raises(AmazonError) as exc_info:
            map_marketplace_participations(invalid)

    assert exc_info.value.error_code == AMAZON_RESPONSE_INVALID
    assert exc_info.value.__cause__ is None
    assert not isinstance(exc_info.value.__context__, ValidationError)
    _scan_exception_chain(exc_info.value, seen=set())
    _assert_no_sensitive_leaks(" ".join(record.message for record in caplog.records))


def test_amazon_error_from_mapping_has_no_httpx_objects():
    with pytest.raises(AmazonError) as exc_info:
        map_marketplace_participations({"payload": [1]})
    assert exc_info.value.error_code == AMAZON_RESPONSE_INVALID
    assert not hasattr(exc_info.value, "response")
