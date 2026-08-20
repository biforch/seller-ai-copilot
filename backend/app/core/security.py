from datetime import datetime, timedelta

from fastapi import Cookie, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.core.auth_session_constants import SESSION_COOKIE_NAME
from app.core.config import settings
from app.core.exceptions import auth_session_invalid_exception
from app.database.session import get_db
from app.services.auth_session_service import auth_session_service

# 使用 pbkdf2_sha256 替代 bcrypt（更兼容）
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
security = HTTPBearer(auto_error=False)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码"""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """哈希密码"""
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    """创建JWT Token"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.JWT_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return encoded_jwt


def decode_token(token: str) -> dict:
    """解码JWT Token"""
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )


def _decode_session_cookie(token: str) -> dict:
    try:
        return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except JWTError:
        raise auth_session_invalid_exception()


async def get_current_user_from_cookie(
    session_cookie: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    db: Session = Depends(get_db),
) -> dict | None:
    if not settings.COOKIE_SESSION_ENABLED or not session_cookie:
        return None

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
    return {
        "id": validated.user_id,
        "email": validated.email,
        "auth_method": "cookie",
        "jti": validated.jti,
    }


async def get_logout_context(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    session_cookie: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict:
    if credentials is not None:
        token = credentials.credentials
        payload = decode_token(token)
        user_id = payload.get("sub")
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication credentials",
            )
        return {
            "id": user_id,
            "email": payload.get("email"),
            "auth_method": "bearer",
            "jti": None,
        }

    if settings.COOKIE_SESSION_ENABLED and session_cookie:
        payload = _decode_session_cookie(session_cookie)
        user_id = payload.get("sub")
        jti = payload.get("jti")
        if user_id is None or not isinstance(jti, str) or not jti:
            raise auth_session_invalid_exception()
        return {
            "id": str(user_id),
            "email": payload.get("email"),
            "auth_method": "cookie",
            "jti": jti,
        }

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Not authenticated",
    )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    cookie_user: dict | None = Depends(get_current_user_from_cookie),
):
    """获取当前用户（依赖注入）"""
    if credentials is not None:
        token = credentials.credentials
        payload = decode_token(token)
        user_id = payload.get("sub")
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication credentials",
            )
        return {
            "id": user_id,
            "email": payload.get("email"),
            "auth_method": "bearer",
            "jti": None,
        }

    if cookie_user is not None:
        return cookie_user

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Not authenticated",
    )
