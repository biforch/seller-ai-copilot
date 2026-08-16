"""Tenant-scoped read-only Amazon account HTTP endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Response
from fastapi.responses import JSONResponse

from app.api.amazon_accounts_deps import get_amazon_account_read_service
from app.core.exceptions import _error_response, public_message_for_amazon_error_code
from app.core.response import success_response
from app.core.security import get_current_user
from app.integrations.amazon.exceptions import AmazonError, sanitize_public_amazon_error_code
from app.schemas.amazon_accounts import (
    AmazonAccountDetailApiResponse,
    AmazonAccountListApiResponse,
    AmazonAccountListResponse,
    AmazonAccountPublic,
)
from app.services.amazon_account_read_service import AmazonAccountReadService, AmazonAccountSummary

router = APIRouter()

_PRIVATE_CACHE_HEADERS = {
    "Cache-Control": "no-store",
    "Pragma": "no-cache",
}


def _to_public_account(summary: AmazonAccountSummary) -> AmazonAccountPublic:
    return AmazonAccountPublic(
        id=summary.id,
        region=summary.region,
        endpoint_mode=summary.endpoint_mode,
        status=summary.status,
        last_verified_at=summary.last_verified_at,
        created_at=summary.created_at,
        updated_at=summary.updated_at,
    )


def _amazon_error_response(exc: AmazonError) -> JSONResponse:
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
        headers=_PRIVATE_CACHE_HEADERS,
    )


@router.get("/accounts", response_model=AmazonAccountListApiResponse)
def list_amazon_accounts(
    response: Response,
    current_user: dict = Depends(get_current_user),
    account_service: AmazonAccountReadService = Depends(get_amazon_account_read_service),
) -> dict | JSONResponse:
    response.headers.update(_PRIVATE_CACHE_HEADERS)
    user_id = uuid.UUID(str(current_user["id"]))
    try:
        summaries = account_service.list_accounts_for_user(user_id=user_id)
    except AmazonError as exc:
        return _amazon_error_response(exc)
    items = [_to_public_account(summary) for summary in summaries]
    payload = AmazonAccountListResponse(items=items, total=len(items))
    return success_response(data=payload.model_dump(mode="json"))


@router.get("/accounts/{account_id}", response_model=AmazonAccountDetailApiResponse)
def get_amazon_account(
    account_id: uuid.UUID,
    response: Response,
    current_user: dict = Depends(get_current_user),
    account_service: AmazonAccountReadService = Depends(get_amazon_account_read_service),
) -> dict | JSONResponse:
    response.headers.update(_PRIVATE_CACHE_HEADERS)
    user_id = uuid.UUID(str(current_user["id"]))
    try:
        summary = account_service.get_account_for_user(
            user_id=user_id,
            account_id=account_id,
        )
    except AmazonError as exc:
        return _amazon_error_response(exc)
    return success_response(data=_to_public_account(summary).model_dump(mode="json"))
