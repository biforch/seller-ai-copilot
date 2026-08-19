from __future__ import annotations

import json

import pytest

from scripts.check_service_health import (
    FAILURE_MESSAGE,
    SUCCESS_MESSAGE,
    HealthCheckError,
    HealthResponse,
    check_service_health,
    main,
)


def _response(status: str, *, status_code: int = 200) -> HealthResponse:
    return HealthResponse(
        status_code=status_code,
        body=json.dumps({"code": 200, "data": {"status": status}}).encode(),
    )


def test_health_and_readiness_are_checked_without_credentials() -> None:
    calls: list[tuple[str, float]] = []

    def fetch(url: str, timeout: float) -> HealthResponse:
        calls.append((url, timeout))
        return _response("ready" if url.endswith("/ready") else "healthy")

    check_service_health("https://seller.example", fetch=fetch)

    assert calls == [
        ("https://seller.example/health", 5.0),
        ("https://seller.example/health/ready", 5.0),
    ]


@pytest.mark.parametrize(
    "base_url",
    [
        "",
        " https://seller.example",
        "ftp://seller.example",
        "https://user:secret@seller.example",
        "https://seller.example/base",
        "https://seller.example?secret=canary",
        "https://seller.example#fragment",
        "https://seller.example\n.evil.test",
    ],
)
def test_unsafe_base_url_is_rejected_without_fetch(base_url: str) -> None:
    called = False

    def fetch(url: str, timeout: float) -> HealthResponse:
        nonlocal called
        called = True
        return _response("healthy")

    with pytest.raises(HealthCheckError):
        check_service_health(base_url, fetch=fetch)
    assert called is False


@pytest.mark.parametrize(
    "response",
    [
        HealthResponse(status_code=503, body=b"{}"),
        HealthResponse(status_code=200, body=b"not-json"),
        HealthResponse(status_code=200, body=b"[]"),
        HealthResponse(status_code=200, body=b'{"code":500,"data":{"status":"healthy"}}'),
        HealthResponse(status_code=200, body=b'{"code":200,"data":{"status":"wrong"}}'),
    ],
)
def test_malformed_or_unhealthy_response_fails_closed(response: HealthResponse) -> None:
    with pytest.raises(HealthCheckError):
        check_service_health("http://127.0.0.1:8080", fetch=lambda url, timeout: response)


def test_invalid_timeout_fails_before_fetch() -> None:
    with pytest.raises(HealthCheckError):
        check_service_health("http://127.0.0.1:8080", timeout=0)


def test_main_outputs_only_fixed_success(monkeypatch, capsys) -> None:
    monkeypatch.setattr("scripts.check_service_health.check_service_health", lambda url: None)
    assert main(["http://127.0.0.1:8080"]) == 0
    captured = capsys.readouterr()
    assert captured.out.strip() == SUCCESS_MESSAGE
    assert captured.err == ""


def test_main_redacts_url_and_exception(monkeypatch, capsys) -> None:
    canary = "canary-health-secret-do-not-leak"

    def fail(url: str) -> None:
        raise RuntimeError(canary)

    monkeypatch.setattr("scripts.check_service_health.check_service_health", fail)
    assert main([f"https://example.test?token={canary}"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == FAILURE_MESSAGE
    assert canary not in captured.err
