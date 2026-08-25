from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.auth_session_constants import SESSION_COOKIE_NAME
from app.core.auth_session_tokens import apply_session_cookies, clear_session_cookies
from app.core.csrf import validate_request_origin
from app.core.exceptions import AppException
from app.core.rate_limit import limiter
from app.core.response import success_response
from app.core.security import (
    decode_session_cookie,
    get_current_user,
    get_password_hash,
)
from app.database.session import get_db
from app.models.user import User
from app.schemas.auth import (
    LoginRequest,
    LoginResponse,
    RegisterRequest,
    RegisterResponse,
    UserInfo,
    UserResponse,
)
from app.services.auth_session_service import auth_session_service
from app.services.login_abuse_service import login_abuse_service

router = APIRouter()


def _invalid_credentials() -> AppException:
    return AppException("Invalid email or password", status.HTTP_401_UNAUTHORIZED)


@router.post("/register")
@limiter.limit("10/minute")
def register(request: Request, body: RegisterRequest, db: Session = Depends(get_db)):
    """用户注册."""
    validate_request_origin(request)
    existing_user = db.query(User).filter(User.email == body.email).first()
    if existing_user:
        raise AppException("Email already registered", status.HTTP_400_BAD_REQUEST)

    hashed_password = get_password_hash(body.password)
    new_user = User(
        email=body.email,
        password_hash=hashed_password,
        plan="free",
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    data = RegisterResponse(
        id=str(new_user.id),
        email=str(new_user.email),
        plan=str(new_user.plan),
        message="Registration successful",
    )
    return success_response(data=data.model_dump(), message="Registration successful", code=201)


@router.post("/login")
@limiter.limit("10/minute")
def login(request: Request, body: LoginRequest, db: Session = Depends(get_db)):
    """用户登录."""
    validate_request_origin(request)
    attempt = login_abuse_service.verify_credentials(
        db, email=str(body.email), password=body.password
    )
    if not attempt.authenticated or attempt.user is None:
        if attempt.state_changed:
            db.commit()
        raise _invalid_credentials()
    user = attempt.user

    user_info = UserInfo(id=str(user.id), email=str(user.email), plan=str(user.plan))
    try:
        created = auth_session_service.create_session(db, user)
        db.commit()
    except Exception:
        db.rollback()
        raise

    payload = success_response(
        data=LoginResponse(token_type="cookie", user=user_info).model_dump(),
    )
    response = JSONResponse(content=payload)
    apply_session_cookies(response, created)
    return response


@router.post("/logout")
@limiter.limit("10/minute")
def logout(
    request: Request,
    db: Session = Depends(get_db),
):
    """Revoke the active cookie session and clear browser cookies."""
    session_cookie = request.cookies.get(SESSION_COOKIE_NAME)
    if session_cookie:
        try:
            payload = decode_session_cookie(session_cookie)
            jti = payload.get("jti")
            if isinstance(jti, str) and jti:
                auth_session_service.revoke_session(db, jti=jti)
                db.commit()
        except AppException:
            db.rollback()
        except Exception:
            db.rollback()
            raise

    payload = success_response(message="Logged out")
    response = JSONResponse(content=payload)
    clear_session_cookies(response)
    return response


@router.get("/me")
def get_current_user_info(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取当前用户信息."""
    user = db.query(User).filter(User.id == current_user["id"]).first()
    if not user:
        raise AppException("User not found", status.HTTP_404_NOT_FOUND)

    data = UserResponse(id=str(user.id), email=str(user.email), plan=str(user.plan))
    return success_response(data=data.model_dump())
