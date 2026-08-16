"""Tenant-scoped Amazon marketplace read and refresh endpoints."""

import hashlib
import uuid

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse

from app.api.amazon_marketplaces_deps import (
    AccountRuntimeResolver,
    MarketplaceRefreshServiceFactory,
    get_amazon_account_runtime_resolver,
    get_amazon_marketplace_read_service,
    get_amazon_marketplace_refresh_service_factory,
)
from app.core.exceptions import _error_response, public_message_for_amazon_error_code
from app.core.rate_limit import limiter
from app.core.response import success_response
from app.core.security import get_current_user
from app.integrations.amazon.exceptions import AmazonError, sanitize_public_amazon_error_code
from app.schemas.amazon_marketplaces import (
    AmazonMarketplaceListApiResponse,
    AmazonMarketplaceListResponse,
    AmazonMarketplacePublic,
    AmazonMarketplaceRefreshApiResponse,
    AmazonMarketplaceRefreshResponse,
)
from app.services.amazon_marketplace_read_service import (
    AmazonMarketplaceParticipationSummary,
    AmazonMarketplaceReadService,
)

router = APIRouter()

_PRIVATE_CACHE_HEADERS = {
    "Cache-Control": "no-store",
    "Pragma": "no-cache",
}


def _amazon_refresh_rate_limit_key(request: Request) -> str:
    authorization = request.headers.get("authorization", "")
    if authorization:
        return hashlib.sha256(authorization.encode("utf-8")).hexdigest()
    client_host = request.client.host if request.client is not None else "unknown"
    return f"anonymous:{client_host}"


def _amazon_error_response(exc: AmazonError) -> JSONResponse:
    status_code = exc.status_code or 400
    safe_error_code = sanitize_public_amazon_error_code(exc.error_code)
    return JSONResponse(
        status_code=status_code,
        content=_error_response(
            status_code,
            public_message_for_amazon_error_code(safe_error_code),
            None,
            error_code=safe_error_code,
        ),
        headers=_PRIVATE_CACHE_HEADERS,
    )


def _to_public_marketplace(
    summary: AmazonMarketplaceParticipationSummary,
) -> AmazonMarketplacePublic:
    return AmazonMarketplacePublic.model_validate(summary, from_attributes=True)


@router.get(
    "/accounts/{account_id}/marketplaces",
    response_model=AmazonMarketplaceListApiResponse,
)
def list_amazon_marketplaces(
    account_id: uuid.UUID,
    response: Response,
    current_user: dict = Depends(get_current_user),
    marketplace_service: AmazonMarketplaceReadService = Depends(
        get_amazon_marketplace_read_service
    ),
) -> dict | JSONResponse:
    response.headers.update(_PRIVATE_CACHE_HEADERS)
    user_id = uuid.UUID(str(current_user["id"]))
    try:
        summaries = marketplace_service.list_marketplaces_for_user(
            user_id=user_id,
            account_id=account_id,
        )
    except AmazonError as exc:
        return _amazon_error_response(exc)
    items = [_to_public_marketplace(summary) for summary in summaries]
    payload = AmazonMarketplaceListResponse(items=items, total=len(items))
    return success_response(data=payload.model_dump(mode="json"))


@router.post(
    "/accounts/{account_id}/marketplaces/refresh",
    response_model=AmazonMarketplaceRefreshApiResponse,
)
@limiter.limit("6/minute", key_func=_amazon_refresh_rate_limit_key)
async def refresh_amazon_marketplaces(
    request: Request,
    account_id: uuid.UUID,
    response: Response,
    current_user: dict = Depends(get_current_user),
    account_runtime_resolver: AccountRuntimeResolver = Depends(
        get_amazon_account_runtime_resolver
    ),
    refresh_service_factory: MarketplaceRefreshServiceFactory = Depends(
        get_amazon_marketplace_refresh_service_factory
    ),
) -> dict | JSONResponse:
    response.headers.update(_PRIVATE_CACHE_HEADERS)
    user_id = uuid.UUID(str(current_user["id"]))
    try:
        account = account_runtime_resolver(user_id, account_id)
        refresh_service = refresh_service_factory(account.region, account.endpoint_mode)
        result = await refresh_service.refresh_marketplace_participations(
            user_id=user_id,
            account_id=account_id,
        )
    except AmazonError as exc:
        return _amazon_error_response(exc)

    payload = AmazonMarketplaceRefreshResponse(
        account_id=result.account_id,
        sync_log_id=result.sync_log_id,
        items_seen=result.items_seen,
        items_written=result.items_written,
        items_deactivated=result.items_deactivated,
    )
    return success_response(data=payload.model_dump(mode="json"))
