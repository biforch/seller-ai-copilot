"""PostgreSQL-backed auth session lifecycle."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.auth_session_tokens import (
    CreatedSessionTokens,
    build_created_session,
    hash_session_secret,
)
from app.core.exceptions import auth_session_invalid_exception
from app.models.auth_session import AuthSession
from app.models.user import User


@dataclass(frozen=True)
class ValidatedSession:
    user_id: str
    email: str
    jti: str
    session_id: uuid.UUID


class AuthSessionService:
    def create_session(self, db: Session, user: User) -> CreatedSessionTokens:
        created = build_created_session(user_id=str(user.id), email=str(user.email))
        record = AuthSession(
            user_id=user.id,
            jti_hash=hash_session_secret(created.jti),
            csrf_token_hash=hash_session_secret(created.csrf_token),
            expires_at=created.expires_at,
        )
        db.add(record)
        db.flush()
        return created

    def get_session_for_csrf(self, db: Session, *, jti: str) -> AuthSession | None:
        jti_hash = hash_session_secret(jti)
        session = db.query(AuthSession).filter(AuthSession.jti_hash == jti_hash).one_or_none()
        if session is None:
            return None
        if session.expires_at <= datetime.now(UTC):
            return None
        return session

    def get_active_session(self, db: Session, *, jti: str) -> AuthSession | None:
        session = self.get_session_for_csrf(db, jti=jti)
        if session is None or session.revoked_at is not None:
            return None
        return session

    def validate_session(
        self, db: Session, *, jti: str, email: str | None, user_id: str | None
    ) -> ValidatedSession:
        session = self.get_active_session(db, jti=jti)
        if session is None:
            raise auth_session_invalid_exception()
        if user_id is not None and str(session.user_id) != str(user_id):
            raise auth_session_invalid_exception()
        return ValidatedSession(
            user_id=str(session.user_id),
            email=email or "",
            jti=jti,
            session_id=session.id,
        )

    def validate_csrf_for_session(self, db: Session, *, jti: str, csrf_token: str) -> None:
        session = self.get_session_for_csrf(db, jti=jti)
        if session is None:
            raise auth_session_invalid_exception()
        expected_hash = hash_session_secret(csrf_token)
        if not _hashes_equal(expected_hash, session.csrf_token_hash):
            from app.core.exceptions import auth_csrf_invalid_exception

            raise auth_csrf_invalid_exception()

    def revoke_session(self, db: Session, *, jti: str) -> None:
        jti_hash = hash_session_secret(jti)
        session = (
            db.query(AuthSession)
            .filter(AuthSession.jti_hash == jti_hash)
            .with_for_update()
            .one_or_none()
        )
        if session is None:
            return
        if session.revoked_at is None:
            session.revoked_at = datetime.now(UTC)


def _hashes_equal(left: str, right: str) -> bool:
    import hmac

    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


auth_session_service = AuthSessionService()
