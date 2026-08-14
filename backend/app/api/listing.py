"""Listing version REST API: import, current, and version history."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Header, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.database.session import get_db
from app.schemas.common import ErrorResponse
from app.schemas.listing import (
    CurrentListingApiResponse,
    CurrentListingResponse,
    ImportListingApiResponse,
    ImportListingRequest,
    ImportListingResponse,
    ListingScoreResponse,
    ListingVersionPageApiResponse,
    ListingVersionPageResponse,
    ListingVersionResponse,
)
from app.schemas.pagination import build_pagination_meta
from app.services.idempotency import IDEMPOTENCY_KEY_HEADER, require_idempotency_key
from app.services.listing_version import (
    get_current_listing_version,
    import_api_request_hash,
    import_listing_version,
    list_listing_versions,
)
from app.services.scoring import compute_listing_score

router = APIRouter()

_LISTING_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    status.HTTP_404_NOT_FOUND: {"model": ErrorResponse, "description": "Not found"},
    status.HTTP_409_CONFLICT: {"model": ErrorResponse, "description": "Conflict"},
    status.HTTP_422_UNPROCESSABLE_ENTITY: {
        "model": ErrorResponse,
        "description": "Validation error",
    },
}


def _score_for_version(version) -> ListingScoreResponse:
    raw = compute_listing_score(
        {
            "title": version.title,
            "bullets": version.bullets,
            "description": version.description,
            "keywords": version.backend_keywords,
        }
    )
    return ListingScoreResponse.model_validate(raw)


def _build_import_payload(result) -> ImportListingResponse:
    return ImportListingResponse(
        version=ListingVersionResponse.from_version(
            result.version,
            is_current=True,
        ),
        replay=result.replay,
        is_first=result.version.version_number == 1,
    )


@router.post(
    "/{product_id}/listing/import",
    response_model=ImportListingApiResponse,
    responses={
        status.HTTP_200_OK: {
            "model": ImportListingApiResponse,
            "description": "Idempotent replay",
        },
        status.HTTP_201_CREATED: {
            "model": ImportListingApiResponse,
            "description": "Version created",
        },
        **_LISTING_ERROR_RESPONSES,
    },
)
def import_listing(
    product_id: uuid.UUID,
    body: ImportListingRequest,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
    idempotency_key_header: str = Header(..., alias=IDEMPOTENCY_KEY_HEADER),
):
    idempotency_key = require_idempotency_key(idempotency_key_header)
    result = import_listing_version(
        db,
        product_id=product_id,
        current_user_id=uuid.UUID(str(current_user["id"])),
        snapshot=body,
        idempotency_key=idempotency_key,
        request_hash=import_api_request_hash(body),
    )
    payload = _build_import_payload(result)
    http_status = status.HTTP_200_OK if result.replay else status.HTTP_201_CREATED
    envelope = ImportListingApiResponse(code=http_status, message="success", data=payload)
    return JSONResponse(
        status_code=http_status,
        content=envelope.model_dump(mode="json"),
    )


@router.get(
    "/{product_id}/listing/current",
    response_model=CurrentListingApiResponse,
    responses=_LISTING_ERROR_RESPONSES,
)
def get_current_listing(
    product_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _product, version = get_current_listing_version(
        db,
        product_id=product_id,
        current_user_id=uuid.UUID(str(current_user["id"])),
    )
    payload = CurrentListingResponse(
        version=ListingVersionResponse.from_version(version, is_current=True),
        score=_score_for_version(version),
    )
    envelope = CurrentListingApiResponse(code=status.HTTP_200_OK, message="success", data=payload)
    return envelope


@router.get(
    "/{product_id}/listing/versions",
    response_model=ListingVersionPageApiResponse,
    responses=_LISTING_ERROR_RESPONSES,
)
def get_listing_versions(
    product_id: uuid.UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    product, items, total = list_listing_versions(
        db,
        product_id=product_id,
        current_user_id=uuid.UUID(str(current_user["id"])),
        page=page,
        page_size=page_size,
    )
    current_id = product.current_listing_version_id
    version_items = [
        ListingVersionResponse.from_version(
            item,
            is_current=current_id is not None and item.id == current_id,
        )
        for item in items
    ]
    payload = ListingVersionPageResponse(
        items=version_items,
        pagination=build_pagination_meta(page, page_size, total),
    )
    envelope = ListingVersionPageApiResponse(code=status.HTTP_200_OK, message="success", data=payload)
    return envelope
