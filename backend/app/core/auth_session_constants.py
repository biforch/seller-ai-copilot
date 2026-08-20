"""Stable auth session and CSRF error codes (public messages only)."""

AUTH_SESSION_INVALID = "AUTH_SESSION_INVALID"
AUTH_CSRF_INVALID = "AUTH_CSRF_INVALID"
AUTH_ORIGIN_INVALID = "AUTH_ORIGIN_INVALID"

AUTH_SESSION_INVALID_MESSAGE = "Authentication required."
AUTH_CSRF_INVALID_MESSAGE = "Request rejected."
AUTH_ORIGIN_INVALID_MESSAGE = "Request rejected."

SESSION_COOKIE_NAME = "sellerai_session"
CSRF_COOKIE_NAME = "sellerai_csrf"
CSRF_HEADER_NAME = "X-CSRF-Token"

OAUTH_CALLBACK_PATH = "/api/v1/amazon/oauth/callback"
CSRF_EXEMPT_PATHS = frozenset(
    {
        "/api/v1/auth/login",
        "/api/v1/auth/register",
    }
)
