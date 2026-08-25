from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta

from passlib.context import CryptContext
from sqlalchemy.orm import sessionmaker

from app.core.security import pwd_context
from app.models.user import User
from app.services.login_abuse_service import (
    MAX_FAILED_LOGIN_ATTEMPTS,
    LoginAbuseService,
    login_abuse_service,
)

PASSWORD = "Password1!abc"
WRONG_PASSWORD = "WrongPassword!234"


def test_successful_login_upgrades_legacy_password_hash(db_session, user_factory):
    legacy_context = CryptContext(schemes=["pbkdf2_sha256"])
    user = user_factory("legacy-login@example.com", password=PASSWORD)
    user.password_hash = legacy_context.hash(PASSWORD)
    db_session.commit()

    attempt = login_abuse_service.verify_credentials(
        db_session, email=str(user.email), password=PASSWORD
    )
    assert attempt.authenticated is True
    assert attempt.state_changed is True
    assert pwd_context.identify(str(user.password_hash)) == "bcrypt_sha256"


def test_expired_lock_allows_valid_login_and_clears_state(db_session, user_factory, monkeypatch):
    user = user_factory("expired-lock@example.com", password=PASSWORD)
    now = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)
    user.failed_login_attempts = MAX_FAILED_LOGIN_ATTEMPTS
    user.locked_until = now - timedelta(seconds=1)
    db_session.commit()
    monkeypatch.setattr(login_abuse_service, "now", lambda: now)

    attempt = login_abuse_service.verify_credentials(
        db_session, email=str(user.email), password=PASSWORD
    )
    assert attempt.authenticated is True
    assert user.failed_login_attempts == 0
    assert user.locked_until is None


def test_corrupt_hash_fails_closed_and_records_failure(db_session, user_factory):
    user = user_factory("corrupt-hash@example.com")
    user.password_hash = "not-a-supported-password-hash"
    db_session.commit()

    attempt = login_abuse_service.verify_credentials(
        db_session, email=str(user.email), password=PASSWORD
    )
    assert attempt.authenticated is False
    assert attempt.state_changed is True
    assert user.failed_login_attempts == 1


def test_concurrent_failures_are_serialized_and_lock_account(engine):
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    setup = session_factory()
    try:
        user = User(
            email="concurrent-login-lock@example.com",
            password_hash=pwd_context.hash(PASSWORD),
            plan="free",
        )
        setup.add(user)
        setup.commit()
        user_id = user.id
    finally:
        setup.close()

    barrier = threading.Barrier(MAX_FAILED_LOGIN_ATTEMPTS)
    failures: list[BaseException] = []

    def worker() -> None:
        session = session_factory()
        try:
            barrier.wait(timeout=10)
            service = LoginAbuseService()
            attempt = service.verify_credentials(
                session,
                email="concurrent-login-lock@example.com",
                password=WRONG_PASSWORD,
            )
            assert attempt.authenticated is False
            session.commit()
        except BaseException as exc:
            failures.append(exc)
            session.rollback()
        finally:
            session.close()

    threads = [threading.Thread(target=worker) for _ in range(MAX_FAILED_LOGIN_ATTEMPTS)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)
        assert not thread.is_alive()

    verify = session_factory()
    try:
        locked = verify.query(User).filter(User.id == user_id).one()
        assert failures == []
        assert locked.failed_login_attempts == MAX_FAILED_LOGIN_ATTEMPTS
        assert locked.locked_until is not None
        verify.delete(locked)
        verify.commit()
    finally:
        verify.close()
