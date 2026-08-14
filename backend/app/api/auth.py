from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from app.core.exceptions import AppException
from app.core.rate_limit import limiter
from app.core.response import success_response
from app.core.security import (
    create_access_token,
    get_current_user,
    get_password_hash,
    verify_password,
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

router = APIRouter()


@router.post("/register")
@limiter.limit("10/minute")
def register(request: Request, body: RegisterRequest, db: Session = Depends(get_db)):
    """用户注册."""
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
    user = db.query(User).filter(User.email == body.email).first()
    if not user or not verify_password(body.password, str(user.password_hash)):
        raise AppException(
            "Invalid email or password",
            status.HTTP_401_UNAUTHORIZED,
        )

    access_token = create_access_token(data={"sub": str(user.id), "email": user.email})
    data = LoginResponse(
        access_token=access_token,
        token_type="bearer",
        user=UserInfo(id=str(user.id), email=str(user.email), plan=str(user.plan)),
    )
    return success_response(data=data.model_dump())


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
