"""CSRF and Origin validation for cookie-authenticated mutating requests."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from urllib.parse import urlparse

from fastapi import Request
from fastapi.responses import JSONResponse
from jose import JWTError, jwt
from sqlalchemy.orm import Session
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.auth_session_constants import (
    CSRF_COOKIE_NAME,
    CSRF_EXEMPT_PATHS,
    CSRF_HEADER_NAME,
    OAUTH_CALLBACK_PATH,
    SESSION_COOKIE_NAME,
)
from app.core.auth_session_tokens import secrets_equal
from app.core.config import settings
from app.core.exceptions import (
    AppException,
    _error_response,
    auth_csrf_invalid_exception,
    auth_origin_invalid_exception,
    auth_session_invalid_exception,
)
from app.database.session import SessionLocal, get_db
from app.services.auth_session_service import auth_session_service


def extract_request_origin(request: Request) -> str | None:
    origin = request.headers.get("origin")
    if origin:
        return origin.strip()
    referer = request.headers.get("referer")
    if not referer:
        return None
    parsed = urlparse(referer.strip())
    if not parsed.scheme or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}"


def origin_is_allowed(origin: str | None) -> bool:
    if not origin:
        return False
    allowed = settings.cors_origins_list
    if allowed == ["*"]:
        return True
    return origin in allowed


def _decode_session_jti(session_cookie: str) -> str | None:
    try:
        payload = jwt.decode(
            session_cookie,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
    except JWTError:
        return None
    jti = payload.get("jti")
    if not isinstance(jti, str) or not jti:
        return None
    return jti


def validate_cookie_csrf(request: Request, db: Session) -> None:
    csrf_cookie = request.cookies.get(CSRF_COOKIE_NAME)
    csrf_header = request.headers.get(CSRF_HEADER_NAME)
    if not csrf_cookie or not csrf_header:
        raise auth_csrf_invalid_exception()

    if not secrets_equal(csrf_cookie, csrf_header):
        raise auth_csrf_invalid_exception()

    session_cookie = request.cookies.get(SESSION_COOKIE_NAME)
    if not session_cookie:
        raise auth_csrf_invalid_exception()

    jti = _decode_session_jti(session_cookie)
    if jti is None:
        raise auth_session_invalid_exception()

    auth_session_service.validate_csrf_for_session(db, jti=jti, csrf_token=csrf_header)

    origin = extract_request_origin(request)
    if not origin_is_allowed(origin):
        raise auth_origin_invalid_exception()


def uses_bearer_authorization(request: Request) -> bool:
    authorization = request.headers.get("authorization", "")
    return authorization.lower().startswith("bearer ")


def should_enforce_csrf(request: Request) -> bool:
    if not settings.COOKIE_SESSION_ENABLED:
        return False
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return False
    if request.url.path in CSRF_EXEMPT_PATHS:
        return False
    if request.url.path == OAUTH_CALLBACK_PATH:
        return False
    if uses_bearer_authorization(request):
        return False
    if not request.cookies.get(SESSION_COOKIE_NAME):
        return False
    return True


@contextmanager
def resolve_request_db(request: Request) -> Iterator[Session]:
    override = request.app.dependency_overrides.get(get_db)
    if override is not None:
        db = next(override())
        try:
            yield db
        finally:
            try:
                next(override())
            except StopIteration:
                pass
    else:
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()


class CookieCsrfMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        from starlette.requests import Request as StarletteRequest

        request = StarletteRequest(scope, receive)

        if should_enforce_csrf(request):
            try:
                with resolve_request_db(request) as db:
                    validate_cookie_csrf(request, db)
            except AppException as exc:
                response = JSONResponse(
                    status_code=exc.code,
                    content=_error_response(
                        exc.code,
                        exc.message,
                        None,
                        error_code=exc.error_code,
                    ),
                )
                await response(scope, receive, send)
                return

        await self.app(scope, receive, send)
