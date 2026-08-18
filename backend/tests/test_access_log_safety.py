"""Tests for OAuth callback Uvicorn access-log isolation."""

from __future__ import annotations

import io
import logging

import pytest

from app.core import access_log_safety as access_log_safety_module
from app.core.access_log_safety import (
    OAuthCallbackAccessLogFilter,
    install_uvicorn_oauth_callback_access_log_filter,
    is_oauth_callback_access_log_record,
)

STATE_CANARY = "state-canary-secret"
CODE_CANARY = "oauth-code-canary-secret"
SELLER_CANARY = "seller-canary-secret"
DESCRIPTION_CANARY = "description-canary-secret"
CALLBACK_PATH = "/api/v1/amazon/oauth/callback"
CALLBACK_QUERY = (
    f"{CALLBACK_PATH}?state={STATE_CANARY}"
    f"&spapi_oauth_code={CODE_CANARY}"
    f"&selling_partner_id={SELLER_CANARY}"
    f"&error=access_denied&error_description={DESCRIPTION_CANARY}"
)


def _access_record(
    *,
    args: tuple[object, ...] | None = None,
    msg: str = '%s - "%s %s HTTP/%s" %s',
    name: str = "uvicorn.access",
) -> logging.LogRecord:
    return logging.LogRecord(
        name=name,
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=args,
        exc_info=None,
    )


def _callback_args() -> tuple[object, ...]:
    return (
        "127.0.0.1:54321",
        "GET",
        CALLBACK_QUERY,
        "1.1",
        303,
    )


@pytest.fixture(autouse=True)
def _reset_access_log_filter_install_flag():
    access_log_safety_module._installed = False
    logger = logging.getLogger("uvicorn.access")
    for filt in list(logger.filters):
        if isinstance(filt, OAuthCallbackAccessLogFilter):
            logger.removeFilter(filt)
    yield
    access_log_safety_module._installed = False
    for filt in list(logger.filters):
        if isinstance(filt, OAuthCallbackAccessLogFilter):
            logger.removeFilter(filt)


def test_callback_access_record_from_args_is_suppressed():
    record = _access_record(args=_callback_args())
    assert is_oauth_callback_access_log_record(record) is True
    assert OAuthCallbackAccessLogFilter().filter(record) is False


def test_callback_access_record_from_formatted_message_is_suppressed():
    record = _access_record(
        msg=(
            '127.0.0.1:54321 - "GET '
            f"{CALLBACK_QUERY} HTTP/1.1\" 303"
        ),
        args=(),
    )
    assert is_oauth_callback_access_log_record(record) is True
    assert OAuthCallbackAccessLogFilter().filter(record) is False


def test_normal_api_access_record_is_not_suppressed():
    record = _access_record(
        args=("127.0.0.1:54321", "GET", "/api/v1/amazon/accounts", "1.1", 200),
    )
    assert is_oauth_callback_access_log_record(record) is False
    assert OAuthCallbackAccessLogFilter().filter(record) is True


def test_similar_non_exact_callback_path_is_not_suppressed():
    record = _access_record(
        args=(
            "127.0.0.1:54321",
            "GET",
            f"{CALLBACK_PATH}/extra?state={STATE_CANARY}",
            "1.1",
            404,
        ),
    )
    assert is_oauth_callback_access_log_record(record) is False


def test_malformed_callback_record_fail_closed_without_leak(caplog: pytest.LogCaptureFixture):
    record = _access_record(
        msg="partial callback access record",
        args=(CALLBACK_PATH, f"state={STATE_CANARY}"),
    )
    filt = OAuthCallbackAccessLogFilter()
    with caplog.at_level(logging.DEBUG):
        assert filt.filter(record) is False
    assert STATE_CANARY not in caplog.text
    assert CODE_CANARY not in caplog.text


def test_malformed_non_callback_record_is_allowed():
    record = _access_record(msg="unrelated access record", args=("127.0.0.1",))
    assert OAuthCallbackAccessLogFilter().filter(record) is True


def test_filter_install_is_idempotent():
    logger = logging.getLogger("uvicorn.access")
    install_uvicorn_oauth_callback_access_log_filter()
    after_first = sum(isinstance(f, OAuthCallbackAccessLogFilter) for f in logger.filters)
    install_uvicorn_oauth_callback_access_log_filter()
    after_second = sum(isinstance(f, OAuthCallbackAccessLogFilter) for f in logger.filters)
    assert after_first == 1
    assert after_second == 1


def test_callback_access_record_never_reaches_handler_output():
    logger = logging.getLogger("uvicorn.access")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    logger.addFilter(OAuthCallbackAccessLogFilter())

    logger.info('%s - "%s %s HTTP/%s" %s', *_callback_args())
    logger.info('%s - "%s %s HTTP/%s" %s', "127.0.0.1:54321", "GET", "/api/v1/health", "1.1", 200)

    output = stream.getvalue()
    assert STATE_CANARY not in output
    assert CODE_CANARY not in output
    assert SELLER_CANARY not in output
    assert DESCRIPTION_CANARY not in output
    assert "/api/v1/health" in output

    logger.removeHandler(handler)
    logger.propagate = True
