"""Session-scoped Amazon rate-limit buckets after cookie-only auth."""

from __future__ import annotations

import inspect
import logging
from pathlib import Path

import pytest
from jose import jwt
from starlette.requests import Request

from app.core.auth_session_constants import CSRF_COOKIE_NAME, SESSION_COOKIE_NAME
from app.core.config import settings
from app.core.oauth_rate_limit import (
    AMAZON_PRODUCT_SYNC_RATE_LIMIT_PREFIX,
    AMAZON_REFRESH_RATE_LIMIT_PREFIX,
    amazon_product_sync_rate_limit_key,
    amazon_refresh_rate_limit_key,
    oauth_start_rate_limit_key,
    session_rate_limit_key,
)
from app.core.security import decode_session_cookie
from app.main import app
from app.services.auth_session_service import auth_session_service

LOGIN_URL = "/api/v1/auth/login"
TEST_ORIGIN = "http://localhost:3000"
CANARY_COOKIE = "canary.jwt.token.value.must-not-leak"
CANARY_BEARER = "Bearer canary-authorization-header-must-not-leak"
BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _cookie_login(client, email: str, password: str = "Password1"):
    return client.post(
        LOGIN_URL,
        json={"email": email, "password": password},
        headers={"Origin": TEST_ORIGIN},
    )


def _snapshot_cookies(client) -> dict[str, str]:
    return {key: value for key, value in client.cookies.items()}


def _http_request(
    cookies: dict[str, str],
    extra_headers: dict[str, str] | None = None,
) -> Request:
    header_list: list[tuple[bytes, bytes]] = []
    if cookies:
        cookie_header = "; ".join(f"{key}={value}" for key, value in cookies.items())
        header_list.append((b"cookie", cookie_header.encode("latin-1")))
    for name, value in (extra_headers or {}).items():
        header_list.append((name.lower().encode("latin-1"), value.encode("latin-1")))
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/",
            "raw_path": b"/",
            "query_string": b"",
            "headers": header_list,
            "client": ("127.0.0.1", 50000),
            "server": ("testserver", 80),
            "app": app,
        }
    )


def _assert_key_hides_canaries(key: str, *, cookies: dict[str, str], user_id: str) -> None:
    session_cookie = cookies[SESSION_COOKIE_NAME]
    payload = jwt.decode(
        session_cookie,
        settings.JWT_SECRET_KEY,
        algorithms=[settings.JWT_ALGORITHM],
    )
    jti = payload["jti"]
    assert isinstance(jti, str)
    assert session_cookie not in key
    assert cookies.get(CSRF_COOKIE_NAME, "") not in key
    assert user_id not in key
    assert jti not in key
    assert CANARY_COOKIE not in key
    assert CANARY_BEARER not in key
    assert "authorization" not in key.lower()


def test_production_limiters_do_not_hash_authorization_headers() -> None:
    listings_source = (BACKEND_ROOT / "app/api/amazon_listings.py").read_text(encoding="utf-8")
    marketplaces_source = (BACKEND_ROOT / "app/api/amazon_marketplaces.py").read_text(
        encoding="utf-8"
    )
    oauth_source = inspect.getsource(oauth_start_rate_limit_key)
    refresh_source = inspect.getsource(amazon_refresh_rate_limit_key)
    sync_source = inspect.getsource(amazon_product_sync_rate_limit_key)
    helper_source = inspect.getsource(session_rate_limit_key)

    assert "request.headers.get(\"authorization\"" not in listings_source
    assert "request.headers.get(\"authorization\"" not in marketplaces_source
    for source in (oauth_source, refresh_source, sync_source, helper_source):
        assert "authorization" not in source.lower()


@pytest.mark.parametrize(
    ("key_func", "prefix"),
    [
        (amazon_refresh_rate_limit_key, AMAZON_REFRESH_RATE_LIMIT_PREFIX),
        (amazon_product_sync_rate_limit_key, AMAZON_PRODUCT_SYNC_RATE_LIMIT_PREFIX),
    ],
)
def test_valid_cookie_sessions_use_isolated_stable_buckets(
    client,
    user_factory,
    key_func,
    prefix,
    caplog: pytest.LogCaptureFixture,
):
    first = user_factory(f"{prefix}-a@example.com")
    second = user_factory(f"{prefix}-b@example.com")

    assert _cookie_login(client, first.email).status_code == 200
    first_cookies = _snapshot_cookies(client)
    first_request = _http_request(first_cookies)

    assert _cookie_login(client, second.email).status_code == 200
    second_cookies = _snapshot_cookies(client)
    second_request = _http_request(second_cookies)

    with caplog.at_level(logging.DEBUG):
        first_key = key_func(first_request)
        first_again = key_func(first_request)
        second_key = key_func(second_request)
        bearer_key = key_func(
            _http_request(first_cookies, extra_headers={"Authorization": CANARY_BEARER})
        )

    assert first_key == first_again
    assert first_key != second_key
    assert first_key == bearer_key
    assert first_key.startswith(f"{prefix}:session:")
    assert second_key.startswith(f"{prefix}:session:")
    _assert_key_hides_canaries(first_key, cookies=first_cookies, user_id=str(first.id))
    _assert_key_hides_canaries(second_key, cookies=second_cookies, user_id=str(second.id))
    joined = caplog.text + first_key + second_key
    assert first_cookies[SESSION_COOKIE_NAME] not in joined
    assert second_cookies[SESSION_COOKIE_NAME] not in joined
    assert CANARY_BEARER not in joined
    assert str(first.id) not in joined
    assert str(second.id) not in joined


@pytest.mark.parametrize(
    "key_func",
    [amazon_refresh_rate_limit_key, amazon_product_sync_rate_limit_key],
)
def test_invalid_cookie_does_not_consume_valid_session_bucket(
    client,
    user_factory,
    db_session,
    key_func,
    caplog: pytest.LogCaptureFixture,
):
    user = user_factory("session-rate-invalid@example.com")
    assert _cookie_login(client, user.email).status_code == 200
    valid_cookies = _snapshot_cookies(client)
    session_cookie = valid_cookies[SESSION_COOKIE_NAME]
    payload = decode_session_cookie(session_cookie)
    jti = payload["jti"]
    assert isinstance(jti, str)

    valid_key = key_func(_http_request(valid_cookies))
    missing_key = key_func(_http_request({}))
    canary_cookies = {**valid_cookies, SESSION_COOKIE_NAME: CANARY_COOKIE}
    invalid_cookie_key = key_func(_http_request(canary_cookies))

    auth_session_service.revoke_session(db_session, jti=jti)
    db_session.commit()
    revoked_key = key_func(_http_request(valid_cookies))

    with caplog.at_level(logging.WARNING):
        still_revoked = key_func(_http_request(valid_cookies))

    assert ":session:" in valid_key
    assert invalid_cookie_key != valid_key
    assert revoked_key != valid_key
    assert ":invalid:" in invalid_cookie_key
    assert ":invalid:" in revoked_key
    assert ":missing:" in missing_key
    assert still_revoked == revoked_key
    joined = caplog.text + invalid_cookie_key + revoked_key + missing_key
    assert CANARY_COOKIE not in joined
    assert session_cookie not in joined
    assert jti not in joined
    assert str(user.id) not in joined
    assert CANARY_COOKIE not in invalid_cookie_key
