"""Persistent, tenant-neutral login abuse protection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.core.security import get_password_hash, verify_and_update_password, verify_password
from app.models.user import User

MAX_FAILED_LOGIN_ATTEMPTS = 5
LOGIN_LOCK_MINUTES = 15


@dataclass(frozen=True)
class LoginAttempt:
    user: User | None
    authenticated: bool
    state_changed: bool = False


class LoginAbuseService:
    """Serialize attempts per known account without revealing account existence."""

    def __init__(self) -> None:
        self._dummy_password_hash = get_password_hash("NotARealAccount!234")

    @staticmethod
    def now() -> datetime:
        return datetime.now(UTC)

    def verify_credentials(self, db: Session, *, email: str, password: str) -> LoginAttempt:
        user = (
            db.query(User)
            .filter(User.email == email)
            .with_for_update()
            .one_or_none()
        )
        if user is None:
            verify_password(password, self._dummy_password_hash)
            return LoginAttempt(user=None, authenticated=False)

        now = self.now()
        if user.locked_until is not None and user.locked_until > now:
            verify_password(password, self._dummy_password_hash)
            return LoginAttempt(user=user, authenticated=False)

        try:
            password_valid, replacement_hash = verify_and_update_password(
                password, str(user.password_hash)
            )
        except ValueError:
            # Corrupt/unsupported stored hashes must fail closed without exposing state.
            verify_password(password, self._dummy_password_hash)
            password_valid, replacement_hash = False, None

        if not password_valid:
            user.failed_login_attempts = int(user.failed_login_attempts or 0) + 1
            if user.failed_login_attempts >= MAX_FAILED_LOGIN_ATTEMPTS:
                user.failed_login_attempts = MAX_FAILED_LOGIN_ATTEMPTS
                user.locked_until = now + timedelta(minutes=LOGIN_LOCK_MINUTES)
            db.add(user)
            return LoginAttempt(user=user, authenticated=False, state_changed=True)

        state_changed = bool(user.failed_login_attempts or user.locked_until is not None)
        user.failed_login_attempts = 0
        user.locked_until = None
        if replacement_hash is not None:
            user.password_hash = replacement_hash
            state_changed = True
        if state_changed:
            db.add(user)
        return LoginAttempt(user=user, authenticated=True, state_changed=state_changed)


login_abuse_service = LoginAbuseService()
