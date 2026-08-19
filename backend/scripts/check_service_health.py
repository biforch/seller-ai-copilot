"""Credential-free liveness/readiness probe for an RC or production edge."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from urllib.error import HTTPError
from urllib.parse import urlparse, urlunparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

MAX_RESPONSE_BYTES = 64 * 1024
DEFAULT_TIMEOUT_SECONDS = 5.0
SUCCESS_MESSAGE = "service-health-ok"
FAILURE_MESSAGE = "SERVICE_HEALTH_CHECK_FAILED"


class HealthCheckError(Exception):
    pass


@dataclass(frozen=True)
class HealthResponse:
    status_code: int
    body: bytes


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def _validated_base_url(value: str) -> str:
    if not isinstance(value, str) or value != value.strip():
        raise HealthCheckError()
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise HealthCheckError()
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"}:
        raise HealthCheckError()
    if not parsed.hostname or parsed.username or parsed.password:
        raise HealthCheckError()
    if parsed.query or parsed.fragment or parsed.params:
        raise HealthCheckError()
    if parsed.path not in {"", "/"}:
        raise HealthCheckError()
    return urlunparse((parsed.scheme, parsed.netloc, "", "", "", ""))


def _default_fetch(url: str, timeout: float) -> HealthResponse:
    opener = build_opener(_RejectRedirects())
    request = Request(url, headers={"Accept": "application/json"})
    try:
        with opener.open(request, timeout=timeout) as response:
            content_length = response.headers.get("Content-Length")
            if content_length is not None and int(content_length) > MAX_RESPONSE_BYTES:
                raise HealthCheckError()
            body = response.read(MAX_RESPONSE_BYTES + 1)
            if len(body) > MAX_RESPONSE_BYTES:
                raise HealthCheckError()
            return HealthResponse(status_code=response.status, body=body)
    except (HTTPError, OSError, ValueError):
        raise HealthCheckError() from None


def _validate_health_response(response: HealthResponse, *, expected_status: str) -> None:
    if response.status_code != 200:
        raise HealthCheckError()
    try:
        payload = json.loads(response.body)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
        raise HealthCheckError() from None
    if not isinstance(payload, dict) or payload.get("code") != 200:
        raise HealthCheckError()
    data = payload.get("data")
    if not isinstance(data, dict) or data.get("status") != expected_status:
        raise HealthCheckError()


def check_service_health(
    base_url: str,
    *,
    fetch: Callable[[str, float], HealthResponse] = _default_fetch,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> None:
    normalized = _validated_base_url(base_url)
    if timeout <= 0 or timeout > 30:
        raise HealthCheckError()
    for path, expected_status in (("/health", "healthy"), ("/health/ready", "ready")):
        response = fetch(f"{normalized}{path}", timeout)
        _validate_health_response(response, expected_status=expected_status)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print(FAILURE_MESSAGE, file=sys.stderr)
        return 1
    try:
        check_service_health(args[0])
    except Exception:
        print(FAILURE_MESSAGE, file=sys.stderr)
        return 1
    print(SUCCESS_MESSAGE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
