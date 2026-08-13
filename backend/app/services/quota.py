import logging
from datetime import datetime, timedelta

from fastapi import status
from sqlalchemy.orm import Session

from app.core.exceptions import QUOTA_EXCEEDED, AppException
from app.core.logging_utils import user_log_ref
from app.core.orm_utils import orm_int
from app.models.user import User

logger = logging.getLogger(__name__)

QUOTA_PERIOD_DAYS = 30


def _maybe_reset_monthly_quota(user: User, now: datetime) -> None:
    if user.reset_date is None:
        user.reset_date = now + timedelta(days=QUOTA_PERIOD_DAYS)
        return

    if now >= user.reset_date:
        active_reserved = orm_int(user.reserved_tokens)
        if active_reserved > 0:
            logger.info(
                "Defer quota reset %s active_reserved=%s reset_date=%s",
                user_log_ref(user.id),
                active_reserved,
                user.reset_date,
            )
            return
        logger.info("Reset monthly quota %s", user_log_ref(user.id))
        user.used_tokens = 0
        user.reserved_tokens = 0
        user.reset_date = now + timedelta(days=QUOTA_PERIOD_DAYS)


def available_tokens(user: User) -> int:
    return orm_int(user.monthly_tokens) - orm_int(user.used_tokens) - orm_int(user.reserved_tokens)


def lock_user_for_quota(db: Session, user_id) -> User:
    user = (
        db.query(User)
        .filter(User.id == user_id)
        .with_for_update()
        .one()
    )
    _maybe_reset_monthly_quota(user, datetime.utcnow())
    return user


def reserve_tokens(user: User, amount: int) -> None:
    if amount <= 0:
        raise ValueError("reserve amount must be positive")

    remaining = available_tokens(user)
    logger.info(
        "Quota reserve %s amount=%s remaining=%s used=%s reserved=%s total=%s",
        user_log_ref(user.id),
        amount,
        remaining,
        orm_int(user.used_tokens),
        orm_int(user.reserved_tokens),
        orm_int(user.monthly_tokens),
    )

    if remaining < amount:
        raise AppException(
            message="AI quota exceeded",
            code=status.HTTP_403_FORBIDDEN,
            detail="Please upgrade your plan.",
            error_code=QUOTA_EXCEEDED,
        )

    user.reserved_tokens = orm_int(user.reserved_tokens) + amount


def release_reserved_tokens(user: User, amount: int) -> None:
    if amount <= 0:
        return
    release = min(amount, orm_int(user.reserved_tokens))
    user.reserved_tokens = orm_int(user.reserved_tokens) - release


def settle_reserved_to_consumed(user: User, reserved_amount: int, consumed_amount: int) -> None:
    """Settle quota after LLM success. Never blocks saving results when consumed > reserved.

    Overage (consumed > reserved) is logged; subsequent reserve_tokens() calls may return
    QUOTA_EXCEEDED when monthly allowance is exhausted.
    """
    if consumed_amount < 0:
        raise ValueError("consumed_amount must be non-negative")

    held = min(reserved_amount, orm_int(user.reserved_tokens))
    user.reserved_tokens = orm_int(user.reserved_tokens) - held
    user.used_tokens = orm_int(user.used_tokens) + consumed_amount

    if consumed_amount > reserved_amount:
        overage = consumed_amount - reserved_amount
        logger.warning(
            "Quota token overage %s reserved=%s consumed=%s overage=%s",
            user_log_ref(user.id),
            reserved_amount,
            consumed_amount,
            overage,
        )

    logger.info(
        "Quota settle %s reserved=%s consumed=%s used=%s remaining_reserved=%s",
        user_log_ref(user.id),
        reserved_amount,
        consumed_amount,
        orm_int(user.used_tokens),
        orm_int(user.reserved_tokens),
    )


def check_quota(user: User, db: Session) -> int:
    """Legacy read-only quota check for non-generate callers."""
    locked = lock_user_for_quota(db, user.id)
    remaining = available_tokens(locked)
    if remaining <= 0:
        raise AppException(
            message="AI quota exceeded",
            code=status.HTTP_403_FORBIDDEN,
            detail="Please upgrade your plan.",
            error_code=QUOTA_EXCEEDED,
        )
    db.add(locked)
    return remaining
