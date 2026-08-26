"""Registered-user-only Listing Audit API for the B1 internal slice."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Request, status

from app.analysis.provider import OpenAIListingAuditProvider
from app.analysis.schemas import ListingAuditInput
from app.core.config import settings
from app.core.exceptions import ANALYSIS_INTERNAL_DISABLED, AppException
from app.core.oauth_rate_limit import listing_audit_rate_limit_key
from app.core.rate_limit import limiter
from app.core.response import success_response
from app.core.security import get_current_user
from app.database.session import get_db
from app.services.generation_executor import GenerationExecutor
from app.services.idempotency import (
    IDEMPOTENCY_KEY_HEADER,
    canonical_request_hash,
    require_idempotency_key,
)

router = APIRouter()


@router.post("/listing-audit")
@limiter.limit("10/hour", key_func=listing_audit_rate_limit_key)
async def create_listing_audit(
    request: Request,
    body: ListingAuditInput,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
    idempotency_key_header: str = Header(..., alias=IDEMPOTENCY_KEY_HEADER),
):
    if not settings.LISTING_AUDIT_INTERNAL_ENABLED:
        raise AppException(
            message="Not found",
            code=status.HTTP_404_NOT_FOUND,
            error_code=ANALYSIS_INTERNAL_DISABLED,
        )

    idempotency_key = require_idempotency_key(idempotency_key_header)
    canonical_input = body.model_dump(mode="json")
    request_hash = canonical_request_hash(canonical_input)
    result = await GenerationExecutor(db).execute_listing_audit(
        user_id=current_user["id"],
        body=body,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        provider=OpenAIListingAuditProvider(),
    )
    return success_response(data=result)
