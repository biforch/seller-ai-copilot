import logging

from fastapi import Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import settings
from app.integrations.amazon.exceptions import (
    AMAZON_ACCOUNT_ALREADY_EXISTS,
    AMAZON_ACCOUNT_DISABLED,
    AMAZON_ACCOUNT_NOT_ACTIVE,
    AMAZON_ACCOUNT_NOT_FOUND,
    AMAZON_CATALOG_ASIN_REQUIRED,
    AMAZON_CATALOG_FETCH_FAILED,
    AMAZON_CATALOG_IDENTITY_CHANGED,
    AMAZON_CATALOG_PERSIST_FAILED,
    AMAZON_CONFIG_INVALID,
    AMAZON_DISABLED,
    AMAZON_LISTING_NOT_FOUND,
    AMAZON_LWA_RATE_LIMITED,
    AMAZON_LWA_TOKEN_INVALID,
    AMAZON_LWA_UNAVAILABLE,
    AMAZON_MARKETPLACE_INACTIVE,
    AMAZON_MARKETPLACE_NOT_ELIGIBLE,
    AMAZON_MARKETPLACE_NOT_FOUND,
    AMAZON_OAUTH_ACCOUNT_PERSIST_FAILED,
    AMAZON_OAUTH_DISABLED,
    AMAZON_OAUTH_INTENT_INVALID,
    AMAZON_OAUTH_MARKETPLACE_INVALID,
    AMAZON_OAUTH_REDIRECT_INVALID,
    AMAZON_OAUTH_SELLER_ALREADY_LINKED,
    AMAZON_OAUTH_SELLER_INVALID,
    AMAZON_OAUTH_SELLER_MISMATCH,
    AMAZON_OAUTH_STATE_EXPIRED,
    AMAZON_OAUTH_STATE_INVALID,
    AMAZON_OAUTH_STATE_REPLAY,
    AMAZON_OAUTH_TOKEN_EXCHANGE_FAILED,
    AMAZON_OAUTH_USER_NOT_FOUND,
    AMAZON_PRODUCT_NOT_FOUND,
    AMAZON_RESPONSE_INVALID,
    AMAZON_RESPONSE_TOO_LARGE,
    AMAZON_SAFE_DETAIL_INVALID,
    AMAZON_SELLING_PARTNER_ID_REQUIRED,
    AMAZON_SP_API_CLIENT_ERROR,
    AMAZON_SP_API_FORBIDDEN,
    AMAZON_SP_API_RATE_LIMITED,
    AMAZON_SP_API_SERVER_ERROR,
    AMAZON_SP_API_TRANSPORT_ERROR,
    AMAZON_SP_API_UNAUTHORIZED,
    AMAZON_SYNC_FINALIZE_FAILED,
    AMAZON_SYNC_IN_PROGRESS,
    AMAZON_SYNC_LEASE_EXPIRED,
    AMAZON_SYNC_LEASE_LOST,
    AMAZON_SYNC_PAGINATION_LIMIT,
    AMAZON_SYNC_PAGINATION_LOOP,
    AMAZON_TOKEN_DECRYPTION_FAILED,
    AmazonError,
    sanitize_public_amazon_error_code,
)
from app.schemas.common import ErrorResponse

logger = logging.getLogger(__name__)

AI_RESPONSE_INVALID = "AI_RESPONSE_INVALID"
AI_PROVIDER_UNAVAILABLE = "AI_PROVIDER_UNAVAILABLE"
IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
LISTING_DECISIONS_INCOMPLETE = "LISTING_DECISIONS_INCOMPLETE"
LISTING_NO_BASE_PARTIAL_ACCEPT_FORBIDDEN = "LISTING_NO_BASE_PARTIAL_ACCEPT_FORBIDDEN"
LISTING_PROPOSAL_NOT_REVIEWING = "LISTING_PROPOSAL_NOT_REVIEWING"
LISTING_PROPOSAL_REVISION_CONFLICT = "LISTING_PROPOSAL_REVISION_CONFLICT"
LISTING_PROPOSAL_STALE = "LISTING_PROPOSAL_STALE"
LISTING_NOT_FOUND = "LISTING_NOT_FOUND"
GENERATION_IN_PROGRESS = "GENERATION_IN_PROGRESS"
GENERATION_FINALIZE_FAILED = "GENERATION_FINALIZE_FAILED"
GENERATION_UNRECOVERABLE = "GENERATION_UNRECOVERABLE"
QUOTA_EXCEEDED = "QUOTA_EXCEEDED"
AI_RESPONSE_INVALID_MESSAGE = (
    "The AI service returned an invalid response. Please try again."
)

AMAZON_GENERIC_PUBLIC_MESSAGE = "Amazon integration request failed."
AMAZON_CONFIG_PUBLIC_MESSAGE = "Amazon integration configuration is invalid."
AMAZON_DISABLED_PUBLIC_MESSAGE = "Amazon integration is disabled."
AMAZON_OAUTH_DISABLED_PUBLIC_MESSAGE = "Amazon OAuth is disabled."
AMAZON_OAUTH_STATE_PUBLIC_MESSAGE = "Amazon OAuth state is invalid."
AMAZON_OAUTH_REDIRECT_PUBLIC_MESSAGE = "Amazon OAuth redirect is invalid."
AMAZON_OAUTH_MARKETPLACE_PUBLIC_MESSAGE = "Amazon OAuth marketplace is invalid."
AMAZON_OAUTH_SELLER_PUBLIC_MESSAGE = "Amazon OAuth seller is invalid."
AMAZON_OAUTH_TOKEN_PUBLIC_MESSAGE = "Amazon OAuth token exchange failed."
AMAZON_OAUTH_ACCOUNT_PUBLIC_MESSAGE = "Amazon OAuth account operation failed."
AMAZON_OAUTH_INTENT_PUBLIC_MESSAGE = "Amazon OAuth intent is invalid."
AMAZON_LWA_PUBLIC_MESSAGE = "Login with Amazon request failed."
AMAZON_SP_API_PUBLIC_MESSAGE = "Amazon SP-API request failed."
AMAZON_RESPONSE_PUBLIC_MESSAGE = "Amazon integration response is invalid."
AMAZON_TOKEN_PUBLIC_MESSAGE = "Amazon token operation failed."
AMAZON_ACCOUNT_PUBLIC_MESSAGE = "Amazon account operation failed."
AMAZON_SYNC_PUBLIC_MESSAGE = "Amazon sync operation failed."
AMAZON_MARKETPLACE_PUBLIC_MESSAGE = "Amazon marketplace operation failed."
AMAZON_LISTING_PUBLIC_MESSAGE = "Amazon listing operation failed."
AMAZON_PRODUCT_PUBLIC_MESSAGE = "Amazon product operation failed."
AMAZON_CATALOG_PUBLIC_MESSAGE = "Amazon catalog operation failed."
AMAZON_SAFE_DETAIL_PUBLIC_MESSAGE = "Amazon safe detail is invalid."
AMAZON_SELLING_PARTNER_PUBLIC_MESSAGE = "Amazon selling partner id is required."

AMAZON_PUBLIC_MESSAGES: dict[str, str] = {
    AMAZON_DISABLED: AMAZON_DISABLED_PUBLIC_MESSAGE,
    AMAZON_CONFIG_INVALID: AMAZON_CONFIG_PUBLIC_MESSAGE,
    AMAZON_LWA_TOKEN_INVALID: AMAZON_LWA_PUBLIC_MESSAGE,
    AMAZON_LWA_RATE_LIMITED: AMAZON_LWA_PUBLIC_MESSAGE,
    AMAZON_LWA_UNAVAILABLE: AMAZON_LWA_PUBLIC_MESSAGE,
    AMAZON_SP_API_UNAUTHORIZED: AMAZON_SP_API_PUBLIC_MESSAGE,
    AMAZON_SP_API_FORBIDDEN: AMAZON_SP_API_PUBLIC_MESSAGE,
    AMAZON_SP_API_RATE_LIMITED: AMAZON_SP_API_PUBLIC_MESSAGE,
    AMAZON_SP_API_CLIENT_ERROR: AMAZON_SP_API_PUBLIC_MESSAGE,
    AMAZON_SP_API_SERVER_ERROR: AMAZON_SP_API_PUBLIC_MESSAGE,
    AMAZON_SP_API_TRANSPORT_ERROR: AMAZON_SP_API_PUBLIC_MESSAGE,
    AMAZON_RESPONSE_INVALID: AMAZON_RESPONSE_PUBLIC_MESSAGE,
    AMAZON_RESPONSE_TOO_LARGE: AMAZON_RESPONSE_PUBLIC_MESSAGE,
    AMAZON_TOKEN_DECRYPTION_FAILED: AMAZON_TOKEN_PUBLIC_MESSAGE,
    AMAZON_ACCOUNT_NOT_FOUND: AMAZON_ACCOUNT_PUBLIC_MESSAGE,
    AMAZON_ACCOUNT_ALREADY_EXISTS: AMAZON_ACCOUNT_PUBLIC_MESSAGE,
    AMAZON_ACCOUNT_DISABLED: AMAZON_ACCOUNT_PUBLIC_MESSAGE,
    AMAZON_ACCOUNT_NOT_ACTIVE: AMAZON_ACCOUNT_PUBLIC_MESSAGE,
    AMAZON_SYNC_IN_PROGRESS: AMAZON_SYNC_PUBLIC_MESSAGE,
    AMAZON_SYNC_LEASE_LOST: AMAZON_SYNC_PUBLIC_MESSAGE,
    AMAZON_SYNC_LEASE_EXPIRED: AMAZON_SYNC_PUBLIC_MESSAGE,
    AMAZON_SYNC_FINALIZE_FAILED: AMAZON_SYNC_PUBLIC_MESSAGE,
    AMAZON_SYNC_PAGINATION_LIMIT: AMAZON_SYNC_PUBLIC_MESSAGE,
    AMAZON_SYNC_PAGINATION_LOOP: AMAZON_SYNC_PUBLIC_MESSAGE,
    AMAZON_SAFE_DETAIL_INVALID: AMAZON_SAFE_DETAIL_PUBLIC_MESSAGE,
    AMAZON_SELLING_PARTNER_ID_REQUIRED: AMAZON_SELLING_PARTNER_PUBLIC_MESSAGE,
    AMAZON_MARKETPLACE_NOT_FOUND: AMAZON_MARKETPLACE_PUBLIC_MESSAGE,
    AMAZON_LISTING_NOT_FOUND: AMAZON_LISTING_PUBLIC_MESSAGE,
    AMAZON_PRODUCT_NOT_FOUND: AMAZON_PRODUCT_PUBLIC_MESSAGE,
    AMAZON_CATALOG_ASIN_REQUIRED: AMAZON_CATALOG_PUBLIC_MESSAGE,
    AMAZON_CATALOG_FETCH_FAILED: AMAZON_CATALOG_PUBLIC_MESSAGE,
    AMAZON_CATALOG_IDENTITY_CHANGED: AMAZON_CATALOG_PUBLIC_MESSAGE,
    AMAZON_CATALOG_PERSIST_FAILED: AMAZON_CATALOG_PUBLIC_MESSAGE,
    AMAZON_MARKETPLACE_INACTIVE: AMAZON_MARKETPLACE_PUBLIC_MESSAGE,
    AMAZON_MARKETPLACE_NOT_ELIGIBLE: AMAZON_MARKETPLACE_PUBLIC_MESSAGE,
    AMAZON_OAUTH_DISABLED: AMAZON_OAUTH_DISABLED_PUBLIC_MESSAGE,
    AMAZON_OAUTH_STATE_INVALID: AMAZON_OAUTH_STATE_PUBLIC_MESSAGE,
    AMAZON_OAUTH_STATE_EXPIRED: AMAZON_OAUTH_STATE_PUBLIC_MESSAGE,
    AMAZON_OAUTH_STATE_REPLAY: AMAZON_OAUTH_STATE_PUBLIC_MESSAGE,
    AMAZON_OAUTH_REDIRECT_INVALID: AMAZON_OAUTH_REDIRECT_PUBLIC_MESSAGE,
    AMAZON_OAUTH_MARKETPLACE_INVALID: AMAZON_OAUTH_MARKETPLACE_PUBLIC_MESSAGE,
    AMAZON_OAUTH_SELLER_INVALID: AMAZON_OAUTH_SELLER_PUBLIC_MESSAGE,
    AMAZON_OAUTH_SELLER_MISMATCH: AMAZON_OAUTH_SELLER_PUBLIC_MESSAGE,
    AMAZON_OAUTH_SELLER_ALREADY_LINKED: AMAZON_OAUTH_SELLER_PUBLIC_MESSAGE,
    AMAZON_OAUTH_TOKEN_EXCHANGE_FAILED: AMAZON_OAUTH_TOKEN_PUBLIC_MESSAGE,
    AMAZON_OAUTH_USER_NOT_FOUND: AMAZON_OAUTH_ACCOUNT_PUBLIC_MESSAGE,
    AMAZON_OAUTH_ACCOUNT_PERSIST_FAILED: AMAZON_OAUTH_ACCOUNT_PUBLIC_MESSAGE,
    AMAZON_OAUTH_INTENT_INVALID: AMAZON_OAUTH_INTENT_PUBLIC_MESSAGE,
}


def public_message_for_amazon_error_code(error_code: str) -> str:
    safe_code = sanitize_public_amazon_error_code(error_code)
    return AMAZON_PUBLIC_MESSAGES.get(safe_code, AMAZON_GENERIC_PUBLIC_MESSAGE)


def oauth_redirect_fallback_error_response() -> dict:
    return error_response(
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        AMAZON_OAUTH_REDIRECT_PUBLIC_MESSAGE,
        None,
        error_code=AMAZON_OAUTH_REDIRECT_INVALID,
    )


class AppException(Exception):
    """应用自定义异常."""

    def __init__(
        self,
        message: str,
        code: int = status.HTTP_400_BAD_REQUEST,
        detail: str | None = None,
        cause: Exception | None = None,
        error_code: str | None = None,
    ):
        self.message = message
        self.code = code
        self.detail = detail
        self.cause = cause
        self.error_code = error_code

        super().__init__(message)

    def __str__(self):
        if self.detail:
            return self.detail
        return self.message


def ai_response_invalid_exception(cause: Exception | None = None) -> AppException:
    """Upstream LLM output could not be validated."""
    return AppException(
        message=AI_RESPONSE_INVALID_MESSAGE,
        code=status.HTTP_502_BAD_GATEWAY,
        error_code=AI_RESPONSE_INVALID,
        detail=None,
        cause=cause,
    )


def error_response(
    code: int,
    message: str,
    detail: str | None = None,
    error_code: str | None = None,
) -> dict:
    return ErrorResponse(
        code=code,
        message=message,
        detail=detail,
        error_code=error_code,
    ).model_dump()


def _error_response(
    code: int,
    message: str,
    detail: str | None = None,
    error_code: str | None = None,
) -> dict:
    return error_response(code, message, detail, error_code=error_code)


async def app_exception_handler(
    request: Request,
    exc: AppException,
) -> JSONResponse:
    return JSONResponse(
        status_code=exc.code,
        content=_error_response(
            exc.code,
            exc.message,
            exc.detail,
            error_code=exc.error_code,
        ),
    )


async def amazon_exception_handler(
    request: Request,
    exc: AmazonError,
) -> JSONResponse:
    status_code = exc.status_code or 400
    safe_error_code = sanitize_public_amazon_error_code(exc.error_code)
    public_message = public_message_for_amazon_error_code(safe_error_code)
    return JSONResponse(
        status_code=status_code,
        content=_error_response(
            status_code,
            public_message,
            None,
            error_code=safe_error_code,
        ),
    )


async def http_exception_handler(
    request: Request,
    exc: StarletteHTTPException,
) -> JSONResponse:
    detail = (
        exc.detail
        if isinstance(exc.detail, str)
        else str(exc.detail)
    )

    return JSONResponse(
        status_code=exc.status_code,
        content=_error_response(
            exc.status_code,
            detail,
            detail,
        ),
    )


async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    errors = exc.errors()

    detail = "; ".join(
        f"{'.'.join(str(loc) for loc in e['loc'])}: {e['msg']}"
        for e in errors
    )

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=_error_response(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Validation Error",
            detail,
        ),
    )


async def unhandled_exception_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:

    logger.exception(
        "Unhandled exception on %s %s",
        request.method,
        request.url.path,
    )

    detail = (
        str(exc)
        if settings.DEBUG
        else None
    )

    response = JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=_error_response(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "Internal Server Error",
            detail,
        ),
    )

    origin = request.headers.get("origin")

    if origin and (
        settings.cors_origins_list == ["*"]
        or origin in settings.cors_origins_list
    ):

        response.headers["Access-Control-Allow-Origin"] = origin

        response.headers["Access-Control-Allow-Credentials"] = "true"

        response.headers["Vary"] = "Origin"

    return response
