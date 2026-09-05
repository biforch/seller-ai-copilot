from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import AppException
from app.models.paddle_webhook_event import PaddleWebhookEvent
from app.models.subscription import Subscription
from app.models.user import User


def checkout_user_signature(user_id: str) -> str:
    return hmac.new(
        settings.JWT_SECRET_KEY.encode(),
        f"paddle-checkout:{user_id}".encode(),
        hashlib.sha256,
    ).hexdigest()


def verify_paddle_signature(raw_body: bytes, signature_header: str) -> None:
    if not settings.PADDLE_WEBHOOK_SECRET:
        raise AppException(
            "Billing webhook is not configured.", code=503, error_code="BILLING_DISABLED"
        )
    parts: dict[str, list[str]] = {}
    for item in signature_header.split(";"):
        key, separator, value = item.strip().partition("=")
        if separator:
            parts.setdefault(key, []).append(value)
    try:
        timestamp = int(parts["ts"][0])
    except (KeyError, ValueError, IndexError) as exc:
        raise AppException(
            "Invalid webhook signature.", code=400, error_code="BILLING_SIGNATURE_INVALID"
        ) from exc
    if abs(int(time.time()) - timestamp) > settings.PADDLE_WEBHOOK_TOLERANCE_SECONDS:
        raise AppException(
            "Expired webhook signature.", code=400, error_code="BILLING_SIGNATURE_INVALID"
        )
    expected = hmac.new(
        settings.PADDLE_WEBHOOK_SECRET.encode(),
        str(timestamp).encode() + b":" + raw_body,
        hashlib.sha256,
    ).hexdigest()
    if not any(hmac.compare_digest(expected, candidate) for candidate in parts.get("h1", [])):
        raise AppException(
            "Invalid webhook signature.", code=400, error_code="BILLING_SIGNATURE_INVALID"
        )


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def _price_id(data: dict[str, Any]) -> str | None:
    items = data.get("items")
    if not isinstance(items, list) or not items or not isinstance(items[0], dict):
        return None
    price = items[0].get("price")
    return price.get("id") if isinstance(price, dict) and isinstance(price.get("id"), str) else None


def _user_id(data: dict[str, Any], existing: Subscription | None) -> uuid.UUID | None:
    custom_data = data.get("custom_data")
    candidate = custom_data.get("user_id") if isinstance(custom_data, dict) else None
    signature = custom_data.get("user_signature") if isinstance(custom_data, dict) else None
    if (
        isinstance(candidate, str)
        and isinstance(signature, str)
        and hmac.compare_digest(checkout_user_signature(candidate), signature)
    ):
        try:
            return uuid.UUID(candidate)
        except ValueError:
            return None
    return existing.user_id if existing is not None else None


def process_paddle_event(db: Session, payload: dict[str, Any]) -> bool:
    event_id = payload.get("event_id")
    event_type = payload.get("event_type")
    data = payload.get("data")
    if (
        not isinstance(event_id, str)
        or not isinstance(event_type, str)
        or not isinstance(data, dict)
    ):
        raise AppException(
            "Invalid webhook payload.", code=400, error_code="BILLING_PAYLOAD_INVALID"
        )
    if db.query(PaddleWebhookEvent).filter(PaddleWebhookEvent.event_id == event_id).first():
        return False
    db.add(
        PaddleWebhookEvent(
            event_id=event_id,
            event_type=event_type,
            status="processed",
            payload={"event_id": event_id, "event_type": event_type},
        )
    )

    if event_type.startswith("subscription."):
        provider_id = data.get("id")
        if not isinstance(provider_id, str):
            raise AppException(
                "Invalid subscription payload.", code=400, error_code="BILLING_PAYLOAD_INVALID"
            )
        subscription = (
            db.query(Subscription)
            .filter(Subscription.provider_subscription_id == provider_id)
            .one_or_none()
        )
        user_id = _user_id(data, subscription)
        if user_id is None or db.query(User).filter(User.id == user_id).one_or_none() is None:
            raise AppException(
                "Billing user could not be matched.", code=422, error_code="BILLING_USER_NOT_FOUND"
            )
        price_id = _price_id(data)
        plan = {
            settings.PADDLE_PLUS_PRICE_ID: "plus",
            settings.PADDLE_PRO_PRICE_ID: "pro",
        }.get(price_id or "")
        if plan is None:
            raise AppException(
                "Unknown billing price.", code=422, error_code="BILLING_PRICE_UNKNOWN"
            )
        if subscription is None:
            subscription = Subscription(user_id=user_id, provider_subscription_id=provider_id)
            db.add(subscription)
        period = data.get("current_billing_period")
        subscription.provider = "paddle"
        subscription.provider_customer_id = data.get("customer_id")
        subscription.provider_price_id = price_id
        subscription.plan = plan
        subscription.status = str(data.get("status") or "inactive")
        subscription.current_period_start = _parse_datetime(
            period.get("starts_at") if isinstance(period, dict) else None
        )
        subscription.current_period_end = _parse_datetime(
            period.get("ends_at") if isinstance(period, dict) else None
        )
        scheduled_change = data.get("scheduled_change")
        subscription.cancel_at_period_end = (
            True
            if isinstance(scheduled_change, dict) and scheduled_change.get("action") == "cancel"
            else False
        )
        subscription.expire_date = subscription.current_period_end
        subscription.updated_at = datetime.now(UTC)
        user = db.query(User).filter(User.id == user_id).with_for_update().one()
        user.plan = plan if subscription.status in {"active", "trialing"} else "free"
    db.commit()
    return True


def parse_and_process_webhook(db: Session, raw_body: bytes, signature_header: str) -> bool:
    verify_paddle_signature(raw_body, signature_header)
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise AppException(
            "Invalid webhook payload.", code=400, error_code="BILLING_PAYLOAD_INVALID"
        ) from exc
    if not isinstance(payload, dict):
        raise AppException(
            "Invalid webhook payload.", code=400, error_code="BILLING_PAYLOAD_INVALID"
        )
    try:
        return process_paddle_event(db, payload)
    except Exception:
        db.rollback()
        raise


def create_customer_portal_session(customer_id: str) -> str:
    if not settings.PADDLE_ENABLED or not settings.PADDLE_API_KEY:
        raise AppException("Billing is not available.", code=503, error_code="BILLING_DISABLED")
    base_url = (
        "https://sandbox-api.paddle.com"
        if settings.PADDLE_ENVIRONMENT == "sandbox"
        else "https://api.paddle.com"
    )
    try:
        response = httpx.post(
            f"{base_url}/customers/{customer_id}/portal-sessions",
            headers={"Authorization": f"Bearer {settings.PADDLE_API_KEY}"},
            timeout=15,
        )
        response.raise_for_status()
        url = response.json()["data"]["urls"]["general"]["overview"]
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
        raise AppException(
            "Customer portal is unavailable.", code=502, error_code="BILLING_PROVIDER_UNAVAILABLE"
        ) from exc
    if not isinstance(url, str) or not url.startswith("https://"):
        raise AppException(
            "Customer portal is unavailable.", code=502, error_code="BILLING_PROVIDER_UNAVAILABLE"
        )
    return url
