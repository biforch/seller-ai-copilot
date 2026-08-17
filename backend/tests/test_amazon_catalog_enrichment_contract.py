import pytest

from app.core.exceptions import (
    AMAZON_CATALOG_PUBLIC_MESSAGE,
    public_message_for_amazon_error_code,
)
from app.integrations.amazon.exceptions import (
    AMAZON_CATALOG_ASIN_REQUIRED,
    AMAZON_CATALOG_FETCH_FAILED,
    AMAZON_CATALOG_IDENTITY_CHANGED,
    AMAZON_CATALOG_PERSIST_FAILED,
    KNOWN_AMAZON_ERROR_CODES,
    amazon_catalog_asin_required_error,
    amazon_catalog_fetch_failed_error,
    amazon_catalog_identity_changed_error,
    amazon_catalog_persist_failed_error,
)


@pytest.mark.parametrize(
    ("factory", "error_code", "status_code"),
    [
        (amazon_catalog_asin_required_error, AMAZON_CATALOG_ASIN_REQUIRED, 422),
        (amazon_catalog_identity_changed_error, AMAZON_CATALOG_IDENTITY_CHANGED, 409),
        (amazon_catalog_fetch_failed_error, AMAZON_CATALOG_FETCH_FAILED, 502),
        (amazon_catalog_persist_failed_error, AMAZON_CATALOG_PERSIST_FAILED, 500),
    ],
)
def test_catalog_errors_have_stable_public_contract(factory, error_code, status_code) -> None:
    error = factory()
    assert error.error_code == error_code
    assert error.status_code == status_code
    assert error_code in KNOWN_AMAZON_ERROR_CODES
    assert public_message_for_amazon_error_code(error_code) == AMAZON_CATALOG_PUBLIC_MESSAGE
