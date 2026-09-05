"""Registered-user-only Listing Audit API for the B1 internal slice."""

from __future__ import annotations

import uuid

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
from app.models.generation_request import GenerationRequest, GenerationRequestStatus
from app.services.audit_entitlement_service import complete_audit, release_audit, reserve_audit
from app.services.generation_executor import GenerationExecutor
from app.services.idempotency import (
    IDEMPOTENCY_KEY_HEADER,
    canonical_request_hash,
    require_idempotency_key,
)
from app.services.product_analytics_service import record_product_event_best_effort

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
    user_id = uuid.UUID(str(current_user["id"]))
    existing = (
        db.query(GenerationRequest)
        .filter(
            GenerationRequest.user_id == user_id,
            GenerationRequest.request_type == "listing_audit",
            GenerationRequest.idempotency_key == idempotency_key,
        )
        .one_or_none()
    )
    attempt_id: uuid.UUID | None = None
    if existing is None or existing.status != GenerationRequestStatus.SUCCEEDED:
        attempt_id = uuid.uuid4()
        reserve_audit(db, user_id=user_id, attempt_id=attempt_id)
        record_product_event_best_effort(
            db,
            user_id=user_id,
            event_type="audit_started",
            correlation_id=attempt_id,
        )
    try:
        result = await GenerationExecutor(db).execute_listing_audit(
            user_id=str(user_id),
            body=body,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            provider=OpenAIListingAuditProvider(),
        )
        if attempt_id is not None:
            completed = (
                db.query(GenerationRequest)
                .filter(
                    GenerationRequest.user_id == user_id,
                    GenerationRequest.request_type == "listing_audit",
                    GenerationRequest.idempotency_key == idempotency_key,
                    GenerationRequest.status == GenerationRequestStatus.SUCCEEDED,
                )
                .one()
            )
            if completed.generation_id is None:
                raise RuntimeError("listing audit completed without a generation")
            complete_audit(db, attempt_id=attempt_id, generation_id=completed.generation_id)
            db.commit()
            record_product_event_best_effort(
                db,
                user_id=user_id,
                event_type="audit_completed",
                correlation_id=attempt_id,
            )
    except Exception:
        db.rollback()
        if attempt_id is not None:
            release_audit(db, attempt_id=attempt_id)
            record_product_event_best_effort(
                db,
                user_id=user_id,
                event_type="audit_failed",
                correlation_id=attempt_id,
            )
        raise
    return success_response(data=result)
