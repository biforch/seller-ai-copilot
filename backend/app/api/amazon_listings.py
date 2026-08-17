"""Tenant-scoped Amazon listing read and sync endpoints."""

import hashlib
import uuid

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse

from app.api.amazon_catalog_deps import (
    CatalogEnrichmentServiceFactory,
    get_amazon_catalog_enrichment_service_factory,
    get_amazon_catalog_read_service,
)
from app.api.amazon_listings_deps import (
    ProductSyncServiceFactory,
    get_amazon_listing_link_service,
    get_amazon_listing_read_service,
    get_amazon_product_sync_service_factory,
)
from app.api.amazon_marketplaces_deps import (
    AccountRuntimeResolver,
    get_amazon_account_runtime_resolver,
)
from app.core.exceptions import _error_response, public_message_for_amazon_error_code
from app.core.rate_limit import limiter
from app.core.response import success_response
from app.core.security import get_current_user
from app.integrations.amazon.exceptions import AmazonError, sanitize_public_amazon_error_code
from app.schemas.amazon_catalog import (
    AmazonCatalogSnapshotApiResponse,
    AmazonCatalogSnapshotPublic,
)
from app.schemas.amazon_listings import (
    AmazonListingApiResponse,
    AmazonListingListApiResponse,
    AmazonListingListResponse,
    AmazonListingProductLinkRequest,
    AmazonListingPublic,
    AmazonProductSyncApiResponse,
    AmazonProductSyncResponse,
)
from app.schemas.pagination import build_pagination_meta
from app.services.amazon_catalog_enrichment_service import CatalogEnrichmentResult
from app.services.amazon_catalog_read_service import (
    AmazonCatalogReadService,
    AmazonCatalogSnapshotSummary,
)
from app.services.amazon_listing_link_service import AmazonListingLinkService
from app.services.amazon_listing_read_service import AmazonListingReadService

router = APIRouter()

_PRIVATE_CACHE_HEADERS = {"Cache-Control": "no-store", "Pragma": "no-cache"}


def _product_sync_rate_limit_key(request: Request) -> str:
    authorization = request.headers.get("authorization", "")
    if authorization:
        return hashlib.sha256(authorization.encode("utf-8")).hexdigest()
    client_host = request.client.host if request.client is not None else "unknown"
    return f"anonymous:{client_host}"


def _catalog_public(
    snapshot: AmazonCatalogSnapshotSummary | CatalogEnrichmentResult,
    *,
    cache_hit: bool | None,
) -> AmazonCatalogSnapshotPublic:
    snapshot_id = (
        snapshot.snapshot_id
        if isinstance(snapshot, CatalogEnrichmentResult)
        else snapshot.id
    )
    return AmazonCatalogSnapshotPublic(
        id=snapshot_id,
        listing_id=snapshot.listing_id,
        asin=snapshot.asin,
        marketplace_id=snapshot.marketplace_id,
        item_name=snapshot.item_name,
        brand=snapshot.brand,
        manufacturer=snapshot.manufacturer,
        color=snapshot.color,
        size=snapshot.size,
        style=snapshot.style,
        model_number=snapshot.model_number,
        part_number=snapshot.part_number,
        product_type=snapshot.product_type,
        fetched_at=snapshot.fetched_at,
        expires_at=snapshot.expires_at,
        cache_hit=cache_hit,
    )


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


@router.get(
    "/accounts/{account_id}/marketplaces/{marketplace_id}/listings",
    response_model=AmazonListingListApiResponse,
)
def list_amazon_listings(
    account_id: uuid.UUID,
    marketplace_id: str,
    response: Response,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    include_inactive: bool = Query(False),
    current_user: dict = Depends(get_current_user),
    listing_service: AmazonListingReadService = Depends(get_amazon_listing_read_service),
) -> dict | JSONResponse:
    response.headers.update(_PRIVATE_CACHE_HEADERS)
    user_id = uuid.UUID(str(current_user["id"]))
    try:
        result = listing_service.list_listings_for_user(
            user_id=user_id,
            account_id=account_id,
            marketplace_id=marketplace_id,
            page=page,
            page_size=page_size,
            include_inactive=include_inactive,
        )
    except AmazonError as exc:
        return _amazon_error_response(exc)
    items = [
        AmazonListingPublic.model_validate(item, from_attributes=True)
        for item in result.items
    ]
    payload = AmazonListingListResponse(
        items=items,
        pagination=build_pagination_meta(result.page, result.page_size, result.total),
    )
    return success_response(data=payload.model_dump(mode="json"))


@router.patch(
    "/accounts/{account_id}/marketplaces/{marketplace_id}/listings/{listing_id}/product-link",
    response_model=AmazonListingApiResponse,
)
def link_amazon_listing_product(
    account_id: uuid.UUID,
    marketplace_id: str,
    listing_id: uuid.UUID,
    body: AmazonListingProductLinkRequest,
    response: Response,
    current_user: dict = Depends(get_current_user),
    link_service: AmazonListingLinkService = Depends(get_amazon_listing_link_service),
) -> dict | JSONResponse:
    response.headers.update(_PRIVATE_CACHE_HEADERS)
    user_id = uuid.UUID(str(current_user["id"]))
    try:
        listing = link_service.link_product_for_user(
            user_id=user_id,
            account_id=account_id,
            marketplace_id=marketplace_id,
            listing_id=listing_id,
            product_id=body.product_id,
        )
    except AmazonError as exc:
        return _amazon_error_response(exc)
    payload = AmazonListingPublic.model_validate(listing, from_attributes=True)
    return success_response(data=payload.model_dump(mode="json"))


@router.post(
    "/accounts/{account_id}/marketplaces/{marketplace_id}/listings/sync",
    response_model=AmazonProductSyncApiResponse,
)
@limiter.limit("3/minute", key_func=_product_sync_rate_limit_key)
async def sync_amazon_listings(
    request: Request,
    account_id: uuid.UUID,
    marketplace_id: str,
    response: Response,
    current_user: dict = Depends(get_current_user),
    account_runtime_resolver: AccountRuntimeResolver = Depends(
        get_amazon_account_runtime_resolver
    ),
    sync_service_factory: ProductSyncServiceFactory = Depends(
        get_amazon_product_sync_service_factory
    ),
) -> dict | JSONResponse:
    response.headers.update(_PRIVATE_CACHE_HEADERS)
    user_id = uuid.UUID(str(current_user["id"]))
    try:
        account = account_runtime_resolver(user_id, account_id)
        sync_service = sync_service_factory(account.region, account.endpoint_mode)
        result = await sync_service.sync_product_listings(
            user_id=user_id,
            account_id=account_id,
            marketplace_id=marketplace_id,
        )
    except AmazonError as exc:
        return _amazon_error_response(exc)
    payload = AmazonProductSyncResponse(
        account_id=result.account_id,
        marketplace_id=result.marketplace_id,
        sync_log_id=result.sync_log_id,
        items_seen=result.items_seen,
        items_written=result.items_written,
        items_deactivated=result.items_deactivated,
        pages_seen=result.pages_seen,
    )
    return success_response(data=payload.model_dump(mode="json"))


@router.get(
    "/accounts/{account_id}/marketplaces/{marketplace_id}/listings/{listing_id}/catalog",
    response_model=AmazonCatalogSnapshotApiResponse,
)
def get_amazon_listing_catalog(
    account_id: uuid.UUID,
    marketplace_id: str,
    listing_id: uuid.UUID,
    response: Response,
    current_user: dict = Depends(get_current_user),
    catalog_service: AmazonCatalogReadService = Depends(get_amazon_catalog_read_service),
) -> dict | JSONResponse:
    response.headers.update(_PRIVATE_CACHE_HEADERS)
    user_id = uuid.UUID(str(current_user["id"]))
    try:
        snapshot = catalog_service.get_latest_for_user(
            user_id=user_id,
            account_id=account_id,
            marketplace_id=marketplace_id,
            listing_id=listing_id,
        )
    except AmazonError as exc:
        return _amazon_error_response(exc)
    payload = None if snapshot is None else _catalog_public(snapshot, cache_hit=None)
    return success_response(
        data=None if payload is None else payload.model_dump(mode="json")
    )


@router.post(
    "/accounts/{account_id}/marketplaces/{marketplace_id}/listings/{listing_id}/catalog/refresh",
    response_model=AmazonCatalogSnapshotApiResponse,
)
@limiter.limit("10/minute", key_func=_product_sync_rate_limit_key)
async def refresh_amazon_listing_catalog(
    request: Request,
    account_id: uuid.UUID,
    marketplace_id: str,
    listing_id: uuid.UUID,
    response: Response,
    force_refresh: bool = Query(False),
    current_user: dict = Depends(get_current_user),
    account_runtime_resolver: AccountRuntimeResolver = Depends(
        get_amazon_account_runtime_resolver
    ),
    enrichment_service_factory: CatalogEnrichmentServiceFactory = Depends(
        get_amazon_catalog_enrichment_service_factory
    ),
) -> dict | JSONResponse:
    response.headers.update(_PRIVATE_CACHE_HEADERS)
    user_id = uuid.UUID(str(current_user["id"]))
    try:
        account = account_runtime_resolver(user_id, account_id)
        enrichment_service = enrichment_service_factory(
            account.region, account.endpoint_mode
        )
        result = await enrichment_service.enrich_listing(
            user_id=user_id,
            account_id=account_id,
            listing_id=listing_id,
            marketplace_id=marketplace_id,
            force_refresh=force_refresh,
        )
    except AmazonError as exc:
        return _amazon_error_response(exc)
    payload = _catalog_public(result, cache_hit=result.cache_hit)
    return success_response(data=payload.model_dump(mode="json"))
