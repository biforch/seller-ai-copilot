import re

from pydantic import BaseModel, EmailStr, field_validator


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        if not re.search(r"[A-Za-z]", v):
            raise ValueError("Password must contain letters")
        if not re.search(r"\d", v):
            raise ValueError("Password must contain numbers")
        return v


class RegisterResponse(BaseModel):
    id: str
    email: str
    plan: str
    message: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserInfo(BaseModel):
    id: str
    email: str
    plan: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str
    user: UserInfo


class CookieLoginResponse(BaseModel):
    token_type: str = "cookie"
    user: UserInfo


class UserResponse(BaseModel):
    id: str
    email: str
    plan: str
