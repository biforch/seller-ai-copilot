from __future__ import annotations

from dataclasses import FrozenInstanceError
from typing import Any

import httpx
import pytest

from app.integrations.amazon.catalog_items import (
    CATALOG_API_VERSION,
    CatalogItemsClient,
    CatalogItemSummary,
)
from app.integrations.amazon.client import SpApiClient
from app.integrations.amazon.exceptions import (
    AMAZON_CONFIG_INVALID,
    AMAZON_RESPONSE_INVALID,
    AMAZON_SP_API_FORBIDDEN,
    AMAZON_SP_API_RATE_LIMITED,
    AMAZON_SP_API_SERVER_ERROR,
    AmazonError,
)
from app.integrations.amazon.lwa import CachingRefreshTokenProvider, LwaTokenClient
from app.integrations.amazon.token_cache import InMemoryTokenCache
from tests.integrations.amazon.conftest import (
    TEST_ACCESS_TOKEN,
    TEST_REFRESH_TOKEN,
    lwa_success_handler,
    make_transport,
)

ASIN = "B012345678"
MARKETPLACE_ID = "ATVPDKIKX0DER"
CANARY = "CATALOG_SECRET_CANARY_XYZ"


def _payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "asin": ASIN,
        "summaries": [
            {
                "marketplaceId": MARKETPLACE_ID,
                "itemName": "Safe product name",
                "brand": "Safe brand",
                "manufacturer": "Safe manufacturer",
                "color": "Blue",
                "size": "Medium",
                "style": "Modern",
                "modelNumber": "MODEL-1",
                "partNumber": "PART-1",
            }
        ],
        "productTypes": [
            {"marketplaceId": MARKETPLACE_ID, "productType": "PRODUCT"}
        ],
    }
    payload.update(overrides)
    return payload


def _make_client(handler, *, amazon_settings, async_refresh_resolver):
    calls: list[httpx.Request] = []

    def combined(request: httpx.Request) -> httpx.Response:
        if "mock.lwa.local" in str(request.url):
            return lwa_success_handler()(request)
        calls.append(request)
        return handler(request)

    transport = make_transport(combined)
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
    return CatalogItemsClient(sp_client), calls


@pytest.mark.asyncio
async def test_get_catalog_item_contract_and_mapping(
    amazon_settings, async_refresh_resolver
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_payload(extraFutureField=CANARY),
            headers={"x-amzn-requestid": "catalog-request-1"},
        )

    client, calls = _make_client(
        handler,
        amazon_settings=amazon_settings,
        async_refresh_resolver=async_refresh_resolver,
    )
    item = await client.get_catalog_item(
        asin=ASIN,
        marketplace_id=MARKETPLACE_ID,
        account_key="account-key",
    )
    assert item == CatalogItemSummary(
        asin=ASIN,
        marketplace_id=MARKETPLACE_ID,
        item_name="Safe product name",
        brand="Safe brand",
        manufacturer="Safe manufacturer",
        color="Blue",
        size="Medium",
        style="Modern",
        model_number="MODEL-1",
        part_number="PART-1",
        product_type="PRODUCT",
        request_id="catalog-request-1",
    )
    assert len(calls) == 1
    request = calls[0]
    assert request.method == "GET"
    assert request.url.path == f"/catalog/{CATALOG_API_VERSION}/items/{ASIN}"
    assert request.url.params["marketplaceIds"] == MARKETPLACE_ID
    assert request.url.params["includedData"] == "productTypes,summaries"
    assert CANARY not in repr(item)


def test_domain_object_is_immutable_and_has_no_raw_payload() -> None:
    item = CatalogItemSummary(
        asin=ASIN,
        marketplace_id=MARKETPLACE_ID,
        item_name=None,
        brand=None,
        manufacturer=None,
        color=None,
        size=None,
        style=None,
        model_number=None,
        part_number=None,
        product_type=None,
    )
    with pytest.raises(FrozenInstanceError):
        item.item_name = "changed"  # type: ignore[misc]
    assert not hasattr(item, "payload")
    assert not hasattr(item, "attributes")


@pytest.mark.asyncio
@pytest.mark.parametrize("asin", ["", "   ", "lowercase1", "B01234567!", "B0123456789"])
async def test_invalid_asin_rejected_without_http(
    asin, amazon_settings, async_refresh_resolver
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("HTTP must not be called")

    client, calls = _make_client(
        handler,
        amazon_settings=amazon_settings,
        async_refresh_resolver=async_refresh_resolver,
    )
    with pytest.raises(AmazonError) as exc_info:
        await client.get_catalog_item(
            asin=asin,
            marketplace_id=MARKETPLACE_ID,
            account_key="account-key",
        )
    assert exc_info.value.error_code == AMAZON_CONFIG_INVALID
    assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "included_data",
    [(), ("attributes",), ("productTypes",), ("summaries", "vendorDetails")],
)
async def test_unsupported_included_data_rejected_without_http(
    included_data, amazon_settings, async_refresh_resolver
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("HTTP must not be called")

    client, calls = _make_client(
        handler,
        amazon_settings=amazon_settings,
        async_refresh_resolver=async_refresh_resolver,
    )
    with pytest.raises(AmazonError) as exc_info:
        await client.get_catalog_item(
            asin=ASIN,
            marketplace_id=MARKETPLACE_ID,
            account_key="account-key",
            included_data=included_data,
        )
    assert exc_info.value.error_code == AMAZON_CONFIG_INVALID
    assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {"asin": ASIN, "summaries": []},
        _payload(asin="B000000000"),
        _payload(summaries=[{"marketplaceId": "OTHER", "itemName": "Wrong"}]),
        _payload(
            summaries=[
                {"marketplaceId": MARKETPLACE_ID},
                {"marketplaceId": MARKETPLACE_ID},
            ]
        ),
        _payload(summaries=[{"marketplaceId": MARKETPLACE_ID, "itemName": "bad\nname"}]),
        _payload(
            productTypes=[
                {"marketplaceId": MARKETPLACE_ID, "productType": "A"},
                {"marketplaceId": MARKETPLACE_ID, "productType": "B"},
            ]
        ),
    ],
)
async def test_invalid_response_is_fail_closed(
    payload, amazon_settings, async_refresh_resolver, caplog
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    client, _calls = _make_client(
        handler,
        amazon_settings=amazon_settings,
        async_refresh_resolver=async_refresh_resolver,
    )
    with caplog.at_level("WARNING"):
        with pytest.raises(AmazonError) as exc_info:
            await client.get_catalog_item(
                asin=ASIN,
                marketplace_id=MARKETPLACE_ID,
                account_key="account-key",
            )
    assert exc_info.value.error_code == AMAZON_RESPONSE_INVALID
    logs = " ".join(record.message for record in caplog.records)
    assert CANARY not in logs
    assert TEST_ACCESS_TOKEN not in logs
    assert TEST_REFRESH_TOKEN not in logs


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "error_code"),
    [
        (403, AMAZON_SP_API_FORBIDDEN),
        (429, AMAZON_SP_API_RATE_LIMITED),
        (503, AMAZON_SP_API_SERVER_ERROR),
    ],
)
async def test_http_error_mapping_is_inherited(
    status_code, error_code, amazon_settings, async_refresh_resolver
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json={"errors": []})

    client, _calls = _make_client(
        handler,
        amazon_settings=amazon_settings,
        async_refresh_resolver=async_refresh_resolver,
    )
    with pytest.raises(AmazonError) as exc_info:
        await client.get_catalog_item(
            asin=ASIN,
            marketplace_id=MARKETPLACE_ID,
            account_key="account-key",
        )
    assert exc_info.value.error_code == error_code


@pytest.mark.asyncio
async def test_request_id_with_control_character_is_dropped(
    amazon_settings, async_refresh_resolver
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_payload(),
            headers={"x-amzn-requestid": "unsafe\x7frequest"},
        )

    client, _calls = _make_client(
        handler,
        amazon_settings=amazon_settings,
        async_refresh_resolver=async_refresh_resolver,
    )
    item = await client.get_catalog_item(
        asin=ASIN,
        marketplace_id=MARKETPLACE_ID,
        account_key="account-key",
    )
    assert item.request_id is None
