import re

from pydantic import BaseModel, EmailStr, field_validator

PASSWORD_MIN_LENGTH = 12
PASSWORD_MAX_LENGTH = 128


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if len(v) < PASSWORD_MIN_LENGTH:
            raise ValueError(f"Password must be at least {PASSWORD_MIN_LENGTH} characters")
        if len(v) > PASSWORD_MAX_LENGTH:
            raise ValueError(f"Password must be at most {PASSWORD_MAX_LENGTH} characters")
        if not re.search(r"[a-z]", v):
            raise ValueError("Password must contain a lowercase letter")
        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain an uppercase letter")
        if not re.search(r"\d", v):
            raise ValueError("Password must contain a number")
        if not re.search(r"[^A-Za-z0-9]", v):
            raise ValueError("Password must contain a special character")
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
    token_type: str = "cookie"
    user: UserInfo | None = None
    mfa_required: bool = True
    mfa_enrollment_required: bool


class MfaCodeRequest(BaseModel):
    code: str

    @field_validator("code")
    @classmethod
    def validate_code(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or len(normalized) > 64:
            raise ValueError("Invalid MFA code")
        return normalized


class MfaSetupResponse(BaseModel):
    secret: str
    provisioning_uri: str


class MfaConfirmResponse(BaseModel):
    user: UserInfo
    recovery_codes: list[str]


class MfaVerifyResponse(BaseModel):
    user: UserInfo
    recovery_code_used: bool


class UserResponse(BaseModel):
    id: str
    email: str
    plan: str
