from typing import Any

from app.schemas.common import ApiResponse


def success_response(
    data: Any = None,
    message: str = "success",
    code: int = 200,
) -> dict:
    """构建统一成功响应."""
    return ApiResponse(code=code, message=message, data=data).model_dump()
