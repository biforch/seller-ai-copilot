"""Rate-limit bucket keys derived from validated cookie sessions."""

from __future__ import annotations

import hashlib

from fastapi import Request

from app.core.auth_session_constants import SESSION_COOKIE_NAME
from app.core.csrf import decode_session_jti, resolve_request_db
from app.core.rate_limit import rate_limit_key
from app.services.auth_session_service import auth_session_service


def _anonymous_oauth_start_bucket(request: Request, label: str) -> str:
    return f"oauth-start:{label}:{rate_limit_key(request)}"


def oauth_start_rate_limit_key(request: Request) -> str:
    """Use a validated session hash bucket; never trust raw cookie claims."""
    session_cookie = request.cookies.get(SESSION_COOKIE_NAME)
    if not session_cookie:
        return _anonymous_oauth_start_bucket(request, "missing")

    jti = decode_session_jti(session_cookie)
    if jti is None:
        return _anonymous_oauth_start_bucket(request, "invalid")

    with resolve_request_db(request) as db:
        session = auth_session_service.get_active_session(db, jti=jti)
        if session is None:
            return _anonymous_oauth_start_bucket(request, "invalid")

        bucket = hashlib.sha256(session.jti_hash.encode("utf-8")).hexdigest()
        return f"oauth-start:session:{bucket}"
