"""Static and environment-contract tests for the isolated Vultr adapter."""

from __future__ import annotations

import base64
import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from scripts.validate_vultr_production_environment import (  # noqa: E402
    SUCCESS_MESSAGE,
    VultrProductionEnvironmentError,
    validate_vultr_production_environment,
)

VALID_ENV = {
    "ENVIRONMENT": "production",
    "DATABASE_URL": "postgresql://app:placeholder@postgres:5432/listnara_prod",
    "JWT_SECRET_KEY": "j" * 32,
    "MFA_ENCRYPTION_KEY": base64.b64encode(b"m" * 32).decode("ascii"),
    "OPENAI_API_KEY": "provider-key-placeholder",
    "OPENAI_BASE_URL": "https://openrouter.ai/api/v1",
    "OPENAI_MODEL": "openai/gpt-5.4-mini",
    "OPENAI_AMAZON_DATA_ENABLED": "false",
    "CORS_ORIGINS": "https://app.listnara.com",
    "SESSION_COOKIE_SECURE": "true",
    "DEBUG": "false",
    "LEGACY_GENERATION_ENABLED": "false",
    "ANALYSIS_PUBLIC_ENABLED": "false",
    "LISTING_AUDIT_INTERNAL_ENABLED": "true",
    "AMAZON_SP_API_ENABLED": "false",
    "AMAZON_OAUTH_ENABLED": "false",
    "AMAZON_SP_API_ENDPOINT_MODE": "mock",
}


def _set_env(monkeypatch: pytest.MonkeyPatch, updates: dict[str, str] | None = None) -> None:
    values = deepcopy(VALID_ENV)
    values.update(updates or {})
    for key, value in values.items():
        monkeypatch.setenv(key, value)


def test_valid_vultr_environment_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_env(monkeypatch)
    validate_vultr_production_environment()


@pytest.mark.parametrize(
    ("name", "value", "reason"),
    [
        ("ENVIRONMENT", "staging", "ENVIRONMENT_NOT_PRODUCTION"),
        ("DATABASE_URL", "postgresql://app:x@localhost:5432/prod", "DATABASE_TARGET_INVALID"),
        ("DATABASE_URL", "postgresql://app:x@postgres:5432/listnara_test", "DATABASE_TARGET_INVALID"),
        ("JWT_SECRET_KEY", "short", "JWT_SECRET_TOO_SHORT"),
        ("MFA_ENCRYPTION_KEY", "not-base64", "MFA_KEY_INVALID_BASE64"),
        ("OPENAI_BASE_URL", "https://example.com/v1", "OPENAI_BASE_URL_INVALID"),
        ("OPENAI_AMAZON_DATA_ENABLED", "true", "AMAZON_AI_DATA_MUST_REMAIN_DISABLED"),
        ("CORS_ORIGINS", "*", "CORS_ORIGIN_INVALID"),
        ("SESSION_COOKIE_SECURE", "false", "SESSION_COOKIE_NOT_SECURE"),
        ("DEBUG", "true", "DEBUG_NOT_FALSE"),
        ("LEGACY_GENERATION_ENABLED", "true", "LEGACY_GENERATION_MUST_REMAIN_DISABLED"),
        ("ANALYSIS_PUBLIC_ENABLED", "true", "ANALYSIS_PUBLIC_MUST_REMAIN_DISABLED"),
        (
            "LISTING_AUDIT_INTERNAL_ENABLED",
            "false",
            "LISTING_AUDIT_INTERNAL_MUST_BE_ENABLED",
        ),
        ("AMAZON_SP_API_ENABLED", "true", "AMAZON_MUST_REMAIN_DISABLED"),
        ("AMAZON_OAUTH_ENABLED", "true", "AMAZON_MUST_REMAIN_DISABLED"),
        ("AMAZON_SP_API_ENDPOINT_MODE", "production", "AMAZON_ENDPOINT_NOT_MOCK"),
    ],
)
def test_unsafe_environment_is_rejected(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str, reason: str
) -> None:
    _set_env(monkeypatch, {name: value})
    with pytest.raises(VultrProductionEnvironmentError, match=reason):
        validate_vultr_production_environment()


def test_cli_failure_does_not_echo_secret() -> None:
    env = {**os.environ, **VALID_ENV, "OPENAI_API_KEY": "canary-secret-do-not-print"}
    env["CORS_ORIGINS"] = "https://invalid.example"
    result = subprocess.run(
        [sys.executable, str(BACKEND_ROOT / "scripts/validate_vultr_production_environment.py")],
        cwd=BACKEND_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "canary-secret-do-not-print" not in result.stdout + result.stderr


def test_cli_success_uses_stable_message() -> None:
    result = subprocess.run(
        [sys.executable, str(BACKEND_ROOT / "scripts/validate_vultr_production_environment.py")],
        cwd=BACKEND_ROOT,
        env={**os.environ, **VALID_ENV},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == SUCCESS_MESSAGE


def test_vultr_compose_is_private_and_migration_gated() -> None:
    compose = yaml.safe_load((REPO_ROOT / "docker-compose.vultr.yml").read_text())
    services = compose["services"]
    assert set(services) == {"postgres", "migrate", "backend", "frontend", "edge"}
    assert "ports" not in services["postgres"]
    assert "ports" not in services["backend"]
    assert "ports" not in services["frontend"]
    assert services["edge"]["ports"] == ["127.0.0.1:8080:80"]
    assert services["migrate"]["restart"] == "no"
    assert services["backend"]["depends_on"]["migrate"]["condition"] == "service_completed_successfully"
    assert (
        services["frontend"]["build"]["args"]["NEXT_PUBLIC_LISTING_AUDIT_INTERNAL_ENABLED"]
        == "true"
    )
    command = " ".join(services["migrate"]["command"])
    assert "validate_vultr_production_environment.py" in command
    assert "alembic upgrade head" in command


def test_vultr_nginx_preserves_oauth_log_isolation_and_tls_contract() -> None:
    inner = (REPO_ROOT / "nginx/nginx.vultr.conf").read_text()
    callback = inner.index("location = /api/v1/amazon/oauth/callback")
    generic = inner.index("location /api/")
    assert callback < generic
    assert "access_log off;" in inner[callback:generic]
    assert "error_log stderr error;" in inner
    assert "limit_req_log_level notice;" in inner
    assert inner.count("proxy_set_header X-Forwarded-Proto https;") >= 3

    host = (REPO_ROOT / "deploy/nginx-app.listnara.com.conf").read_text()
    assert "127.0.0.1:8080" in host
    assert "Strict-Transport-Security" in host
    assert "/etc/letsencrypt/live/listnara.com/fullchain.pem" in host
    assert host.count("access_log off;") == 2


def test_real_vultr_secret_file_is_ignored() -> None:
    result = subprocess.run(
        ["git", "check-ignore", "-q", ".env.vultr"], cwd=REPO_ROOT, check=False
    )
    assert result.returncode == 0
