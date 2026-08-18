"""Suppress OAuth callback query strings from Uvicorn access logs."""

from __future__ import annotations

import logging
import re
from typing import Any

OAUTH_CALLBACK_ACCESS_PATH = "/api/v1/amazon/oauth/callback"
_UVICORN_ACCESS_LOGGER = "uvicorn.access"
_REQUEST_TARGET_RE = re.compile(r'"[A-Z]+ ([^ ]+) HTTP/')

_installed = False


def _record_text(record: logging.LogRecord) -> str:
    parts: list[str] = []
    try:
        parts.append(str(record.msg))
    except Exception:
        pass
    if record.args:
        try:
            parts.extend(str(arg) for arg in record.args)
        except Exception:
            pass
    return " ".join(parts)


def _path_only(request_target: str) -> str:
    return request_target.split("?", 1)[0]


def _request_target_from_args(args: Any) -> str | None:
    if not isinstance(args, tuple) or len(args) < 3:
        return None
    method = args[1]
    target = args[2]
    if not isinstance(method, str) or not isinstance(target, str):
        return None
    return target


def _request_target_from_message(message: str) -> str | None:
    match = _REQUEST_TARGET_RE.search(message)
    if match is None:
        return None
    return match.group(1)


def _extract_request_target(record: logging.LogRecord) -> str | None:
    target = _request_target_from_args(record.args)
    if target is not None:
        return target
    try:
        message = record.getMessage()
    except Exception:
        return None
    return _request_target_from_message(message)


def _contains_callback_path(record: logging.LogRecord) -> bool:
    return OAUTH_CALLBACK_ACCESS_PATH in _record_text(record)


def is_oauth_callback_access_log_record(record: logging.LogRecord) -> bool:
    """Return True when a uvicorn.access record must be suppressed."""
    if record.name != _UVICORN_ACCESS_LOGGER:
        return False

    request_target = _extract_request_target(record)
    if request_target is not None:
        return _path_only(request_target) == OAUTH_CALLBACK_ACCESS_PATH

    # Fail closed: unparsed callback-shaped access records must not reach handlers.
    return _contains_callback_path(record)


class OAuthCallbackAccessLogFilter(logging.Filter):
    """Drop uvicorn.access records for the OAuth callback path."""

    def filter(self, record: logging.LogRecord) -> bool:
        return not is_oauth_callback_access_log_record(record)


def install_uvicorn_oauth_callback_access_log_filter() -> None:
    """Install the callback access-log filter once on uvicorn.access."""
    global _installed
    logger = logging.getLogger(_UVICORN_ACCESS_LOGGER)
    if any(isinstance(filt, OAuthCallbackAccessLogFilter) for filt in logger.filters):
        _installed = True
        return
    logger.addFilter(OAuthCallbackAccessLogFilter())
    _installed = True
