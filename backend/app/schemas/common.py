from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """统一成功响应格式."""

    code: int = 200
    message: str = "success"
    data: T | None = None


class ErrorResponse(BaseModel):
    """统一错误响应格式."""

    code: int
    message: str
    detail: str | None = None
    error_code: str | None = None
