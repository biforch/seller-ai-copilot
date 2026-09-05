from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import AppException
from app.core.response import success_response
from app.core.security import get_current_user
from app.database.session import get_db
from app.models.subscription import Subscription
from app.services.audit_entitlement_service import get_entitlement
from app.services.paddle_billing_service import (
    checkout_user_signature,
    create_customer_portal_session,
    parse_and_process_webhook,
)

router = APIRouter()


@router.get("/entitlement")
def entitlement(current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    value = get_entitlement(db, user_id=uuid.UUID(str(current_user["id"])))
    return success_response(
        data={
            "plan": value.plan,
            "limit": value.limit,
            "used": value.used,
            "reserved": value.reserved,
            "remaining": value.remaining,
            "period_start": value.period_start,
            "period_end": value.period_end,
            "subscription_status": value.subscription_status,
            "cancel_at_period_end": value.cancel_at_period_end,
        }
    )


@router.get("/checkout-config")
def checkout_config(current_user: dict = Depends(get_current_user)):
    user_id = str(current_user["id"])
    return success_response(
        data={
            "enabled": settings.PADDLE_ENABLED,
            "environment": settings.PADDLE_ENVIRONMENT,
            "client_token": settings.PADDLE_CLIENT_TOKEN if settings.PADDLE_ENABLED else None,
            "user_id": user_id if settings.PADDLE_ENABLED else None,
            "user_signature": (
                checkout_user_signature(user_id) if settings.PADDLE_ENABLED else None
            ),
            "prices": {"plus": settings.PADDLE_PLUS_PRICE_ID, "pro": settings.PADDLE_PRO_PRICE_ID},
        }
    )


@router.post("/portal")
def customer_portal(current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    subscription = (
        db.query(Subscription)
        .filter(
            Subscription.user_id == uuid.UUID(str(current_user["id"])),
            Subscription.provider_customer_id.isnot(None),
        )
        .order_by(Subscription.updated_at.desc().nullslast(), Subscription.created_at.desc())
        .first()
    )
    if subscription is None:
        raise AppException(
            "No billing account was found.", code=404, error_code="BILLING_CUSTOMER_NOT_FOUND"
        )
    return success_response(
        data={"url": create_customer_portal_session(str(subscription.provider_customer_id))}
    )


@router.post("/paddle/webhook")
async def paddle_webhook(
    request: Request,
    paddle_signature: str = Header(default="", alias="Paddle-Signature"),
    db: Session = Depends(get_db),
):
    processed = parse_and_process_webhook(db, await request.body(), paddle_signature)
    return success_response(data={"processed": processed})
