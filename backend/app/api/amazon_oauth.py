"""Amazon OAuth HTTP endpoints."""

from __future__ import annotations

import logging
import uuid
from urllib.parse import urlencode, urlparse, urlunparse

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.responses import Response as StarletteResponse

from app.api.amazon_oauth_deps import (
    AmazonOAuthServiceFactory,
    get_amazon_oauth_service,
    get_amazon_oauth_service_factory,
)
from app.core.config import settings as app_settings
from app.core.exceptions import oauth_redirect_fallback_error_response
from app.core.response import success_response
from app.core.security import get_current_user
from app.integrations.amazon.config import AmazonSettings
from app.integrations.amazon.exceptions import (
    AMAZON_OAUTH_ACCOUNT_PERSIST_FAILED,
    AMAZON_OAUTH_REDIRECT_INVALID,
    AmazonError,
    amazon_oauth_redirect_invalid_error,
    sanitize_callback_redirect_error_code,
)
from app.schemas.amazon_oauth import AmazonOAuthStartRequest, AmazonOAuthStartResponse
from app.services.amazon_oauth_service import AmazonOAuthService

logger = logging.getLogger(__name__)

router = APIRouter()

_CALLBACK_SECURITY_QUERY_KEYS = (
    "state",
    "spapi_oauth_code",
    "selling_partner_id",
    "error",
    "error_description",
)

_OAUTH_START_CACHE_HEADERS = {
    "Cache-Control": "no-store",
    "Pragma": "no-cache",
}

_OAUTH_CALLBACK_SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "Pragma": "no-cache",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}


def _amazon_settings() -> AmazonSettings:
    return app_settings.amazon_settings


def _validate_frontend_base_url(url: str, *, environment: str) -> str:
    normalized = url.strip()
    if not normalized:
        raise amazon_oauth_redirect_invalid_error()
    if any(ord(char) < 32 or ord(char) == 127 for char in normalized):
        raise amazon_oauth_redirect_invalid_error()

    parsed = urlparse(normalized)
    if parsed.username or parsed.password:
        raise amazon_oauth_redirect_invalid_error()
    if parsed.fragment:
        raise amazon_oauth_redirect_invalid_error()
    if parsed.query:
        raise amazon_oauth_redirect_invalid_error()
    if not parsed.scheme or not parsed.netloc or not parsed.hostname:
        raise amazon_oauth_redirect_invalid_error()

    if environment in {"staging", "production"}:
        if parsed.scheme != "https":
            raise amazon_oauth_redirect_invalid_error()
    elif environment == "testing":
        if parsed.scheme != "https":
            raise amazon_oauth_redirect_invalid_error()
        hostname = parsed.hostname.lower()
        if not (
            hostname.endswith(".test")
            or "mock" in hostname
            or hostname.endswith(".local")
        ):
            raise amazon_oauth_redirect_invalid_error()
    elif parsed.scheme not in {"http", "https"}:
        raise amazon_oauth_redirect_invalid_error()

    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))


def _frontend_success_location(amazon_settings: AmazonSettings) -> str:
    return _validate_frontend_base_url(
        amazon_settings.oauth_frontend_success_url,
        environment=amazon_settings.environment,
    )


def _frontend_error_location(amazon_settings: AmazonSettings, *, error_code: str) -> str:
    safe_error_code = sanitize_callback_redirect_error_code(error_code)
    base = _validate_frontend_base_url(
        amazon_settings.oauth_frontend_error_url,
        environment=amazon_settings.environment,
    )
    parsed = urlparse(base)
    query = urlencode({"error_code": safe_error_code})
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", query, ""))


def _oauth_redirect_fallback_json() -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content=oauth_redirect_fallback_error_response(),
        headers=_OAUTH_CALLBACK_SECURITY_HEADERS,
    )


def _build_oauth_error_redirect(
    amazon_settings: AmazonSettings,
    error_code: str,
) -> RedirectResponse | JSONResponse:
    try:
        location = _frontend_error_location(amazon_settings, error_code=error_code)
    except AmazonError:
        return _oauth_redirect_fallback_json()
    return RedirectResponse(
        url=location,
        status_code=303,
        headers=_OAUTH_CALLBACK_SECURITY_HEADERS,
    )


def _build_oauth_success_redirect(
    amazon_settings: AmazonSettings,
) -> RedirectResponse | JSONResponse:
    try:
        location = _frontend_success_location(amazon_settings)
    except AmazonError:
        return _build_oauth_error_redirect(amazon_settings, AMAZON_OAUTH_REDIRECT_INVALID)
    return RedirectResponse(
        url=location,
        status_code=303,
        headers=_OAUTH_CALLBACK_SECURITY_HEADERS,
    )


def _has_duplicate_security_query_params(request: Request) -> bool:
    for key in _CALLBACK_SECURITY_QUERY_KEYS:
        if len(request.query_params.getlist(key)) > 1:
            return True
    return False


def _read_callback_query_param(request: Request, key: str) -> str | None:
    values = request.query_params.getlist(key)
    if not values:
        return None
    return values[0]


def _callback_params_invalid(
    *,
    error: str | None,
    state: str | None,
    spapi_oauth_code: str | None,
    selling_partner_id: str | None,
) -> bool:
    if error is not None and error != "":
        return True
    if state is None or state == "":
        return True
    if spapi_oauth_code is None or spapi_oauth_code == "":
        return True
    if selling_partner_id is None or selling_partner_id == "":
        return True
    return False


@router.post("/oauth/start")
def start_amazon_oauth(
    body: AmazonOAuthStartRequest,
    response: Response,
    current_user: dict = Depends(get_current_user),
    oauth_service: AmazonOAuthService = Depends(get_amazon_oauth_service),
) -> dict:
    result = oauth_service.start_authorization(
        user_id=uuid.UUID(str(current_user["id"])),
        marketplace_code=body.marketplace_code,
        intent=body.intent,
        target_account_id=body.target_account_id,
    )
    response.headers.update(_OAUTH_START_CACHE_HEADERS)
    payload = AmazonOAuthStartResponse(
        authorization_url=result.authorization_url,
        marketplace_code=result.marketplace_code,
        region=result.region,
        expires_at=result.expires_at,
    )
    return success_response(data=payload.model_dump(mode="json"))


@router.get("/oauth/callback")
async def amazon_oauth_callback(
    request: Request,
    oauth_service_factory: AmazonOAuthServiceFactory = Depends(get_amazon_oauth_service_factory),
) -> StarletteResponse:
    amazon_settings = _amazon_settings()

    if _has_duplicate_security_query_params(request):
        return _build_oauth_error_redirect(amazon_settings, AMAZON_OAUTH_REDIRECT_INVALID)

    error = _read_callback_query_param(request, "error")
    state = _read_callback_query_param(request, "state")
    spapi_oauth_code = _read_callback_query_param(request, "spapi_oauth_code")
    selling_partner_id = _read_callback_query_param(request, "selling_partner_id")

    if _callback_params_invalid(
        error=error,
        state=state,
        spapi_oauth_code=spapi_oauth_code,
        selling_partner_id=selling_partner_id,
    ):
        return _build_oauth_error_redirect(amazon_settings, AMAZON_OAUTH_REDIRECT_INVALID)

    assert state is not None
    assert spapi_oauth_code is not None
    assert selling_partner_id is not None

    oauth_service = oauth_service_factory()
    try:
        await oauth_service.complete_authorization(
            state=state,
            spapi_oauth_code=spapi_oauth_code,
            selling_partner_id=selling_partner_id,
        )
    except AmazonError as exc:
        return _build_oauth_error_redirect(amazon_settings, exc.error_code)
    except Exception:
        logger.warning(
            "OAuth callback failure operation=oauth_callback category=unexpected",
        )
        return _build_oauth_error_redirect(
            amazon_settings,
            AMAZON_OAUTH_ACCOUNT_PERSIST_FAILED,
        )

    return _build_oauth_success_redirect(amazon_settings)
