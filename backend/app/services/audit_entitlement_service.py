from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.exceptions import AppException
from app.models.audit_usage import AuditUsage
from app.models.subscription import Subscription
from app.models.user import User

PLAN_LIMITS = {"free": 5, "plus": 25, "pro": 60}
ACTIVE_SUBSCRIPTION_STATUSES = {"active", "trialing"}


@dataclass(frozen=True)
class Entitlement:
    plan: str
    limit: int | None
    used: int
    reserved: int
    period_start: datetime
    period_end: datetime
    subscription_status: str | None
    cancel_at_period_end: bool

    @property
    def remaining(self) -> int | None:
        if self.limit is None:
            return None
        return max(0, self.limit - self.used - self.reserved)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _free_period(now: datetime) -> tuple[datetime, datetime]:
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start, end


def _active_subscription(db: Session, user_id: uuid.UUID, now: datetime) -> Subscription | None:
    candidates = (
        db.query(Subscription)
        .filter(Subscription.user_id == user_id)
        .order_by(Subscription.updated_at.desc().nullslast(), Subscription.created_at.desc())
        .all()
    )
    for subscription in candidates:
        if subscription.status not in ACTIVE_SUBSCRIPTION_STATUSES:
            continue
        if subscription.plan not in {"plus", "pro"}:
            continue
        if subscription.current_period_end and _utc(subscription.current_period_end) <= now:
            continue
        return subscription
    return None


def get_entitlement(db: Session, *, user_id: uuid.UUID, lock: bool = False) -> Entitlement:
    user_query = db.query(User).filter(User.id == user_id)
    if lock:
        user_query = user_query.with_for_update()
    user = user_query.one_or_none()
    if user is None:
        raise AppException("Authentication required.", code=401, error_code="AUTH_SESSION_INVALID")

    now = datetime.now(UTC)
    subscription = _active_subscription(db, user_id, now)
    subscription_status: str | None
    if subscription and subscription.current_period_start and subscription.current_period_end:
        plan = str(subscription.plan)
        period_start = _utc(subscription.current_period_start)
        period_end = _utc(subscription.current_period_end)
        subscription_status = str(subscription.status)
        cancel_at_period_end = bool(subscription.cancel_at_period_end)
    else:
        plan = "free"
        period_start, period_end = _free_period(now)
        subscription_status = str(subscription.status) if subscription else None
        cancel_at_period_end = False

    # Reservations abandoned by a crashed request must not consume quota forever.
    stale_before = now - timedelta(minutes=15)
    db.query(AuditUsage).filter(
        AuditUsage.user_id == user_id,
        AuditUsage.status == "reserved",
        AuditUsage.updated_at < stale_before,
    ).update({AuditUsage.status: "released", AuditUsage.updated_at: now}, synchronize_session=False)

    counts: dict[str, int] = {
        str(status): int(count)
        for status, count in (
            db.query(AuditUsage.status, func.count(AuditUsage.id))
            .filter(
                AuditUsage.user_id == user_id,
                AuditUsage.period_start == period_start,
                AuditUsage.period_end == period_end,
                AuditUsage.status.in_(["reserved", "completed"]),
            )
            .group_by(AuditUsage.status)
            .all()
        )
    }
    limit = None if bool(user.is_admin) else PLAN_LIMITS[plan]
    return Entitlement(
        plan=plan,
        limit=limit,
        used=int(counts.get("completed", 0)),
        reserved=int(counts.get("reserved", 0)),
        period_start=period_start,
        period_end=period_end,
        subscription_status=subscription_status,
        cancel_at_period_end=cancel_at_period_end,
    )


def reserve_audit(db: Session, *, user_id: uuid.UUID, attempt_id: uuid.UUID) -> Entitlement:
    entitlement = get_entitlement(db, user_id=user_id, lock=True)
    if entitlement.remaining is not None and entitlement.remaining <= 0:
        db.rollback()
        raise AppException(
            "Your monthly audit allowance has been used.",
            code=403,
            error_code="AUDIT_QUOTA_EXCEEDED",
        )
    db.add(
        AuditUsage(
            user_id=user_id,
            attempt_id=attempt_id,
            status="reserved",
            plan=entitlement.plan,
            period_start=entitlement.period_start,
            period_end=entitlement.period_end,
        )
    )
    db.commit()
    return entitlement


def complete_audit(db: Session, *, attempt_id: uuid.UUID, generation_id: uuid.UUID) -> None:
    usage = db.query(AuditUsage).filter(AuditUsage.attempt_id == attempt_id).with_for_update().one()
    usage.status = "completed"
    usage.generation_id = generation_id
    usage.updated_at = datetime.now(UTC)


def release_audit(db: Session, *, attempt_id: uuid.UUID) -> None:
    usage = db.query(AuditUsage).filter(AuditUsage.attempt_id == attempt_id).one_or_none()
    if usage is not None and usage.status == "reserved":
        usage.status = "released"
        usage.updated_at = datetime.now(UTC)
        db.commit()
