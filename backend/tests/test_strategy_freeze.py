import os
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent


def _testing_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "ENVIRONMENT": "testing",
        "DATABASE_URL": "postgresql://sellerai:sellerai123@localhost/sellerai_test",
        "AMAZON_SP_API_ENDPOINT_MODE": "mock",
        "LEGACY_GENERATION_ENABLED": False,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_frozen_capabilities_are_disabled_by_default() -> None:
    settings = _testing_settings()

    assert Settings.model_fields["LEGACY_GENERATION_ENABLED"].default is False
    assert Settings.model_fields["ANALYSIS_PUBLIC_ENABLED"].default is False
    assert settings.LEGACY_GENERATION_ENABLED is False
    assert settings.ANALYSIS_PUBLIC_ENABLED is False
    assert settings.AMAZON_SP_API_ENABLED is False
    assert settings.AMAZON_OAUTH_ENABLED is False


def test_public_analysis_cannot_be_enabled_before_b3() -> None:
    with pytest.raises(ValidationError, match="must remain false before the B3 go/no-go"):
        _testing_settings(ANALYSIS_PUBLIC_ENABLED=True)


def test_legacy_generate_router_registration_is_feature_gated() -> None:
    source = (BACKEND_ROOT / "app" / "main.py").read_text(encoding="utf-8")

    assert "if settings.LEGACY_GENERATION_ENABLED:" in source
    assert source.index("if settings.LEGACY_GENERATION_ENABLED:") < source.index(
        'prefix="/api/v1/generate"'
    )


def test_default_app_does_not_register_legacy_generate_routes() -> None:
    env = os.environ.copy()
    env["LEGACY_GENERATION_ENABLED"] = "false"
    env["ANALYSIS_PUBLIC_ENABLED"] = "false"
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from app.main import app; "
                "assert not any(route.path.startswith('/api/v1/generate') "
                "for route in app.routes)"
            ),
        ],
        cwd=BACKEND_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )

    assert result.returncode == 0


def test_rc_contract_explicitly_keeps_frozen_capabilities_off() -> None:
    env_example = (REPO_ROOT / ".env.rc.example").read_text(encoding="utf-8")
    compose = (REPO_ROOT / "docker-compose.rc.yml").read_text(encoding="utf-8")

    assert "LEGACY_GENERATION_ENABLED=false" in env_example
    assert "ANALYSIS_PUBLIC_ENABLED=false" in env_example
    assert "${LEGACY_GENERATION_ENABLED:-false}" in compose
    assert "${ANALYSIS_PUBLIC_ENABLED:-false}" in compose
