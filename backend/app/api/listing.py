"""Listing version REST API: import, current, and version history."""

from __future__ import annotations

import logging
import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, Query, status
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.exceptions import AppException
from app.core.security import get_current_user
from app.database.session import get_db
from app.schemas.common import ErrorResponse
from app.schemas.listing import (
    ApproveProposalApiResponse,
    ApproveProposalRequest,
    ApproveProposalResponse,
    CurrentListingApiResponse,
    CurrentListingResponse,
    ImportListingApiResponse,
    ImportListingRequest,
    ImportListingResponse,
    ListingProposalDetailApiResponse,
    ListingProposalDetailResponse,
    ListingProposalDiffResponse,
    ListingProposalListItemResponse,
    ListingProposalPageApiResponse,
    ListingProposalPageResponse,
    ListingProposalResponse,
    ListingScoreResponse,
    ListingVersionPageApiResponse,
    ListingVersionPageResponse,
    ListingVersionResponse,
    PatchProposalDecisionsApiResponse,
    PatchProposalDecisionsRequest,
    PatchProposalDecisionsResponse,
    RejectProposalApiResponse,
    RejectProposalRequest,
    RejectProposalResponse,
)
from app.schemas.pagination import build_pagination_meta
from app.services.idempotency import IDEMPOTENCY_KEY_HEADER, require_idempotency_key
from app.services.listing_proposal import (
    approve_listing_proposal,
    get_listing_proposal_detail,
    list_listing_proposals,
    patch_proposal_decisions,
    reject_listing_proposal,
)
from app.services.listing_version import (
    get_current_listing_version,
    import_api_request_hash,
    import_listing_version,
    list_listing_versions,
)
from app.services.scoring import compute_listing_score

router = APIRouter()

logger = logging.getLogger(__name__)

ProposalListStatus = Literal["reviewing", "approved", "rejected", "superseded", "all"]

_LISTING_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    status.HTTP_404_NOT_FOUND: {"model": ErrorResponse, "description": "Not found"},
    status.HTTP_409_CONFLICT: {"model": ErrorResponse, "description": "Conflict"},
    status.HTTP_422_UNPROCESSABLE_ENTITY: {
        "model": ErrorResponse,
        "description": "Validation error",
    },
}

_LISTING_PROPOSAL_LIST_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    **_LISTING_ERROR_RESPONSES,
    status.HTTP_500_INTERNAL_SERVER_ERROR: {
        "model": ErrorResponse,
        "description": "Internal server error",
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


def _build_proposal_detail_payload(detail) -> ListingProposalDetailResponse:
    current_id = detail.current_listing_version_id
    return ListingProposalDetailResponse(
        proposal=ListingProposalResponse.from_proposal(detail.proposal),
        base_version=(
            ListingVersionResponse.from_version(
                detail.base_version,
                is_current=current_id is not None and detail.base_version.id == current_id,
            )
            if detail.base_version is not None
            else None
        ),
        approved_version=(
            ListingVersionResponse.from_version(
                detail.approved_version,
                is_current=current_id is not None and detail.approved_version.id == current_id,
            )
            if detail.approved_version is not None
            else None
        ),
        diff=ListingProposalDiffResponse.from_diff(detail.diff),
    )


def _build_proposal_list_items(proposals) -> list[ListingProposalListItemResponse]:
    items: list[ListingProposalListItemResponse] = []
    for proposal in proposals:
        try:
            items.append(ListingProposalListItemResponse.from_proposal(proposal))
        except ValidationError:
            logger.warning(
                "Invalid proposal candidate snapshot proposal_id=%s product_id=%s category=validation_error",
                proposal.id,
                proposal.product_id,
            )
            raise AppException(
                message="Internal server error",
                code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            ) from None
    return items


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


@router.get(
    "/{product_id}/listing/proposals",
    response_model=ListingProposalPageApiResponse,
    responses=_LISTING_PROPOSAL_LIST_ERROR_RESPONSES,
)
def list_product_listing_proposals(
    product_id: uuid.UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status_filter: ProposalListStatus = Query("reviewing", alias="status"),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _product, proposals, total = list_listing_proposals(
        db,
        product_id=product_id,
        current_user_id=uuid.UUID(str(current_user["id"])),
        page=page,
        page_size=page_size,
        status_filter=status_filter,
    )
    payload = ListingProposalPageResponse(
        items=_build_proposal_list_items(proposals),
        pagination=build_pagination_meta(page, page_size, total),
    )
    return ListingProposalPageApiResponse(
        code=status.HTTP_200_OK,
        message="success",
        data=payload,
    )


@router.get(
    "/{product_id}/listing/proposals/{proposal_id}",
    response_model=ListingProposalDetailApiResponse,
    responses=_LISTING_ERROR_RESPONSES,
)
def get_listing_proposal(
    product_id: uuid.UUID,
    proposal_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    detail = get_listing_proposal_detail(
        db,
        product_id=product_id,
        current_user_id=uuid.UUID(str(current_user["id"])),
        proposal_id=proposal_id,
    )
    payload = _build_proposal_detail_payload(detail)
    return ListingProposalDetailApiResponse(
        code=status.HTTP_200_OK,
        message="success",
        data=payload,
    )


@router.patch(
    "/{product_id}/listing/proposals/{proposal_id}/decisions",
    response_model=PatchProposalDecisionsApiResponse,
    responses=_LISTING_ERROR_RESPONSES,
)
def patch_listing_proposal_decisions(
    product_id: uuid.UUID,
    proposal_id: uuid.UUID,
    body: PatchProposalDecisionsRequest,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    proposal = patch_proposal_decisions(
        db,
        product_id=product_id,
        current_user_id=uuid.UUID(str(current_user["id"])),
        proposal_id=proposal_id,
        decisions=body.decisions,
        expected_revision=body.expected_revision,
    )
    payload = PatchProposalDecisionsResponse(
        proposal=ListingProposalResponse.from_proposal(proposal),
    )
    return PatchProposalDecisionsApiResponse(
        code=status.HTTP_200_OK,
        message="success",
        data=payload,
    )


@router.post(
    "/{product_id}/listing/proposals/{proposal_id}/approve",
    response_model=ApproveProposalApiResponse,
    responses=_LISTING_ERROR_RESPONSES,
)
def approve_listing_proposal_endpoint(
    product_id: uuid.UUID,
    proposal_id: uuid.UUID,
    body: ApproveProposalRequest,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    result = approve_listing_proposal(
        db,
        product_id=product_id,
        current_user_id=uuid.UUID(str(current_user["id"])),
        proposal_id=proposal_id,
        expected_revision=body.expected_revision,
        decisions=body.decisions,
    )
    payload = ApproveProposalResponse(
        proposal=ListingProposalResponse.from_proposal(result.proposal),
        approved_version=ListingVersionResponse.from_version(
            result.version,
            is_current=True,
        ),
        replay=result.replay,
    )
    return ApproveProposalApiResponse(
        code=status.HTTP_200_OK,
        message="success",
        data=payload,
    )


@router.post(
    "/{product_id}/listing/proposals/{proposal_id}/reject",
    response_model=RejectProposalApiResponse,
    responses=_LISTING_ERROR_RESPONSES,
)
def reject_listing_proposal_endpoint(
    product_id: uuid.UUID,
    proposal_id: uuid.UUID,
    body: RejectProposalRequest,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    result = reject_listing_proposal(
        db,
        product_id=product_id,
        current_user_id=uuid.UUID(str(current_user["id"])),
        proposal_id=proposal_id,
        expected_revision=body.expected_revision,
    )
    payload = RejectProposalResponse(
        proposal=ListingProposalResponse.from_proposal(result.proposal),
        replay=result.replay,
    )
    return RejectProposalApiResponse(
        code=status.HTTP_200_OK,
        message="success",
        data=payload,
    )
