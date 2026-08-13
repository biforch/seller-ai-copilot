from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings


def rate_limit_key(request) -> str:
    """Resolve the rate-limit bucket key for a request."""
    if settings.ENVIRONMENT == "testing":
        test_ip = request.headers.get("X-Test-Client-IP")
        if test_ip:
            return test_ip.strip()
    return get_remote_address(request)


limiter = Limiter(key_func=rate_limit_key)
