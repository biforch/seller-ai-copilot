import os
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.auth_session_constants import SESSION_COOKIE_NAME
from app.core.auth_session_tokens import apply_session_cookies, clear_session_cookies
from app.core.config import settings
from app.core.csrf import validate_request_origin
from app.core.exceptions import AppException
from app.core.rate_limit import limiter
from app.core.response import success_response
from app.core.security import (
    decode_session_cookie,
    get_current_user,
    get_mfa_pending_user,
    get_password_hash,
)
from app.database.session import get_db
from app.models.user import User
from app.schemas.auth import (
    LoginRequest,
    LoginResponse,
    MfaCodeRequest,
    MfaConfirmResponse,
    MfaSetupResponse,
    MfaVerifyResponse,
    RegisterRequest,
    RegisterResponse,
    UserInfo,
    UserResponse,
)
from app.services.auth_session_service import auth_session_service
from app.services.login_abuse_service import login_abuse_service
from app.services.mfa_service import mfa_service
from app.services.product_analytics_service import record_product_event_best_effort

router = APIRouter()


def _invalid_credentials() -> AppException:
    return AppException("Invalid email or password", status.HTTP_401_UNAUTHORIZED)


def _user_info(user: User) -> UserInfo:
    return UserInfo(id=str(user.id), email=str(user.email), plan=str(user.plan), is_admin=bool(user.is_admin))


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
    record_product_event_best_effort(
        db,
        user_id=new_user.id,
        event_type="registration_completed",
    )

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

    test_auto_verify = settings.ENVIRONMENT == "testing" and (
        os.environ.get("AUTH_TESTING_AUTO_VERIFY_MFA", "").lower() == "true"
    )
    try:
        created = auth_session_service.create_session(
            db, user, mfa_verified=test_auto_verify
        )
        db.commit()
    except Exception:
        db.rollback()
        raise

    payload = success_response(
        data=LoginResponse(
            token_type="cookie",
            user=_user_info(user) if test_auto_verify else None,
            mfa_required=not test_auto_verify,
            mfa_enrollment_required=(
                user.mfa_enabled_at is None and not test_auto_verify
            ),
        ).model_dump(),
    )
    response = JSONResponse(content=payload)
    apply_session_cookies(response, created)
    response.headers["Cache-Control"] = "no-store"
    return response


def _pending_user(db: Session, current_user: dict) -> User:
    user = (
        db.query(User)
        .filter(User.id == current_user["id"])
        .with_for_update()
        .one_or_none()
    )
    if user is None:
        raise AppException("Authentication required", status.HTTP_401_UNAUTHORIZED)
    return user


def _complete_mfa(db: Session, current_user: dict) -> None:
    auth_session_service.mark_mfa_verified(
        db, session_id=uuid.UUID(current_user["session_id"])
    )


def _reject_mfa(db: Session, current_user: dict) -> None:
    auth_session_service.record_mfa_failure(
        db, session_id=uuid.UUID(current_user["session_id"])
    )
    db.commit()
    raise AppException("Invalid MFA code", status.HTTP_401_UNAUTHORIZED)


@router.post("/mfa/setup")
@limiter.limit("5/minute")
def setup_mfa(
    request: Request,
    current_user: dict = Depends(get_mfa_pending_user),
    db: Session = Depends(get_db),
):
    validate_request_origin(request)
    user = _pending_user(db, current_user)
    if user.mfa_enabled_at is not None:
        raise AppException("MFA is already configured", status.HTTP_409_CONFLICT)
    if user.mfa_secret_ciphertext is None:
        secret = mfa_service.generate_secret()
        user.mfa_secret_ciphertext = mfa_service.encrypt_secret(
            secret, user_id=str(user.id)
        )
        db.commit()
    else:
        secret = mfa_service.decrypt_secret(
            user.mfa_secret_ciphertext, user_id=str(user.id)
        )
    data = MfaSetupResponse(
        secret=secret,
        provisioning_uri=mfa_service.provisioning_uri(secret, email=str(user.email)),
    )
    response = JSONResponse(content=success_response(data=data.model_dump()))
    response.headers["Cache-Control"] = "no-store"
    return response


@router.post("/mfa/confirm")
@limiter.limit("10/minute")
def confirm_mfa(
    request: Request,
    body: MfaCodeRequest,
    current_user: dict = Depends(get_mfa_pending_user),
    db: Session = Depends(get_db),
):
    validate_request_origin(request)
    user = _pending_user(db, current_user)
    if user.mfa_enabled_at is not None or user.mfa_secret_ciphertext is None:
        raise AppException("MFA setup is not pending", status.HTTP_409_CONFLICT)
    secret = mfa_service.decrypt_secret(
        user.mfa_secret_ciphertext, user_id=str(user.id)
    )
    counter = mfa_service.matching_totp_counter(secret, body.code)
    if counter is None:
        _reject_mfa(db, current_user)
    recovery_codes = mfa_service.generate_recovery_codes()
    user.mfa_recovery_code_hashes = [
        mfa_service.hash_recovery_code(code) for code in recovery_codes
    ]
    user.mfa_enabled_at = datetime.now(UTC)
    user.mfa_last_totp_counter = counter
    _complete_mfa(db, current_user)
    db.commit()
    data = MfaConfirmResponse(user=_user_info(user), recovery_codes=recovery_codes)
    response = JSONResponse(content=success_response(data=data.model_dump()))
    response.headers["Cache-Control"] = "no-store"
    return response


@router.post("/mfa/verify")
@limiter.limit("10/minute")
def verify_mfa(
    request: Request,
    body: MfaCodeRequest,
    current_user: dict = Depends(get_mfa_pending_user),
    db: Session = Depends(get_db),
):
    validate_request_origin(request)
    user = _pending_user(db, current_user)
    if user.mfa_enabled_at is None or user.mfa_secret_ciphertext is None:
        raise AppException("MFA enrollment required", status.HTTP_409_CONFLICT)
    secret = mfa_service.decrypt_secret(
        user.mfa_secret_ciphertext, user_id=str(user.id)
    )
    upgrade_secret_envelope = mfa_service.needs_envelope_upgrade(
        user.mfa_secret_ciphertext
    )
    counter = mfa_service.matching_totp_counter(secret, body.code)
    replayed_totp = counter is not None and (
        user.mfa_last_totp_counter is not None
        and counter <= user.mfa_last_totp_counter
    )
    recovery_candidate = mfa_service.hash_recovery_code(body.code)
    legacy_recovery_candidate = mfa_service.hash_legacy_recovery_code(body.code)
    stored_hashes = list(user.mfa_recovery_code_hashes or [])
    recovery_hash = mfa_service.find_recovery_hash(
        recovery_candidate,
        stored_hashes,
        legacy_candidate=legacy_recovery_candidate,
    )
    if (counter is None or replayed_totp) and recovery_hash is None:
        _reject_mfa(db, current_user)
    recovery_used = recovery_hash is not None
    if recovery_hash is not None:
        stored_hashes.remove(recovery_hash)
        user.mfa_recovery_code_hashes = stored_hashes
    else:
        user.mfa_last_totp_counter = counter
    if upgrade_secret_envelope:
        user.mfa_secret_ciphertext = mfa_service.encrypt_secret(
            secret, user_id=str(user.id)
        )
    _complete_mfa(db, current_user)
    db.commit()
    data = MfaVerifyResponse(
        user=_user_info(user), recovery_code_used=recovery_used
    )
    response = JSONResponse(content=success_response(data=data.model_dump()))
    response.headers["Cache-Control"] = "no-store"
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

    data = UserResponse(id=str(user.id), email=str(user.email), plan=str(user.plan), is_admin=bool(user.is_admin))
    return success_response(data=data.model_dump())
