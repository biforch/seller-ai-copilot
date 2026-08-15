import importlib.util
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import WEAK_JWT_SECRETS, Settings
from app.core.logging_utils import redact_sensitive_text


def test_production_rejects_weak_jwt_secret():
    with pytest.raises(ValueError, match="JWT_SECRET_KEY"):
        Settings(
            _env_file=None,
            ENVIRONMENT="production",
            DATABASE_URL="postgresql://example.com:5432/sellerai_prod",
            JWT_SECRET_KEY="your-super-secret-jwt-key-change-me",
            OPENAI_API_KEY="test-openai-key",
        )


def test_production_rejects_short_jwt_secret():
    with pytest.raises(ValueError, match="at least 32 characters"):
        Settings(
            _env_file=None,
            ENVIRONMENT="production",
            DATABASE_URL="postgresql://example.com:5432/sellerai_prod",
            JWT_SECRET_KEY="short-secret",
            OPENAI_API_KEY="test-openai-key",
        )


def test_production_rejects_debug_true():
    with pytest.raises(ValueError, match="DEBUG"):
        Settings(
            _env_file=None,
            ENVIRONMENT="production",
            DATABASE_URL="postgresql://example.com:5432/sellerai_prod",
            JWT_SECRET_KEY="x" * 32,
            OPENAI_API_KEY="test-openai-key",
            DEBUG=True,
        )


def test_invalid_environment_value_is_rejected():
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            ENVIRONMENT="develoment",
            DATABASE_URL="postgresql://localhost:5432/sellerai_test",
            JWT_SECRET_KEY="pytest-jwt-secret-key-min-32-chars-long",
            OPENAI_API_KEY="test-openai-key",
        )


def test_testing_refuses_non_test_database_name():
    with pytest.raises(ValueError, match="test database"):
        Settings(
            _env_file=None,
            ENVIRONMENT="testing",
            DATABASE_URL="postgresql://localhost:5432/sellerai",
            JWT_SECRET_KEY="pytest-jwt-secret-key-min-32-chars-long",
            OPENAI_API_KEY="test-openai-key",
        )


def test_debug_defaults_false_in_settings():
    settings = Settings(
        _env_file=None,
        ENVIRONMENT="testing",
        DATABASE_URL="postgresql://localhost:5432/sellerai_test",
        JWT_SECRET_KEY="pytest-jwt-secret-key-min-32-chars-long",
        OPENAI_API_KEY="test-openai-key",
    )
    assert settings.DEBUG is False


@pytest.mark.parametrize(
    "secret",
    sorted(WEAK_JWT_SECRETS - {""}),
)
def test_known_weak_jwt_values_are_blocked_in_production(secret):
    with pytest.raises(ValueError):
        Settings(
            _env_file=None,
            ENVIRONMENT="staging",
            DATABASE_URL="postgresql://example.com:5432/sellerai_stage",
            JWT_SECRET_KEY=secret if secret else "x" * 32,
            OPENAI_API_KEY="test-openai-key",
        )


def test_redact_sensitive_text_covers_common_secret_patterns():
    raw = (
        "Authorization: Bearer abc.def.ghi "
        "api_key=secret-value refresh_token=rt-123 access_token=at-456 "
        "client_secret=cs-789 eyJhbGci.test.signature "
        "postgresql://user:pass@localhost:5432/db"
    )
    redacted = redact_sensitive_text(raw)
    assert "Bearer [REDACTED]" in redacted
    assert "secret-value" not in redacted
    assert "rt-123" not in redacted
    assert "at-456" not in redacted
    assert "cs-789" not in redacted


def test_manual_llm_scripts_do_not_execute_on_import():
    scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
    for script_name in (
        "check_openai_connection.py",
        "check_openrouter_connection.py",
        "check_amazon_sp_api_sandbox.py",
    ):
        script_path = scripts_dir / script_name
        spec = importlib.util.spec_from_file_location(script_name, script_path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        assert callable(getattr(module, "test", None) or getattr(module, "main", None))


def test_gitignore_ignores_amazon_sandbox_env_file():
    gitignore = (Path(__file__).resolve().parents[2] / ".gitignore").read_text(encoding="utf-8")
    assert "/backend/.env.amazon.sandbox" in gitignore


def test_amazon_sandbox_script_has_no_production_endpoint_fallback():
    script_path = (
        Path(__file__).resolve().parents[1] / "scripts" / "check_amazon_sp_api_sandbox.py"
    )
    source = script_path.read_text(encoding="utf-8")
    assert "AmazonEndpointMode.PRODUCTION" not in source
    assert 'endpoint_mode="production"' not in source
    assert "SANDBOX_NA_HOST" in source


def test_amazon_sandbox_script_source_has_no_real_credentials():
    script_path = (
        Path(__file__).resolve().parents[1] / "scripts" / "check_amazon_sp_api_sandbox.py"
    )
    source = script_path.read_text(encoding="utf-8")
    assert "AKIA" not in source
    assert "Atza|" not in source
    assert "Atzr|" not in source


def test_dockerignore_excludes_env_but_keeps_example():
    dockerignore = (Path(__file__).resolve().parents[1] / ".dockerignore").read_text()
    assert ".env" in dockerignore
    assert "!.env.example" in dockerignore
