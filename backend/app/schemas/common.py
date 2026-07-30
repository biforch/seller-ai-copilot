from typing import Any, Generic, Optional, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """统一成功响应格式."""

    code: int = 200
    message: str = "success"
    data: Optional[T] = None


class ErrorResponse(BaseModel):
    """统一错误响应格式."""

    code: int
    message: str
    detail: Optional[str] = None
