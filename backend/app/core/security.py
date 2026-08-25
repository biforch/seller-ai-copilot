from datetime import datetime, timedelta

from fastapi import Cookie, Depends
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.core.auth_session_constants import SESSION_COOKIE_NAME
from app.core.config import settings
from app.core.exceptions import auth_session_invalid_exception
from app.database.session import get_db
from app.services.auth_session_service import auth_session_service

pwd_context = CryptContext(
    schemes=["bcrypt_sha256", "pbkdf2_sha256"],
    deprecated=["pbkdf2_sha256"],
)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码"""
    return pwd_context.verify(plain_password, hashed_password)


def verify_and_update_password(
    plain_password: str, hashed_password: str
) -> tuple[bool, str | None]:
    """Verify a password and return an upgraded hash when the stored scheme is legacy."""
    return pwd_context.verify_and_update(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """哈希密码"""
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    """Create a signed JWT used only inside HttpOnly session cookies."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.JWT_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    """Decode a signed JWT used by internal session machinery."""
    try:
        return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except JWTError:
        raise auth_session_invalid_exception()


def _decode_session_cookie(token: str) -> dict:
    try:
        return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except JWTError:
        raise auth_session_invalid_exception()


async def _resolve_cookie_user(
    session_cookie: str | None,
    db: Session,
    *,
    require_mfa: bool = True,
) -> dict:
    if not session_cookie:
        raise auth_session_invalid_exception()

    payload = _decode_session_cookie(session_cookie)
    user_id = payload.get("sub")
    jti = payload.get("jti")
    if user_id is None or not isinstance(jti, str) or not jti:
        raise auth_session_invalid_exception()

    validated = auth_session_service.validate_session(
        db,
        jti=jti,
        email=payload.get("email") if isinstance(payload.get("email"), str) else None,
        user_id=str(user_id),
    )
    if require_mfa and not validated.mfa_verified:
        raise auth_session_invalid_exception()
    return {
        "id": validated.user_id,
        "email": validated.email,
        "auth_method": "cookie",
        "jti": validated.jti,
        "session_id": str(validated.session_id),
        "mfa_verified": validated.mfa_verified,
    }


async def get_current_user(
    session_cookie: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    db: Session = Depends(get_db),
):
    """Resolve the current user from the HttpOnly session cookie only."""
    return await _resolve_cookie_user(session_cookie, db)


async def get_mfa_pending_user(
    session_cookie: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    db: Session = Depends(get_db),
):
    """Resolve a password-authenticated session before mandatory MFA completes."""
    return await _resolve_cookie_user(session_cookie, db, require_mfa=False)


async def get_logout_context(
    session_cookie: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    db: Session = Depends(get_db),
) -> dict:
    """Resolve logout context from the active cookie session only."""
    return await _resolve_cookie_user(session_cookie, db, require_mfa=False)


def decode_session_cookie(token: str) -> dict:
    """Decode a session cookie JWT for internal server-side use."""
    return _decode_session_cookie(token)
