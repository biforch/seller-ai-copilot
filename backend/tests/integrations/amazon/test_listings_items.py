from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from app.integrations.amazon.client import SpApiClient
from app.integrations.amazon.exceptions import (
    AMAZON_CONFIG_INVALID,
    AMAZON_RESPONSE_INVALID,
    AMAZON_SELLING_PARTNER_ID_REQUIRED,
    AMAZON_SP_API_CLIENT_ERROR,
    AMAZON_SP_API_FORBIDDEN,
    AMAZON_SP_API_RATE_LIMITED,
    AMAZON_SP_API_SERVER_ERROR,
    AMAZON_SP_API_TRANSPORT_ERROR,
    AMAZON_SP_API_UNAUTHORIZED,
    AmazonError,
)
from app.integrations.amazon.listings_items import (
    LISTINGS_API_VERSION,
    MARKETPLACE_ID_MAX_LENGTH,
    ListingsItemsClient,
    SearchListingsItem,
    SearchListingsItemsPage,
    map_search_listings_items_page,
)
from app.integrations.amazon.lwa import CachingRefreshTokenProvider, LwaTokenClient
from app.integrations.amazon.token_cache import InMemoryTokenCache
from tests.integrations.amazon.conftest import (
    TEST_ACCESS_TOKEN,
    TEST_REFRESH_TOKEN,
    lwa_success_handler,
    make_transport,
)

FAKE_SELLER_ID = "FAKESELLER1234"
FAKE_MARKETPLACE_ID = "ATVPDKIKX0DER"
FAKE_PAGE_TOKEN = "FAKE-PAGE-TOKEN-OPAQUE-001"
CANARY = "CANARY_SECRET_PAYLOAD_MARKER_XYZ"
RESPONSE_CANARY = "SENSITIVE_RESPONSE_CANARY_7f3e"
SENSITIVE_MARKERS = (TEST_ACCESS_TOKEN, TEST_REFRESH_TOKEN, FAKE_PAGE_TOKEN, CANARY, RESPONSE_CANARY)


def _wire_summary(
    *,
    marketplace_id: str = FAKE_MARKETPLACE_ID,
    asin: str = "B012345678",
    product_type: str = "PRODUCT",
    status: list[str] | None = None,
    created_date: str = "2021-08-01T00:00:00.000Z",
    last_updated_date: str = "2021-08-02T00:00:00.000Z",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "marketplaceId": marketplace_id,
        "asin": asin,
        "productType": product_type,
        "status": status if status is not None else ["BUYABLE"],
        "createdDate": created_date,
        "lastUpdatedDate": last_updated_date,
    }
    if extra:
        summary.update(extra)
    return summary


def _wire_item(
    *,
    sku: str = "SKU-001",
    summaries: list[dict[str, Any]] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "sku": sku,
        "summaries": summaries if summaries is not None else [_wire_summary()],
    }
    if extra:
        item.update(extra)
    return item


def _wire_page(
    *items: dict[str, Any],
    next_token: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"items": list(items)}
    if next_token is not None:
        payload["pagination"] = {"nextToken": next_token}
    if extra:
        payload.update(extra)
    return payload


def _assert_no_sensitive_leaks(text: str) -> None:
    for marker in SENSITIVE_MARKERS:
        assert marker not in text


def _make_listings_client(
    handler: Any,
    *,
    amazon_settings: Any,
    async_refresh_resolver: Any,
) -> tuple[ListingsItemsClient, list[httpx.Request]]:
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
    return ListingsItemsClient(sp_client), sp_api_calls


def test_map_minimal_normal_page() -> None:
    page = map_search_listings_items_page(
        _wire_page(_wire_item()),
        marketplace_id=FAKE_MARKETPLACE_ID,
    )
    assert len(page.items) == 1
    item = page.items[0]
    assert item.seller_sku == "SKU-001"
    assert item.marketplace_id == FAKE_MARKETPLACE_ID
    assert item.asin == "B012345678"
    assert item.status_codes == ("BUYABLE",)
    assert item.product_type == "PRODUCT"
    assert item.upstream_created_at == datetime(2021, 8, 1, tzinfo=UTC)
    assert item.upstream_last_updated_at == datetime(2021, 8, 2, tzinfo=UTC)
    assert page.next_page_token is None
    assert page.request_id is None


def test_map_multiple_items() -> None:
    page = map_search_listings_items_page(
        _wire_page(_wire_item(sku="SKU-A"), _wire_item(sku="SKU-B")),
        marketplace_id=FAKE_MARKETPLACE_ID,
    )
    assert [item.seller_sku for item in page.items] == ["SKU-A", "SKU-B"]


def test_map_empty_page_allowed() -> None:
    page = map_search_listings_items_page(_wire_page(), marketplace_id=FAKE_MARKETPLACE_ID)
    assert page.items == ()
    assert page.next_page_token is None


def test_map_empty_items_with_next_token_allowed() -> None:
    page = map_search_listings_items_page(
        _wire_page(next_token=FAKE_PAGE_TOKEN),
        marketplace_id=FAKE_MARKETPLACE_ID,
    )
    assert page.items == ()
    assert page.next_page_token == FAKE_PAGE_TOKEN


def test_map_next_token() -> None:
    page = map_search_listings_items_page(
        _wire_page(_wire_item(), next_token=FAKE_PAGE_TOKEN),
        marketplace_id=FAKE_MARKETPLACE_ID,
    )
    assert page.next_page_token == FAKE_PAGE_TOKEN


def test_map_duplicate_statuses_deduped_preserving_order() -> None:
    page = map_search_listings_items_page(
        _wire_page(
            _wire_item(
                summaries=[
                    _wire_summary(status=["BUYABLE", "DISCOVERABLE", "BUYABLE"]),
                ]
            )
        ),
        marketplace_id=FAKE_MARKETPLACE_ID,
    )
    assert page.items[0].status_codes == ("BUYABLE", "DISCOVERABLE")


def test_map_unknown_extra_fields_ignored() -> None:
    page = map_search_listings_items_page(
        _wire_page(
            _wire_item(extra={"futureField": RESPONSE_CANARY}),
            extra={"futureTopLevel": "ignored"},
        ),
        marketplace_id=FAKE_MARKETPLACE_ID,
    )
    assert page.items[0].seller_sku == "SKU-001"
    assert not hasattr(page.items[0], "futureField")


def test_domain_objects_immutable() -> None:
    page = map_search_listings_items_page(_wire_page(_wire_item()), marketplace_id=FAKE_MARKETPLACE_ID)
    item = page.items[0]
    with pytest.raises(FrozenInstanceError):
        item.seller_sku = "changed"  # type: ignore[misc]


def test_domain_object_has_no_raw_payload() -> None:
    page = map_search_listings_items_page(_wire_page(_wire_item()), marketplace_id=FAKE_MARKETPLACE_ID)
    item = page.items[0]
    assert not hasattr(item, "payload")
    assert not hasattr(item, "raw_payload")
    assert "payload" not in vars(item)


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param([], id="top_level_array"),
        pytest.param("string", id="top_level_string"),
        pytest.param(None, id="top_level_null"),
        pytest.param({"items": "bad"}, id="items_not_list"),
        pytest.param({"items": [_wire_item(sku="")]}, id="empty_seller_sku"),
        pytest.param({"items": [_wire_item(sku="   ")]}, id="blank_seller_sku"),
        pytest.param({"items": [_wire_item(summaries=[])]}, id="missing_summary"),
        pytest.param(
            {
                "items": [
                    _wire_item(
                        summaries=[_wire_summary(marketplace_id="OTHER-MARKETPLACE")],
                    )
                ]
            },
            id="marketplace_mismatch",
        ),
        pytest.param(
            {
                "items": [
                    _wire_item(sku="DUP"),
                    _wire_item(sku="DUP"),
                ]
            },
            id="duplicate_identity",
        ),
        pytest.param({"items": [_wire_item(summaries=[_wire_summary(status=["", "BUYABLE"])])]}, id="empty_status"),
        pytest.param({"items": [_wire_item(summaries=[_wire_summary(status=[123])])]}, id="invalid_status_type"),
        pytest.param(
            {"items": [_wire_item(summaries=[_wire_summary(created_date="2021-08-01T00:00:00")])]},
            id="naive_datetime",
        ),
        pytest.param(
            {"items": [_wire_item(summaries=[_wire_summary(created_date="not-a-date")])]},
            id="invalid_datetime",
        ),
        pytest.param({"pagination": {"nextToken": "x" * 3000}}, id="next_token_too_long"),
    ],
)
def test_map_rejects_invalid_payload(payload: Any) -> None:
    with pytest.raises(AmazonError) as exc_info:
        map_search_listings_items_page(payload, marketplace_id=FAKE_MARKETPLACE_ID)
    assert exc_info.value.error_code == AMAZON_RESPONSE_INVALID


def test_map_status_count_boundary_rejected() -> None:
    statuses = [f"STATUS-{index}" for index in range(33)]
    with pytest.raises(AmazonError) as exc_info:
        map_search_listings_items_page(
            _wire_page(_wire_item(summaries=[_wire_summary(status=statuses)])),
            marketplace_id=FAKE_MARKETPLACE_ID,
        )
    assert exc_info.value.error_code == AMAZON_RESPONSE_INVALID


def test_map_status_length_boundary_rejected() -> None:
    with pytest.raises(AmazonError) as exc_info:
        map_search_listings_items_page(
            _wire_page(_wire_item(summaries=[_wire_summary(status=["x" * 65])])),
            marketplace_id=FAKE_MARKETPLACE_ID,
        )
    assert exc_info.value.error_code == AMAZON_RESPONSE_INVALID


def test_sensitive_invalid_payload_not_in_exception_chain() -> None:
    invalid = _wire_page(
        _wire_item(
            summaries=[
                _wire_summary(
                    asin=RESPONSE_CANARY,
                    status=[RESPONSE_CANARY],
                )
            ]
        )
    )
    with pytest.raises(AmazonError) as exc_info:
        map_search_listings_items_page(invalid, marketplace_id=FAKE_MARKETPLACE_ID)
    assert exc_info.value.error_code == AMAZON_RESPONSE_INVALID
    assert exc_info.value.__cause__ is None
    assert not isinstance(exc_info.value.__context__, ValidationError)
    _assert_no_sensitive_leaks(str(exc_info.value))
    _assert_no_sensitive_leaks(repr(exc_info.value))


@pytest.mark.asyncio
async def test_search_listings_items_builds_path_and_query(
    amazon_settings,
    async_refresh_resolver,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_wire_page(_wire_item()))

    client, calls = _make_listings_client(
        handler,
        amazon_settings=amazon_settings,
        async_refresh_resolver=async_refresh_resolver,
    )
    await client.search_listings_items(
        seller_id=FAKE_SELLER_ID,
        marketplace_id=FAKE_MARKETPLACE_ID,
        account_key="test-account",
        page_size=20,
    )
    assert len(calls) == 1
    request = calls[0]
    assert request.method == "GET"
    assert request.url.path == f"/listings/{LISTINGS_API_VERSION}/items/{FAKE_SELLER_ID}"
    assert request.url.params.get("marketplaceIds") == FAKE_MARKETPLACE_ID
    assert request.url.params.get("pageSize") == "20"
    assert request.url.params.get("includedData") == "summaries"
    assert "pageToken" not in request.url.params


@pytest.mark.asyncio
async def test_seller_id_path_is_url_encoded(
    amazon_settings,
    async_refresh_resolver,
) -> None:
    encoded_seller = "FAKE/SELLER+ID"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_wire_page())

    client, calls = _make_listings_client(
        handler,
        amazon_settings=amazon_settings,
        async_refresh_resolver=async_refresh_resolver,
    )
    await client.search_listings_items(
        seller_id=encoded_seller,
        marketplace_id=FAKE_MARKETPLACE_ID,
        account_key="test-account",
    )
    request_url = str(calls[0].url)
    assert "/items/FAKE%2FSELLER%2BID" in request_url


@pytest.mark.asyncio
@pytest.mark.parametrize("page_size", [1, 20])
async def test_page_size_valid_values(
    page_size: int,
    amazon_settings,
    async_refresh_resolver,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_wire_page())

    client, calls = _make_listings_client(
        handler,
        amazon_settings=amazon_settings,
        async_refresh_resolver=async_refresh_resolver,
    )
    await client.search_listings_items(
        seller_id=FAKE_SELLER_ID,
        marketplace_id=FAKE_MARKETPLACE_ID,
        account_key="test-account",
        page_size=page_size,
    )
    assert calls[0].url.params.get("pageSize") == str(page_size)


@pytest.mark.asyncio
@pytest.mark.parametrize("page_size", [0, 21, True])
async def test_page_size_invalid_rejects_without_http(
    page_size: int,
    amazon_settings,
    async_refresh_resolver,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("HTTP must not be called")

    client, _calls = _make_listings_client(
        handler,
        amazon_settings=amazon_settings,
        async_refresh_resolver=async_refresh_resolver,
    )
    with pytest.raises(AmazonError) as exc_info:
        await client.search_listings_items(
            seller_id=FAKE_SELLER_ID,
            marketplace_id=FAKE_MARKETPLACE_ID,
            account_key="test-account",
            page_size=page_size,  # type: ignore[arg-type]
        )
    assert exc_info.value.error_code == AMAZON_CONFIG_INVALID


@pytest.mark.asyncio
async def test_page_token_sent_when_provided(
    amazon_settings,
    async_refresh_resolver,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_wire_page())

    client, calls = _make_listings_client(
        handler,
        amazon_settings=amazon_settings,
        async_refresh_resolver=async_refresh_resolver,
    )
    await client.search_listings_items(
        seller_id=FAKE_SELLER_ID,
        marketplace_id=FAKE_MARKETPLACE_ID,
        account_key="test-account",
        page_token=FAKE_PAGE_TOKEN,
    )
    assert calls[0].url.params.get("pageToken") == FAKE_PAGE_TOKEN


@pytest.mark.asyncio
async def test_included_data_invalid_rejects_without_http(
    amazon_settings,
    async_refresh_resolver,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("HTTP must not be called")

    client, _calls = _make_listings_client(
        handler,
        amazon_settings=amazon_settings,
        async_refresh_resolver=async_refresh_resolver,
    )
    with pytest.raises(AmazonError) as exc_info:
        await client.search_listings_items(
            seller_id=FAKE_SELLER_ID,
            marketplace_id=FAKE_MARKETPLACE_ID,
            account_key="test-account",
            included_data=("summaries", "unsupported"),
        )
    assert exc_info.value.error_code == AMAZON_CONFIG_INVALID


@pytest.mark.asyncio
async def test_empty_seller_id_rejects_without_http(
    amazon_settings,
    async_refresh_resolver,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("HTTP must not be called")

    client, _calls = _make_listings_client(
        handler,
        amazon_settings=amazon_settings,
        async_refresh_resolver=async_refresh_resolver,
    )
    with pytest.raises(AmazonError) as exc_info:
        await client.search_listings_items(
            seller_id="   ",
            marketplace_id=FAKE_MARKETPLACE_ID,
            account_key="test-account",
        )
    assert exc_info.value.error_code == AMAZON_SELLING_PARTNER_ID_REQUIRED


@pytest.mark.asyncio
async def test_success_response_mapping_and_request_id(
    amazon_settings,
    async_refresh_resolver,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_wire_page(_wire_item(), next_token=FAKE_PAGE_TOKEN),
            headers={"x-amzn-requestid": "req-listings-123"},
        )

    client, _calls = _make_listings_client(
        handler,
        amazon_settings=amazon_settings,
        async_refresh_resolver=async_refresh_resolver,
    )
    page = await client.search_listings_items(
        seller_id=FAKE_SELLER_ID,
        marketplace_id=FAKE_MARKETPLACE_ID,
        account_key="test-account",
    )
    assert isinstance(page, SearchListingsItemsPage)
    assert isinstance(page.items[0], SearchListingsItem)
    assert page.next_page_token == FAKE_PAGE_TOKEN
    assert page.request_id == "req-listings-123"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "expected_code"),
    [
        (400, AMAZON_SP_API_CLIENT_ERROR),
        (401, AMAZON_SP_API_UNAUTHORIZED),
        (403, AMAZON_SP_API_FORBIDDEN),
        (429, AMAZON_SP_API_RATE_LIMITED),
        (500, AMAZON_SP_API_SERVER_ERROR),
        (503, AMAZON_SP_API_SERVER_ERROR),
    ],
)
async def test_http_errors_keep_existing_codes(
    status_code: int,
    expected_code: str,
    amazon_settings,
    async_refresh_resolver,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json={"errors": []}, headers={"x-amzn-requestid": "rid-2"})

    client, _calls = _make_listings_client(
        handler,
        amazon_settings=amazon_settings,
        async_refresh_resolver=async_refresh_resolver,
    )
    with pytest.raises(AmazonError) as exc_info:
        await client.search_listings_items(
            seller_id=FAKE_SELLER_ID,
            marketplace_id=FAKE_MARKETPLACE_ID,
            account_key="test-account",
        )
    assert exc_info.value.error_code == expected_code


@pytest.mark.asyncio
async def test_invalid_json_response(
    amazon_settings,
    async_refresh_resolver,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"{not-json " + CANARY.encode() + b"}",
            headers={"content-type": "application/json", "x-amzn-requestid": "rid-1"},
        )

    client, _calls = _make_listings_client(
        handler,
        amazon_settings=amazon_settings,
        async_refresh_resolver=async_refresh_resolver,
    )
    with caplog.at_level("WARNING"):
        with pytest.raises(AmazonError) as exc_info:
            await client.search_listings_items(
                seller_id=FAKE_SELLER_ID,
                marketplace_id=FAKE_MARKETPLACE_ID,
                account_key="test-account",
            )
    assert exc_info.value.error_code == AMAZON_RESPONSE_INVALID
    _assert_no_sensitive_leaks(" ".join(record.message for record in caplog.records))


@pytest.mark.asyncio
async def test_schema_invalid_200_response(
    amazon_settings,
    async_refresh_resolver,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"items": "bad"})

    client, _calls = _make_listings_client(
        handler,
        amazon_settings=amazon_settings,
        async_refresh_resolver=async_refresh_resolver,
    )
    with pytest.raises(AmazonError) as exc_info:
        await client.search_listings_items(
            seller_id=FAKE_SELLER_ID,
            marketplace_id=FAKE_MARKETPLACE_ID,
            account_key="test-account",
        )
    assert exc_info.value.error_code == AMAZON_RESPONSE_INVALID


@pytest.mark.asyncio
async def test_transport_timeout_maps_to_transport_error(
    amazon_settings,
    async_refresh_resolver,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "mock.lwa.local" in str(request.url):
            return lwa_success_handler()(request)
        raise httpx.TimeoutException("timeout")

    client, _calls = _make_listings_client(
        handler,
        amazon_settings=amazon_settings,
        async_refresh_resolver=async_refresh_resolver,
    )
    with pytest.raises(AmazonError) as exc_info:
        await client.search_listings_items(
            seller_id=FAKE_SELLER_ID,
            marketplace_id=FAKE_MARKETPLACE_ID,
            account_key="test-account",
        )
    assert exc_info.value.error_code == AMAZON_SP_API_TRANSPORT_ERROR


@pytest.mark.asyncio
async def test_page_token_not_in_exception_or_repr(
    amazon_settings,
    async_refresh_resolver,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"errors": []}, headers={"x-amzn-requestid": "rid-403"})

    client, _calls = _make_listings_client(
        handler,
        amazon_settings=amazon_settings,
        async_refresh_resolver=async_refresh_resolver,
    )
    with pytest.raises(AmazonError) as exc_info:
        await client.search_listings_items(
            seller_id=FAKE_SELLER_ID,
            marketplace_id=FAKE_MARKETPLACE_ID,
            account_key="test-account",
            page_token=FAKE_PAGE_TOKEN,
        )
    _assert_no_sensitive_leaks(str(exc_info.value))
    _assert_no_sensitive_leaks(repr(exc_info.value))
    page = map_search_listings_items_page(
        _wire_page(next_token=FAKE_PAGE_TOKEN),
        marketplace_id=FAKE_MARKETPLACE_ID,
    )
    _assert_no_sensitive_leaks(repr(page))


@pytest.mark.parametrize(
    "marketplace_id",
    [
        pytest.param(123, id="non_string"),
        pytest.param("", id="empty_string"),
        pytest.param("   ", id="whitespace_only"),
        pytest.param("A" * (MARKETPLACE_ID_MAX_LENGTH + 1), id="too_long"),
    ],
)
def test_mapper_rejects_invalid_marketplace_id_param(marketplace_id: object) -> None:
    with pytest.raises(AmazonError) as exc_info:
        map_search_listings_items_page(_wire_page(_wire_item()), marketplace_id=marketplace_id)  # type: ignore[arg-type]
    assert exc_info.value.error_code == AMAZON_RESPONSE_INVALID
    assert exc_info.value.__cause__ is None
    _assert_no_sensitive_leaks(str(exc_info.value))


def test_map_duplicate_matching_summaries_rejected() -> None:
    payload = _wire_page(
        _wire_item(
            summaries=[
                _wire_summary(),
                _wire_summary(),
            ],
        ),
    )
    with pytest.raises(AmazonError) as exc_info:
        map_search_listings_items_page(payload, marketplace_id=FAKE_MARKETPLACE_ID)
    assert exc_info.value.error_code == AMAZON_RESPONSE_INVALID
    _assert_no_sensitive_leaks(str(exc_info.value))
    _assert_no_sensitive_leaks(repr(exc_info.value))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "marketplace_id",
    [
        pytest.param(123, id="non_string"),
        pytest.param("", id="empty_string"),
        pytest.param("   ", id="whitespace_only"),
        pytest.param("A" * (MARKETPLACE_ID_MAX_LENGTH + 1), id="too_long"),
    ],
)
async def test_client_rejects_invalid_marketplace_id_without_http(
    marketplace_id: object,
    amazon_settings,
    async_refresh_resolver,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("HTTP must not be called")

    client, _calls = _make_listings_client(
        handler,
        amazon_settings=amazon_settings,
        async_refresh_resolver=async_refresh_resolver,
    )
    with pytest.raises(AmazonError) as exc_info:
        await client.search_listings_items(
            seller_id=FAKE_SELLER_ID,
            marketplace_id=marketplace_id,  # type: ignore[arg-type]
            account_key="test-account",
        )
    assert exc_info.value.error_code == AMAZON_CONFIG_INVALID


@pytest.mark.asyncio
async def test_client_strips_marketplace_id_before_request(
    amazon_settings,
    async_refresh_resolver,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_wire_page(_wire_item()))

    client, calls = _make_listings_client(
        handler,
        amazon_settings=amazon_settings,
        async_refresh_resolver=async_refresh_resolver,
    )
    await client.search_listings_items(
        seller_id=FAKE_SELLER_ID,
        marketplace_id=f"  {FAKE_MARKETPLACE_ID}  ",
        account_key="test-account",
    )
    assert calls[0].url.params.get("marketplaceIds") == FAKE_MARKETPLACE_ID
