"""Quota billing-period reset behavior."""

from __future__ import annotations

import threading
from datetime import datetime, timedelta

from sqlalchemy.orm import sessionmaker

from app.core.exceptions import QUOTA_EXCEEDED, AppException
from app.models.user import User
from app.services.quota import QUOTA_PERIOD_DAYS, lock_user_for_quota, reserve_tokens
from app.services.quota_estimation import estimate_reserve_tokens


def test_quota_resets_when_no_active_reserved(db_session, user_factory):
    user = user_factory("reset-clean@example.com")
    user.monthly_tokens = 1000
    user.used_tokens = 900
    user.reserved_tokens = 0
    user.reset_date = datetime.utcnow() - timedelta(days=1)
    db_session.add(user)
    db_session.commit()

    locked = lock_user_for_quota(db_session, user.id)
    assert locked.used_tokens == 0
    assert locked.reserved_tokens == 0
    assert locked.reset_date > datetime.utcnow()


def test_quota_reset_deferred_while_processing_reserved(db_session, user_factory):
    user = user_factory("reset-defer@example.com")
    user.monthly_tokens = 1000
    user.used_tokens = 800
    user.reserved_tokens = 150
    user.reset_date = datetime.utcnow() - timedelta(days=1)
    db_session.add(user)
    db_session.commit()

    locked = lock_user_for_quota(db_session, user.id)
    assert locked.used_tokens == 800
    assert locked.reserved_tokens == 150


def test_quota_resets_after_processing_reserved_cleared(db_session, user_factory):
    user = user_factory("reset-after@example.com")
    user.monthly_tokens = 1000
    user.used_tokens = 800
    user.reserved_tokens = 150
    user.reset_date = datetime.utcnow() - timedelta(days=1)
    db_session.add(user)
    db_session.commit()

    locked = lock_user_for_quota(db_session, user.id)
    locked.reserved_tokens = 0
    db_session.add(locked)
    db_session.commit()

    again = lock_user_for_quota(db_session, user.id)
    assert again.used_tokens == 0
    assert again.reserved_tokens == 0


def test_concurrent_reset_and_reserve_never_negative(engine):
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    setup = session_factory()
    try:
        from app.core.security import get_password_hash

        reserve_amount = estimate_reserve_tokens(
            "listing",
            {
                "name": "Race",
                "category": "Electronics",
                "market": "USA",
                "platform": "Amazon",
            },
        )
        user = User(
            email="reset-race@example.com",
            password_hash=get_password_hash("Password1"),
            monthly_tokens=reserve_amount + 500,
            used_tokens=100,
            reserved_tokens=0,
            reset_date=datetime.utcnow() - timedelta(days=1),
        )
        setup.add(user)
        setup.commit()
        setup.refresh(user)
    finally:
        setup.close()

    errors: list[BaseException] = []
    barrier = threading.Barrier(2)

    def worker():
        db = session_factory()
        try:
            barrier.wait(timeout=5)
            locked = lock_user_for_quota(db, user.id)
            reserve_tokens(locked, reserve_amount)
            db.add(locked)
            db.commit()
        except BaseException as exc:
            errors.append(exc)
        finally:
            db.close()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
        assert not thread.is_alive()

    if errors:
        assert all(isinstance(exc, AppException) and exc.error_code == QUOTA_EXCEEDED for exc in errors)
        assert len(errors) == 1

    verify = session_factory()
    try:
        refreshed = verify.query(User).filter(User.id == user.id).one()
        assert refreshed.used_tokens >= 0
        assert refreshed.reserved_tokens >= 0
        assert refreshed.used_tokens + refreshed.reserved_tokens <= refreshed.monthly_tokens
        if refreshed.reset_date is not None:
            assert refreshed.reset_date > datetime.utcnow() - timedelta(days=QUOTA_PERIOD_DAYS + 1)
    finally:
        verify.close()
