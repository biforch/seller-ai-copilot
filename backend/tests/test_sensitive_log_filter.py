import logging

import pytest

from app.core.log_filter import SensitiveDataLogFilter, install_sensitive_data_log_filter


def _record(*, msg: object, args: object = (), exc_info=None) -> logging.LogRecord:
    return logging.LogRecord(
        name="app.test",
        level=logging.WARNING,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=args,
        exc_info=exc_info,
    )


def test_sensitive_log_filter_redacts_message_and_arguments():
    record = _record(
        msg="callback=%s authorization=%s",
        args=(
            "/api/v1/amazon/oauth/callback?state=state-canary&spapi_oauth_code=code-canary",
            "Bearer token-canary",
        ),
    )
    assert SensitiveDataLogFilter().filter(record) is True
    rendered = record.getMessage()
    assert "state-canary" not in rendered
    assert "code-canary" not in rendered
    assert "token-canary" not in rendered
    assert "[REDACTED]" in rendered


def test_sensitive_log_filter_redacts_nested_mapping_arguments():
    record = _record(msg="payload=%s", args=({"refresh_token": "refresh_token=canary"},))
    SensitiveDataLogFilter().filter(record)
    assert "canary" not in record.getMessage()


def test_sensitive_log_filter_redacts_opaque_positional_secret_from_message_context():
    record = _record(msg="password=%s", args=("opaque-password-canary",))
    SensitiveDataLogFilter().filter(record)
    assert record.getMessage() == "password=[REDACTED]"
    assert "opaque-password-canary" not in record.getMessage()


def test_sensitive_log_filter_redacts_exception_arguments():
    try:
        raise RuntimeError("Bearer exception-token-canary")
    except RuntimeError as exc:
        record = _record(msg="request failed", exc_info=(type(exc), exc, exc.__traceback__))

    SensitiveDataLogFilter().filter(record)
    rendered = logging.Formatter("%(message)s").format(record)
    assert "exception-token-canary" not in rendered
    assert "Bearer [REDACTED]" in rendered


def test_sensitive_log_filter_fails_closed_when_redaction_raises(monkeypatch):
    def fail(_text: str) -> str:
        raise RuntimeError("redactor-secret-canary")

    monkeypatch.setattr("app.core.log_filter.redact_sensitive_text", fail)
    record = _record(msg="Bearer raw-secret-canary")
    assert SensitiveDataLogFilter().filter(record) is True
    assert record.getMessage() == "[REDACTED_LOG_RECORD]"
    assert "raw-secret-canary" not in record.getMessage()


def test_filter_installation_is_idempotent():
    logger = logging.getLogger()
    handler = logging.Handler()
    logger.addHandler(handler)
    try:
        install_sensitive_data_log_filter()
        install_sensitive_data_log_filter()
        filters = [item for item in handler.filters if isinstance(item, SensitiveDataLogFilter)]
        assert len(filters) == 1
    finally:
        logger.removeHandler(handler)


@pytest.mark.parametrize("logger_name", ["uvicorn", "uvicorn.error"])
def test_filter_installs_on_existing_uvicorn_handlers(logger_name: str):
    logger = logging.getLogger(logger_name)
    handler = logging.Handler()
    logger.addHandler(handler)
    try:
        install_sensitive_data_log_filter()
        assert any(isinstance(item, SensitiveDataLogFilter) for item in handler.filters)
    finally:
        logger.removeHandler(handler)
