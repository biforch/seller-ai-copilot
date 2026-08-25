"""Fail-closed redaction for application-managed log handlers."""

from __future__ import annotations

import logging
import traceback as traceback_module
from collections.abc import Mapping
from typing import Any

from app.core.logging_utils import redact_sensitive_text

_FILTERED_LOGGERS = ("uvicorn", "uvicorn.error")
_REDACTION_FAILURE_MESSAGE = "[REDACTED_LOG_RECORD]"


def _redact_value(value: Any) -> Any:
    if isinstance(value, str):
        return redact_sensitive_text(value)
    if isinstance(value, tuple):
        return tuple(_redact_value(item) for item in value)
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    if isinstance(value, Mapping):
        return {key: _redact_value(item) for key, item in value.items()}
    return value


def _redact_exception_info(record: logging.LogRecord) -> None:
    if record.exc_info is None:
        return
    exc_type, exc_value, traceback = record.exc_info
    if exc_type is None or exc_value is None:
        raise ValueError("invalid exception info")
    safe_args = tuple(_redact_value(arg) for arg in getattr(exc_value, "args", ()))
    try:
        safe_exception = exc_type(*safe_args)
    except Exception:
        safe_exception = Exception(*(safe_args or ("redacted exception",)))
    record.exc_info = (type(safe_exception), safe_exception, traceback)
    formatted = "".join(traceback_module.format_exception(*record.exc_info))
    record.exc_text = redact_sensitive_text(formatted)


class SensitiveDataLogFilter(logging.Filter):
    """Redact known secrets before formatting; suppress raw data on any failure."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            # Render first so a sensitive label in msg protects an otherwise opaque
            # positional value (for example: logger.info("password=%s", value)).
            record.msg = redact_sensitive_text(record.getMessage())
            record.args = ()
            _redact_exception_info(record)
        except Exception:
            record.msg = _REDACTION_FAILURE_MESSAGE
            record.args = ()
            record.exc_info = None
            record.exc_text = None
        return True


def _install_on_handler(handler: logging.Handler) -> None:
    if not any(isinstance(item, SensitiveDataLogFilter) for item in handler.filters):
        handler.addFilter(SensitiveDataLogFilter())


def install_sensitive_data_log_filter() -> None:
    """Attach redaction once to active root and Uvicorn error-log handlers."""
    targets = (logging.getLogger(), *(logging.getLogger(name) for name in _FILTERED_LOGGERS))
    for target in targets:
        for handler in target.handlers:
            _install_on_handler(handler)
