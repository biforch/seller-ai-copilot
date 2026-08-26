"""Rate-limit bucket keys derived from validated cookie sessions."""

from __future__ import annotations

import hashlib

from fastapi import Request

from app.core.auth_session_constants import SESSION_COOKIE_NAME
from app.core.csrf import decode_session_jti, resolve_request_db
from app.core.rate_limit import rate_limit_key
from app.services.auth_session_service import auth_session_service

OAUTH_START_RATE_LIMIT_PREFIX = "oauth-start"
AMAZON_REFRESH_RATE_LIMIT_PREFIX = "amazon-refresh"
AMAZON_PRODUCT_SYNC_RATE_LIMIT_PREFIX = "amazon-product-sync"
LISTING_AUDIT_RATE_LIMIT_PREFIX = "listing-audit"


def _unauthenticated_session_bucket(request: Request, *, prefix: str, label: str) -> str:
    return f"{prefix}:{label}:{rate_limit_key(request)}"


def session_rate_limit_key(request: Request, *, prefix: str) -> str:
    """Use a validated session hash bucket; never trust raw cookie claims."""
    session_cookie = request.cookies.get(SESSION_COOKIE_NAME)
    if not session_cookie:
        return _unauthenticated_session_bucket(request, prefix=prefix, label="missing")

    jti = decode_session_jti(session_cookie)
    if jti is None:
        return _unauthenticated_session_bucket(request, prefix=prefix, label="invalid")

    with resolve_request_db(request) as db:
        session = auth_session_service.get_active_session(db, jti=jti)
        if session is None:
            return _unauthenticated_session_bucket(request, prefix=prefix, label="invalid")

        bucket = hashlib.sha256(session.jti_hash.encode("utf-8")).hexdigest()
        return f"{prefix}:session:{bucket}"


def oauth_start_rate_limit_key(request: Request) -> str:
    return session_rate_limit_key(request, prefix=OAUTH_START_RATE_LIMIT_PREFIX)


def amazon_refresh_rate_limit_key(request: Request) -> str:
    return session_rate_limit_key(request, prefix=AMAZON_REFRESH_RATE_LIMIT_PREFIX)


def amazon_product_sync_rate_limit_key(request: Request) -> str:
    return session_rate_limit_key(request, prefix=AMAZON_PRODUCT_SYNC_RATE_LIMIT_PREFIX)


def listing_audit_rate_limit_key(request: Request) -> str:
    return session_rate_limit_key(request, prefix=LISTING_AUDIT_RATE_LIMIT_PREFIX)
