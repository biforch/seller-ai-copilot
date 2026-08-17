"""Amazon SP-API integration exceptions."""

from __future__ import annotations

import re

AMAZON_DISABLED = "AMAZON_DISABLED"
AMAZON_CONFIG_INVALID = "AMAZON_CONFIG_INVALID"
AMAZON_LWA_TOKEN_INVALID = "AMAZON_LWA_TOKEN_INVALID"
AMAZON_LWA_RATE_LIMITED = "AMAZON_LWA_RATE_LIMITED"
AMAZON_LWA_UNAVAILABLE = "AMAZON_LWA_UNAVAILABLE"
AMAZON_SP_API_UNAUTHORIZED = "AMAZON_SP_API_UNAUTHORIZED"
AMAZON_SP_API_FORBIDDEN = "AMAZON_SP_API_FORBIDDEN"
AMAZON_SP_API_RATE_LIMITED = "AMAZON_SP_API_RATE_LIMITED"
AMAZON_SP_API_CLIENT_ERROR = "AMAZON_SP_API_CLIENT_ERROR"
AMAZON_SP_API_SERVER_ERROR = "AMAZON_SP_API_SERVER_ERROR"
AMAZON_SP_API_TRANSPORT_ERROR = "AMAZON_SP_API_TRANSPORT_ERROR"
AMAZON_RESPONSE_INVALID = "AMAZON_RESPONSE_INVALID"
AMAZON_RESPONSE_TOO_LARGE = "AMAZON_RESPONSE_TOO_LARGE"
AMAZON_TOKEN_DECRYPTION_FAILED = "AMAZON_TOKEN_DECRYPTION_FAILED"
AMAZON_ACCOUNT_NOT_FOUND = "AMAZON_ACCOUNT_NOT_FOUND"
AMAZON_ACCOUNT_ALREADY_EXISTS = "AMAZON_ACCOUNT_ALREADY_EXISTS"
AMAZON_ACCOUNT_DISABLED = "AMAZON_ACCOUNT_DISABLED"
AMAZON_SYNC_IN_PROGRESS = "AMAZON_SYNC_IN_PROGRESS"
AMAZON_SYNC_LEASE_LOST = "AMAZON_SYNC_LEASE_LOST"
AMAZON_SYNC_LEASE_EXPIRED = "AMAZON_SYNC_LEASE_EXPIRED"
AMAZON_SYNC_FINALIZE_FAILED = "AMAZON_SYNC_FINALIZE_FAILED"
AMAZON_SAFE_DETAIL_INVALID = "AMAZON_SAFE_DETAIL_INVALID"
AMAZON_SELLING_PARTNER_ID_REQUIRED = "AMAZON_SELLING_PARTNER_ID_REQUIRED"
AMAZON_ACCOUNT_NOT_ACTIVE = "AMAZON_ACCOUNT_NOT_ACTIVE"
AMAZON_MARKETPLACE_NOT_FOUND = "AMAZON_MARKETPLACE_NOT_FOUND"
AMAZON_MARKETPLACE_INACTIVE = "AMAZON_MARKETPLACE_INACTIVE"
AMAZON_MARKETPLACE_NOT_ELIGIBLE = "AMAZON_MARKETPLACE_NOT_ELIGIBLE"
AMAZON_LISTING_NOT_FOUND = "AMAZON_LISTING_NOT_FOUND"
AMAZON_PRODUCT_NOT_FOUND = "AMAZON_PRODUCT_NOT_FOUND"
AMAZON_CATALOG_ASIN_REQUIRED = "AMAZON_CATALOG_ASIN_REQUIRED"
AMAZON_CATALOG_IDENTITY_CHANGED = "AMAZON_CATALOG_IDENTITY_CHANGED"
AMAZON_CATALOG_PERSIST_FAILED = "AMAZON_CATALOG_PERSIST_FAILED"
AMAZON_CATALOG_FETCH_FAILED = "AMAZON_CATALOG_FETCH_FAILED"
AMAZON_SYNC_PAGINATION_LIMIT = "AMAZON_SYNC_PAGINATION_LIMIT"
AMAZON_SYNC_PAGINATION_LOOP = "AMAZON_SYNC_PAGINATION_LOOP"
AMAZON_OAUTH_DISABLED = "AMAZON_OAUTH_DISABLED"
AMAZON_OAUTH_STATE_INVALID = "AMAZON_OAUTH_STATE_INVALID"
AMAZON_OAUTH_STATE_EXPIRED = "AMAZON_OAUTH_STATE_EXPIRED"
AMAZON_OAUTH_STATE_REPLAY = "AMAZON_OAUTH_STATE_REPLAY"
AMAZON_OAUTH_REDIRECT_INVALID = "AMAZON_OAUTH_REDIRECT_INVALID"
AMAZON_OAUTH_MARKETPLACE_INVALID = "AMAZON_OAUTH_MARKETPLACE_INVALID"
AMAZON_OAUTH_SELLER_INVALID = "AMAZON_OAUTH_SELLER_INVALID"
AMAZON_OAUTH_SELLER_MISMATCH = "AMAZON_OAUTH_SELLER_MISMATCH"
AMAZON_OAUTH_SELLER_ALREADY_LINKED = "AMAZON_OAUTH_SELLER_ALREADY_LINKED"
AMAZON_OAUTH_TOKEN_EXCHANGE_FAILED = "AMAZON_OAUTH_TOKEN_EXCHANGE_FAILED"
AMAZON_OAUTH_USER_NOT_FOUND = "AMAZON_OAUTH_USER_NOT_FOUND"
AMAZON_OAUTH_ACCOUNT_PERSIST_FAILED = "AMAZON_OAUTH_ACCOUNT_PERSIST_FAILED"
AMAZON_OAUTH_INTENT_INVALID = "AMAZON_OAUTH_INTENT_INVALID"

ERROR_BODY_MAX_LEN = 500

_SAFE_ERROR_CODE_PATTERN = re.compile(r"^[A-Z0-9_]{1,64}$")

KNOWN_AMAZON_ERROR_CODES = frozenset(
    {
        AMAZON_DISABLED,
        AMAZON_CONFIG_INVALID,
        AMAZON_LWA_TOKEN_INVALID,
        AMAZON_LWA_RATE_LIMITED,
        AMAZON_LWA_UNAVAILABLE,
        AMAZON_SP_API_UNAUTHORIZED,
        AMAZON_SP_API_FORBIDDEN,
        AMAZON_SP_API_RATE_LIMITED,
        AMAZON_SP_API_CLIENT_ERROR,
        AMAZON_SP_API_SERVER_ERROR,
        AMAZON_SP_API_TRANSPORT_ERROR,
        AMAZON_RESPONSE_INVALID,
        AMAZON_RESPONSE_TOO_LARGE,
        AMAZON_TOKEN_DECRYPTION_FAILED,
        AMAZON_ACCOUNT_NOT_FOUND,
        AMAZON_ACCOUNT_ALREADY_EXISTS,
        AMAZON_ACCOUNT_DISABLED,
        AMAZON_SYNC_IN_PROGRESS,
        AMAZON_SYNC_LEASE_LOST,
        AMAZON_SYNC_LEASE_EXPIRED,
        AMAZON_SYNC_FINALIZE_FAILED,
        AMAZON_SAFE_DETAIL_INVALID,
        AMAZON_SELLING_PARTNER_ID_REQUIRED,
        AMAZON_ACCOUNT_NOT_ACTIVE,
        AMAZON_MARKETPLACE_NOT_FOUND,
        AMAZON_MARKETPLACE_INACTIVE,
        AMAZON_MARKETPLACE_NOT_ELIGIBLE,
        AMAZON_LISTING_NOT_FOUND,
        AMAZON_PRODUCT_NOT_FOUND,
        AMAZON_CATALOG_ASIN_REQUIRED,
        AMAZON_CATALOG_IDENTITY_CHANGED,
        AMAZON_CATALOG_PERSIST_FAILED,
        AMAZON_CATALOG_FETCH_FAILED,
        AMAZON_SYNC_PAGINATION_LIMIT,
        AMAZON_SYNC_PAGINATION_LOOP,
        AMAZON_OAUTH_DISABLED,
        AMAZON_OAUTH_STATE_INVALID,
        AMAZON_OAUTH_STATE_EXPIRED,
        AMAZON_OAUTH_STATE_REPLAY,
        AMAZON_OAUTH_REDIRECT_INVALID,
        AMAZON_OAUTH_MARKETPLACE_INVALID,
        AMAZON_OAUTH_SELLER_INVALID,
        AMAZON_OAUTH_SELLER_MISMATCH,
        AMAZON_OAUTH_SELLER_ALREADY_LINKED,
        AMAZON_OAUTH_TOKEN_EXCHANGE_FAILED,
        AMAZON_OAUTH_USER_NOT_FOUND,
        AMAZON_OAUTH_ACCOUNT_PERSIST_FAILED,
        AMAZON_OAUTH_INTENT_INVALID,
    }
)


def is_safe_amazon_error_code_token(error_code: str) -> bool:
    return bool(_SAFE_ERROR_CODE_PATTERN.fullmatch(error_code))


def sanitize_public_amazon_error_code(error_code: str) -> str:
    if is_safe_amazon_error_code_token(error_code) and error_code in KNOWN_AMAZON_ERROR_CODES:
        return error_code
    return AMAZON_CONFIG_INVALID


def sanitize_callback_redirect_error_code(error_code: str) -> str:
    if is_safe_amazon_error_code_token(error_code) and error_code in KNOWN_AMAZON_ERROR_CODES:
        return error_code
    return AMAZON_OAUTH_REDIRECT_INVALID


class AmazonError(Exception):
    """Base exception for Amazon integration failures."""

    def __init__(
        self,
        message: str,
        *,
        error_code: str,
        status_code: int | None = None,
        request_id: str | None = None,
        cause: Exception | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.status_code = status_code
        self.request_id = request_id
        self.cause = cause


def amazon_disabled_error() -> AmazonError:
    return AmazonError(
        "Amazon SP-API integration is disabled",
        error_code=AMAZON_DISABLED,
    )


def amazon_config_invalid_error(message: str) -> AmazonError:
    return AmazonError(message, error_code=AMAZON_CONFIG_INVALID)


def amazon_response_invalid_error(*, cause: Exception | None = None) -> AmazonError:
    return AmazonError(
        "Amazon integration response was invalid",
        error_code=AMAZON_RESPONSE_INVALID,
        cause=cause,
    )


def amazon_response_too_large_error() -> AmazonError:
    return AmazonError(
        "Amazon integration response exceeded size limit",
        error_code=AMAZON_RESPONSE_TOO_LARGE,
    )


def amazon_token_decryption_failed_error() -> AmazonError:
    return AmazonError(
        "Amazon refresh token could not be decrypted",
        error_code=AMAZON_TOKEN_DECRYPTION_FAILED,
    )


def amazon_account_not_found_error() -> AmazonError:
    return AmazonError(
        "Amazon account was not found",
        error_code=AMAZON_ACCOUNT_NOT_FOUND,
        status_code=404,
    )


def amazon_account_already_exists_error() -> AmazonError:
    return AmazonError(
        "Amazon account already exists for this refresh token",
        error_code=AMAZON_ACCOUNT_ALREADY_EXISTS,
        status_code=409,
    )


def amazon_account_disabled_error() -> AmazonError:
    return AmazonError(
        "Amazon account is disabled",
        error_code=AMAZON_ACCOUNT_DISABLED,
        status_code=403,
    )


def amazon_sync_in_progress_error() -> AmazonError:
    return AmazonError(
        "Amazon account sync is already in progress",
        error_code=AMAZON_SYNC_IN_PROGRESS,
        status_code=409,
    )


def amazon_sync_lease_lost_error() -> AmazonError:
    return AmazonError(
        "Amazon sync lease was lost",
        error_code=AMAZON_SYNC_LEASE_LOST,
        status_code=409,
    )


def amazon_sync_finalize_failed_error() -> AmazonError:
    return AmazonError(
        "Amazon sync finalize failed",
        error_code=AMAZON_SYNC_FINALIZE_FAILED,
        status_code=500,
    )


def amazon_safe_detail_invalid_error() -> AmazonError:
    return AmazonError(
        "Amazon sync safe detail is invalid",
        error_code=AMAZON_SAFE_DETAIL_INVALID,
        status_code=400,
    )


def amazon_selling_partner_id_required_error() -> AmazonError:
    return AmazonError(
        "Amazon selling partner id is required",
        error_code=AMAZON_SELLING_PARTNER_ID_REQUIRED,
    )


def amazon_account_not_active_error() -> AmazonError:
    return AmazonError(
        "Amazon account is not active for sync",
        error_code=AMAZON_ACCOUNT_NOT_ACTIVE,
        status_code=403,
    )


def amazon_marketplace_not_found_error() -> AmazonError:
    return AmazonError(
        "Amazon marketplace participation was not found",
        error_code=AMAZON_MARKETPLACE_NOT_FOUND,
        status_code=404,
    )


def amazon_marketplace_inactive_error() -> AmazonError:
    return AmazonError(
        "Amazon marketplace participation is inactive",
        error_code=AMAZON_MARKETPLACE_INACTIVE,
        status_code=409,
    )


def amazon_marketplace_not_eligible_error() -> AmazonError:
    return AmazonError(
        "Amazon marketplace participation is not eligible for sync",
        error_code=AMAZON_MARKETPLACE_NOT_ELIGIBLE,
        status_code=409,
    )


def amazon_listing_not_found_error() -> AmazonError:
    return AmazonError(
        "Amazon listing was not found",
        error_code=AMAZON_LISTING_NOT_FOUND,
        status_code=404,
    )


def amazon_product_not_found_error() -> AmazonError:
    return AmazonError(
        "Product was not found",
        error_code=AMAZON_PRODUCT_NOT_FOUND,
        status_code=404,
    )


def amazon_catalog_asin_required_error() -> AmazonError:
    return AmazonError(
        "Amazon listing ASIN is required for catalog enrichment",
        error_code=AMAZON_CATALOG_ASIN_REQUIRED,
        status_code=422,
    )


def amazon_catalog_identity_changed_error() -> AmazonError:
    return AmazonError(
        "Amazon listing identity changed during catalog enrichment",
        error_code=AMAZON_CATALOG_IDENTITY_CHANGED,
        status_code=409,
    )


def amazon_catalog_persist_failed_error() -> AmazonError:
    return AmazonError(
        "Amazon catalog enrichment could not be saved",
        error_code=AMAZON_CATALOG_PERSIST_FAILED,
        status_code=500,
    )


def amazon_catalog_fetch_failed_error() -> AmazonError:
    return AmazonError(
        "Amazon catalog enrichment request failed",
        error_code=AMAZON_CATALOG_FETCH_FAILED,
        status_code=502,
    )


def amazon_sync_pagination_limit_error() -> AmazonError:
    return AmazonError(
        "Amazon sync pagination limit exceeded",
        error_code=AMAZON_SYNC_PAGINATION_LIMIT,
        status_code=422,
    )


def amazon_sync_pagination_loop_error() -> AmazonError:
    return AmazonError(
        "Amazon sync pagination loop detected",
        error_code=AMAZON_SYNC_PAGINATION_LOOP,
        status_code=502,
    )


def amazon_oauth_disabled_error() -> AmazonError:
    return AmazonError(
        "Amazon OAuth integration is disabled",
        error_code=AMAZON_OAUTH_DISABLED,
        status_code=503,
    )


def amazon_oauth_state_invalid_error() -> AmazonError:
    return AmazonError(
        "Amazon OAuth state is invalid",
        error_code=AMAZON_OAUTH_STATE_INVALID,
        status_code=400,
    )


def amazon_oauth_state_expired_error() -> AmazonError:
    return AmazonError(
        "Amazon OAuth state has expired",
        error_code=AMAZON_OAUTH_STATE_EXPIRED,
        status_code=400,
    )


def amazon_oauth_state_replay_error() -> AmazonError:
    return AmazonError(
        "Amazon OAuth state was already used",
        error_code=AMAZON_OAUTH_STATE_REPLAY,
        status_code=409,
    )


def amazon_oauth_redirect_invalid_error() -> AmazonError:
    return AmazonError(
        "Amazon OAuth redirect URI is invalid",
        error_code=AMAZON_OAUTH_REDIRECT_INVALID,
        status_code=400,
    )


def amazon_oauth_marketplace_invalid_error() -> AmazonError:
    return AmazonError(
        "Amazon OAuth marketplace is invalid",
        error_code=AMAZON_OAUTH_MARKETPLACE_INVALID,
        status_code=400,
    )


def amazon_oauth_seller_invalid_error() -> AmazonError:
    return AmazonError(
        "Amazon OAuth seller identifier is invalid",
        error_code=AMAZON_OAUTH_SELLER_INVALID,
        status_code=400,
    )


def amazon_oauth_seller_mismatch_error() -> AmazonError:
    return AmazonError(
        "Amazon OAuth seller does not match the account",
        error_code=AMAZON_OAUTH_SELLER_MISMATCH,
        status_code=409,
    )


def amazon_oauth_seller_already_linked_error() -> AmazonError:
    return AmazonError(
        "Amazon OAuth seller is already linked",
        error_code=AMAZON_OAUTH_SELLER_ALREADY_LINKED,
        status_code=409,
    )


def amazon_oauth_token_exchange_failed_error() -> AmazonError:
    return AmazonError(
        "Amazon OAuth token exchange failed",
        error_code=AMAZON_OAUTH_TOKEN_EXCHANGE_FAILED,
        status_code=502,
    )


def amazon_oauth_user_not_found_error() -> AmazonError:
    return AmazonError(
        "Amazon OAuth user was not found",
        error_code=AMAZON_OAUTH_USER_NOT_FOUND,
        status_code=401,
    )


def amazon_oauth_account_persist_failed_error() -> AmazonError:
    return AmazonError(
        "Amazon OAuth account persistence failed",
        error_code=AMAZON_OAUTH_ACCOUNT_PERSIST_FAILED,
        status_code=500,
    )


def amazon_oauth_intent_invalid_error() -> AmazonError:
    return AmazonError(
        "Amazon OAuth intent is invalid",
        error_code=AMAZON_OAUTH_INTENT_INVALID,
        status_code=400,
    )


def lwa_error_from_status(status_code: int) -> AmazonError:
    if status_code == 429:
        return AmazonError(
            "Login with Amazon rate limit exceeded",
            error_code=AMAZON_LWA_RATE_LIMITED,
            status_code=status_code,
        )
    if status_code >= 500:
        return AmazonError(
            "Login with Amazon token service is unavailable",
            error_code=AMAZON_LWA_UNAVAILABLE,
            status_code=status_code,
        )
    return AmazonError(
        "Login with Amazon token exchange failed",
        error_code=AMAZON_LWA_TOKEN_INVALID,
        status_code=status_code,
    )


def lwa_unavailable_error(*, cause: Exception | None = None) -> AmazonError:
    return AmazonError(
        "Login with Amazon token service is unavailable",
        error_code=AMAZON_LWA_UNAVAILABLE,
        cause=cause,
    )


def sp_api_error_from_status(
    status_code: int,
    *,
    request_id: str | None = None,
) -> AmazonError:
    if status_code == 401:
        error_code = AMAZON_SP_API_UNAUTHORIZED
        message = "Amazon SP-API request was unauthorized"
    elif status_code == 403:
        error_code = AMAZON_SP_API_FORBIDDEN
        message = "Amazon SP-API request was forbidden"
    elif status_code == 429:
        error_code = AMAZON_SP_API_RATE_LIMITED
        message = "Amazon SP-API rate limit exceeded"
    elif 400 <= status_code < 500:
        error_code = AMAZON_SP_API_CLIENT_ERROR
        message = "Amazon SP-API client error"
    elif status_code >= 500:
        error_code = AMAZON_SP_API_SERVER_ERROR
        message = "Amazon SP-API server error"
    else:
        error_code = AMAZON_SP_API_CLIENT_ERROR
        message = "Amazon SP-API request failed"

    return AmazonError(
        message,
        error_code=error_code,
        status_code=status_code,
        request_id=request_id,
    )


def sp_api_transport_error(*, cause: Exception) -> AmazonError:
    return AmazonError(
        "Amazon SP-API transport error",
        error_code=AMAZON_SP_API_TRANSPORT_ERROR,
        cause=cause,
    )
