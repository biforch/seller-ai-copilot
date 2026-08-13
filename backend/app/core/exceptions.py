import logging

from fastapi import Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import settings
from app.schemas.common import ErrorResponse

logger = logging.getLogger(__name__)

AI_RESPONSE_INVALID = "AI_RESPONSE_INVALID"
AI_PROVIDER_UNAVAILABLE = "AI_PROVIDER_UNAVAILABLE"
IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
GENERATION_IN_PROGRESS = "GENERATION_IN_PROGRESS"
GENERATION_FINALIZE_FAILED = "GENERATION_FINALIZE_FAILED"
GENERATION_UNRECOVERABLE = "GENERATION_UNRECOVERABLE"
QUOTA_EXCEEDED = "QUOTA_EXCEEDED"
AI_RESPONSE_INVALID_MESSAGE = (
    "The AI service returned an invalid response. Please try again."
)


class AppException(Exception):
    """应用自定义异常."""

    def __init__(
        self,
        message: str,
        code: int = status.HTTP_400_BAD_REQUEST,
        detail: str | None = None,
        cause: Exception | None = None,
        error_code: str | None = None,
    ):
        self.message = message
        self.code = code
        self.detail = detail
        self.cause = cause
        self.error_code = error_code

        super().__init__(message)

    def __str__(self):
        if self.detail:
            return self.detail
        return self.message


def ai_response_invalid_exception(cause: Exception | None = None) -> AppException:
    """Upstream LLM output could not be validated."""
    return AppException(
        message=AI_RESPONSE_INVALID_MESSAGE,
        code=status.HTTP_502_BAD_GATEWAY,
        error_code=AI_RESPONSE_INVALID,
        detail=None,
        cause=cause,
    )


def error_response(
    code: int,
    message: str,
    detail: str | None = None,
    error_code: str | None = None,
) -> dict:
    return ErrorResponse(
        code=code,
        message=message,
        detail=detail,
        error_code=error_code,
    ).model_dump()


def _error_response(
    code: int,
    message: str,
    detail: str | None = None,
    error_code: str | None = None,
) -> dict:
    return error_response(code, message, detail, error_code=error_code)


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
            error_code=exc.error_code,
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

    origin = request.headers.get("origin")

    if origin and (
        settings.cors_origins_list == ["*"]
        or origin in settings.cors_origins_list
    ):

        response.headers["Access-Control-Allow-Origin"] = origin

        response.headers["Access-Control-Allow-Credentials"] = "true"

        response.headers["Vary"] = "Origin"

    return response
