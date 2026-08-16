"""A4.2 product sync error and safe_detail contract unit tests."""

from __future__ import annotations

import pytest

from app.integrations.amazon.exceptions import (
    AMAZON_ACCOUNT_NOT_ACTIVE,
    AMAZON_MARKETPLACE_INACTIVE,
    AMAZON_MARKETPLACE_NOT_ELIGIBLE,
    AMAZON_MARKETPLACE_NOT_FOUND,
    AMAZON_SYNC_PAGINATION_LIMIT,
    AMAZON_SYNC_PAGINATION_LOOP,
    AmazonError,
    amazon_account_not_active_error,
    amazon_marketplace_inactive_error,
    amazon_marketplace_not_eligible_error,
    amazon_marketplace_not_found_error,
    amazon_sync_pagination_limit_error,
    amazon_sync_pagination_loop_error,
)

CANARY = "CANARY_SECRET_PAYLOAD_MARKER_XYZ"


@pytest.mark.parametrize(
    ("factory", "expected_code", "expected_status"),
    [
        (amazon_account_not_active_error, AMAZON_ACCOUNT_NOT_ACTIVE, 403),
        (amazon_marketplace_not_found_error, AMAZON_MARKETPLACE_NOT_FOUND, 404),
        (amazon_marketplace_inactive_error, AMAZON_MARKETPLACE_INACTIVE, 409),
        (amazon_marketplace_not_eligible_error, AMAZON_MARKETPLACE_NOT_ELIGIBLE, 409),
        (amazon_sync_pagination_limit_error, AMAZON_SYNC_PAGINATION_LIMIT, 422),
        (amazon_sync_pagination_loop_error, AMAZON_SYNC_PAGINATION_LOOP, 502),
    ],
)
def test_product_sync_error_helpers(
    factory,
    expected_code: str,
    expected_status: int,
) -> None:
    exc = factory()
    assert isinstance(exc, AmazonError)
    assert exc.error_code == expected_code
    assert exc.status_code == expected_status
    assert CANARY not in exc.message
    assert CANARY not in str(exc)
    assert CANARY not in repr(exc)
