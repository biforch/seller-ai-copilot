import logging
import uuid

from fastapi import APIRouter, Depends, Header, Request

from app.core.rate_limit import limiter
from app.core.response import success_response
from app.core.security import get_current_user
from app.database.session import get_db
from app.schemas.generate import AnalyzeRequest, GenerateListingRequest
from app.services.generation_executor import GenerationExecutor
from app.services.idempotency import (
    IDEMPOTENCY_KEY_HEADER,
    canonical_request_hash,
    require_idempotency_key,
)

router = APIRouter()
logger = logging.getLogger(__name__)


def _listing_hash(body: GenerateListingRequest, target_customer, advantages) -> str:
    return canonical_request_hash(
        {
            "project_id": str(body.project_id) if body.project_id else None,
            "product_id": str(body.product_id) if body.product_id else None,
            "name": body.name,
            "category": body.category,
            "market": body.market,
            "platform": body.platform,
            "target_customer": target_customer,
            "advantages": advantages,
        }
    )


@router.post("/listing")
@limiter.limit("20/hour")
async def generate_listing(
    request: Request,
    body: GenerateListingRequest,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
    idempotency_key_header: str = Header(..., alias=IDEMPOTENCY_KEY_HEADER),
):
    idempotency_key = require_idempotency_key(idempotency_key_header)

    executor = GenerationExecutor(db)
    user = executor._get_user(current_user["id"])
    target_customer, advantages = executor._resolve_context(
        uuid.UUID(str(user.id)),
        body.product_id,
        body.target_customer,
        body.advantages,
    )
    request_hash = _listing_hash(body, target_customer, advantages)

    data = await executor.execute_listing(
        user_id=current_user["id"],
        body=body,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    return success_response(data=data)


@router.post("/analyze")
@limiter.limit("20/hour")
async def analyze_listing(
    request: Request,
    body: AnalyzeRequest,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
    idempotency_key_header: str = Header(..., alias=IDEMPOTENCY_KEY_HEADER),
):
    idempotency_key = require_idempotency_key(idempotency_key_header)
    request_hash = canonical_request_hash(
        {
            "project_id": str(body.project_id) if body.project_id else None,
            "title": body.title,
            "reviews": body.reviews,
            "rating": body.rating,
            "description": body.description,
        }
    )

    executor = GenerationExecutor(db)
    data = await executor.execute_analyze(
        user_id=current_user["id"],
        body=body,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    return success_response(data=data)


@router.post("/keywords")
@limiter.limit("20/hour")
async def generate_keywords(
    request: Request,
    body: GenerateListingRequest,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
    idempotency_key_header: str = Header(..., alias=IDEMPOTENCY_KEY_HEADER),
):
    idempotency_key = require_idempotency_key(idempotency_key_header)

    executor = GenerationExecutor(db)
    user = executor._get_user(current_user["id"])
    target_customer, advantages = executor._resolve_context(
        uuid.UUID(str(user.id)),
        body.product_id,
        body.target_customer,
        body.advantages,
    )
    request_hash = _listing_hash(body, target_customer, advantages)

    data = await executor.execute_keywords(
        user_id=current_user["id"],
        body=body,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    return success_response(data=data)
