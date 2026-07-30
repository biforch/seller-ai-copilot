import logging

from typing import Optional

from fastapi import Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import settings
from app.schemas.common import ErrorResponse


logger = logging.getLogger(__name__)


class AppException(Exception):
    """应用自定义异常."""

    def __init__(
        self,
        message: str,
        code: int = status.HTTP_400_BAD_REQUEST,
        detail: Optional[str] = None,
        cause: Optional[Exception] = None,
    ):
        self.message = message
        self.code = code
        self.detail = detail
        self.cause = cause

        super().__init__(message)

    def __str__(self):
        if self.detail:
            return self.detail
        return self.message


def error_response(
    code: int,
    message: str,
    detail: Optional[str] = None,
) -> dict:
    return ErrorResponse(
        code=code,
        message=message,
        detail=detail,
    ).model_dump()


def _error_response(
    code: int,
    message: str,
    detail: Optional[str] = None,
) -> dict:
    return error_response(code, message, detail)


async def app_exception_handler(
    request: Request,
    exc: AppException,
) -> JSONResponse:
    return JSONResponse(
        status_code=exc.code,
        content=_error_response(
            exc.code,
            exc.message,
            exc.detail,
        ),
    )


async def http_exception_handler(
    request: Request,
    exc: StarletteHTTPException,
) -> JSONResponse:
    detail = (
        exc.detail
        if isinstance(exc.detail, str)
        else str(exc.detail)
    )

    return JSONResponse(
        status_code=exc.status_code,
        content=_error_response(
            exc.status_code,
            detail,
            detail,
        ),
    )


async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    errors = exc.errors()

    detail = "; ".join(
        f"{'.'.join(str(loc) for loc in e['loc'])}: {e['msg']}"
        for e in errors
    )

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=_error_response(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Validation Error",
            detail,
        ),
    )


async def unhandled_exception_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:

    # 完整堆栈打到后端日志，方便排查
    logger.exception(
        "Unhandled exception on %s %s",
        request.method,
        request.url.path,
    )

    detail = (
        str(exc)
        if settings.DEBUG
        else None
    )

    response = JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=_error_response(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "Internal Server Error",
            detail,
        ),
    )

    # 注意：这里注册的是裸 Exception，Starlette 会把它挂到
    # ServerErrorMiddleware（在 CORSMiddleware 外层），
    # 所以正常走完的响应不会经过 CORSMiddleware 加 CORS 头。
    # 不手动加的话，前端看到的会是一个具有迷惑性的 CORS 报错，
    # 而看不到真正的 500 原因（我们这周已经踩过两次这个坑）。
    origin = request.headers.get("origin")

    if origin and (
        settings.cors_origins_list == ["*"]
        or origin in settings.cors_origins_list
    ):

        response.headers["Access-Control-Allow-Origin"] = origin

        response.headers["Access-Control-Allow-Credentials"] = "true"

        response.headers["Vary"] = "Origin"

    return response