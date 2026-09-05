from __future__ import annotations

import logging
import uuid
from collections import Counter, defaultdict
from datetime import UTC, date, datetime, timedelta

from sqlalchemy.orm import Session

from app.models.product_event import ProductEvent

logger = logging.getLogger(__name__)

EVENT_TYPES = (
    "registration_completed",
    "audit_started",
    "audit_completed",
    "audit_failed",
    "amazon_connect_started",
    "amazon_connected",
)


def record_product_event(
    db: Session,
    *,
    user_id: uuid.UUID,
    event_type: str,
    correlation_id: uuid.UUID | None = None,
    commit: bool = True,
) -> None:
    if event_type not in EVENT_TYPES:
        raise ValueError("Unsupported product event type")
    db.add(ProductEvent(user_id=user_id, event_type=event_type, correlation_id=correlation_id))
    if commit:
        db.commit()


def record_product_event_best_effort(
    db: Session,
    *,
    user_id: uuid.UUID,
    event_type: str,
    correlation_id: uuid.UUID | None = None,
) -> None:
    try:
        record_product_event(
            db,
            user_id=user_id,
            event_type=event_type,
            correlation_id=correlation_id,
        )
    except Exception:
        db.rollback()
        logger.warning("Product analytics event could not be recorded event_type=%s", event_type)


def build_analytics_summary(db: Session, *, days: int) -> dict:
    now = datetime.now(UTC)
    start = now - timedelta(days=days - 1)
    start = start.replace(hour=0, minute=0, second=0, microsecond=0)
    events = (
        db.query(ProductEvent)
        .filter(ProductEvent.occurred_at >= start)
        .order_by(ProductEvent.occurred_at.asc())
        .all()
    )
    counts = Counter(event.event_type for event in events)
    unique_users: dict[str, set[uuid.UUID]] = defaultdict(set)
    daily: dict[date, Counter[str]] = defaultdict(Counter)
    for event in events:
        unique_users[event.event_type].add(event.user_id)
        occurred_at = event.occurred_at
        if occurred_at.tzinfo is None:
            occurred_at = occurred_at.replace(tzinfo=UTC)
        daily[occurred_at.astimezone(UTC).date()][event.event_type] += 1

    audit_finished = counts["audit_completed"] + counts["audit_failed"]
    audit_success_rate = (
        round(counts["audit_completed"] / audit_finished * 100, 1) if audit_finished else None
    )
    timeline = []
    for offset in range(days):
        day = start.date() + timedelta(days=offset)
        timeline.append(
            {
                "date": day.isoformat(),
                "registration_completed": daily[day]["registration_completed"],
                "audit_started": daily[day]["audit_started"],
                "audit_completed": daily[day]["audit_completed"],
                "audit_failed": daily[day]["audit_failed"],
                "amazon_connect_started": daily[day]["amazon_connect_started"],
                "amazon_connected": daily[day]["amazon_connected"],
            }
        )

    return {
        "days": days,
        "period_start": start,
        "period_end": now,
        "counts": {event_type: counts[event_type] for event_type in EVENT_TYPES},
        "unique_users": {event_type: len(unique_users[event_type]) for event_type in EVENT_TYPES},
        "audit_success_rate": audit_success_rate,
        "daily": timeline,
    }
