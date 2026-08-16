"""Static baseline checks for RC1.1 production container release artifacts."""

from __future__ import annotations

import io
import json
import re
import shutil
import subprocess
import sys
from contextlib import redirect_stderr
from pathlib import Path
from urllib.parse import quote

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from scripts.validate_rc_environment import (  # noqa: E402
    DB_PASSWORD_PLACEHOLDER,
    FAILURE_PREFIX,
    JWT_PLACEHOLDER,
    SUCCESS_MESSAGE,
    RCEnvironmentError,
    main,
    validate_rc_environment,
)

BACKEND_DOCKERFILE_PROD = REPO_ROOT / "backend" / "Dockerfile.prod"
FRONTEND_DOCKERFILE_PROD = REPO_ROOT / "frontend" / "Dockerfile.prod"
RC_COMPOSE = REPO_ROOT / "docker-compose.rc.yml"
ENV_RC_EXAMPLE = REPO_ROOT / ".env.rc.example"
RUNBOOK = REPO_ROOT / "docs" / "rc-deployment-runbook.md"
BACKEND_DOCKERIGNORE = REPO_ROOT / "backend" / ".dockerignore"
FRONTEND_DOCKERIGNORE = REPO_ROOT / "frontend" / ".dockerignore"
VALIDATOR_SCRIPT = BACKEND_ROOT / "scripts" / "validate_rc_environment.py"
RC_COMPOSE_PROJECT = "sellerai_rc"


def _docker_compose_available() -> bool:
    if shutil.which("docker") is None:
        return False
    result = subprocess.run(
        ["docker", "compose", "version"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def _require_docker_compose() -> None:
    if not _docker_compose_available():
        pytest.skip("Docker CLI or Compose plugin not available")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _dockerignore_patterns(path: Path) -> set[str]:
    patterns: set[str] = set()
    for line in _read(path).splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        patterns.add(stripped)
    return patterns


def _valid_rc_env(**overrides: str) -> dict[str, str]:
    password = "rc-valid-password-urlsafe-value"
    jwt = "rc-valid-jwt-secret-generated-at-runtime-min-32-chars"
    env = {
        "ENVIRONMENT": "staging",
        "POSTGRES_USER": "sellerai_rc",
        "POSTGRES_PASSWORD": password,
        "POSTGRES_DB": "sellerai_rc_test",
        "DATABASE_URL": f"postgresql://sellerai_rc:{password}@postgres:5432/sellerai_rc_test",
        "JWT_SECRET_KEY": jwt,
        "OPENAI_API_KEY": "rc-placeholder-not-for-real-llm",
        "CORS_ORIGINS": "http://127.0.0.1:8080",
        "NEXT_PUBLIC_API_URL": "/api/v1",
        "NEXT_PUBLIC_APP_NAME": "SellerAI Copilot",
        "RC_HTTP_PORT": "8080",
    }
    env.update(overrides)
    return env


def _write_env_file(path: Path, env: dict[str, str]) -> None:
    lines = [f"{key}={value}" for key, value in env.items()]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _compose_config_json(env_file: Path) -> dict:
    _require_docker_compose()
    result = subprocess.run(
        [
            "docker",
            "compose",
            "-p",
            RC_COMPOSE_PROJECT,
            "--env-file",
            str(env_file),
            "-f",
            str(RC_COMPOSE),
            "config",
            "--format",
            "json",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    return json.loads(result.stdout)


def _run_validator_main(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(VALIDATOR_SCRIPT)],
        cwd=BACKEND_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize(
    ("dockerfile", "forbidden"),
    [
        (BACKEND_DOCKERFILE_PROD, ("--reload",)),
        (FRONTEND_DOCKERFILE_PROD, ("npm run dev", "next dev")),
    ],
)
def test_production_dockerfile_has_no_dev_commands(
    dockerfile: Path,
    forbidden: tuple[str, ...],
) -> None:
    content = _read(dockerfile).lower()
    for token in forbidden:
        assert token.lower() not in content, f"{dockerfile.name} must not contain {token!r}"


@pytest.mark.parametrize(
    ("dockerfile", "expected_user"),
    [
        (BACKEND_DOCKERFILE_PROD, "USER app"),
        (FRONTEND_DOCKERFILE_PROD, "USER nextjs"),
    ],
)
def test_production_dockerfile_runs_as_non_root(
    dockerfile: Path,
    expected_user: str,
) -> None:
    assert expected_user in _read(dockerfile)


def test_backend_production_dockerfile_exposes_healthcheck_and_workers() -> None:
    content = _read(BACKEND_DOCKERFILE_PROD)
    assert "HEALTHCHECK" in content
    assert "/health" in content
    assert "--workers" in content
    assert "8000" in content
    assert "scripts" in content
    assert VALIDATOR_SCRIPT.name in content or "COPY scripts ./scripts" in content


def test_frontend_production_dockerfile_standalone_runner() -> None:
    content = _read(FRONTEND_DOCKERFILE_PROD)
    assert "npm ci" in content
    assert "standalone" in content
    assert 'CMD ["node", "server.js"]' in content
    assert "NODE_ENV=production" in content
    assert "COPY --from=builder /app/public ./public" in content
    assert ".next/static" in content


def _normalized_dockerfile_text(path: Path) -> str:
    return re.sub(r"\s+", " ", _read(path))


def test_frontend_production_dockerfile_uses_alpine_user_creation() -> None:
    content = _normalized_dockerfile_text(FRONTEND_DOCKERFILE_PROD)
    lowered = content.lower()

    assert "addgroup -s -g 1001 nodejs" in lowered
    assert "adduser -s" in lowered
    assert "-u 1001" in lowered
    assert "-g nodejs" in lowered
    assert " nextjs" in lowered or " nextjs " in lowered
    assert "user nextjs" in lowered
    assert "user root" not in lowered

    forbidden_fragments = (
        "adduser --system --uid 1001 --gid",
        "adduser --gid",
        "npm run dev",
    )
    for fragment in forbidden_fragments:
        assert fragment.lower() not in lowered, f"unexpected fragment: {fragment!r}"


def test_rc_compose_has_no_bind_mounts_or_backend_env_file() -> None:
    content = _read(RC_COMPOSE)
    assert "env_file:" not in content
    assert "backend/.env" not in content
    assert re.search(r"-\s+\./[^:]+:/", content) is None, "bind mounts are not allowed in RC compose"
    assert "postgres_data:/var/lib/postgresql/data" in content


def test_rc_compose_volume_has_no_explicit_name() -> None:
    content = _read(RC_COMPOSE)
    volumes_section = content.split("volumes:", 1)[1]
    assert "name:" not in volumes_section
    assert "postgres_data:" in volumes_section
    assert "sellerai_rc_postgres_data:" not in content


def test_rc_compose_migrate_runs_validator_before_alembic() -> None:
    content = _read(RC_COMPOSE)
    migrate_section = content.split("migrate:", 1)[1].split("\n  backend:", 1)[0]
    assert "validate_rc_environment.py" in migrate_section
    assert "alembic upgrade head" in migrate_section
    validator_index = migrate_section.index("validate_rc_environment.py")
    alembic_index = migrate_section.index("alembic upgrade head")
    assert validator_index < alembic_index
    assert "POSTGRES_DB:" in migrate_section
    assert "POSTGRES_PASSWORD:" in migrate_section
    assert "POSTGRES_USER:" in migrate_section


def test_rc_compose_disposable_database_and_migrate_flow() -> None:
    content = _read(RC_COMPOSE)
    assert "service_completed_successfully" in content
    assert "Dockerfile.prod" in content
    assert "redis:" not in content.split("services:")[1].split("volumes:")[0]


def test_rc_compose_requires_critical_env_vars() -> None:
    content = _read(RC_COMPOSE)
    for var in (
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_DB",
        "DATABASE_URL",
        "JWT_SECRET_KEY",
        "OPENAI_API_KEY",
        "CORS_ORIGINS",
        "ENVIRONMENT",
    ):
        assert f"${{{var}:?" in content, f"missing required env guard for {var}"


def test_dockerignore_excludes_sensitive_and_review_artifacts() -> None:
    required_snippets = (
        ".env",
        "tests/",
        "__pycache__",
        ".pytest_cache",
        "p1*",
        "rc1-*",
    )
    for dockerignore in (BACKEND_DOCKERIGNORE, FRONTEND_DOCKERIGNORE):
        patterns = _dockerignore_patterns(dockerignore)
        joined = "\n".join(patterns)
        for snippet in required_snippets:
            assert any(snippet in pattern for pattern in patterns) or snippet in joined


def test_dockerignore_keeps_runtime_sources() -> None:
    backend_patterns = _dockerignore_patterns(BACKEND_DOCKERIGNORE)
    assert not any(pattern.startswith("app/") for pattern in backend_patterns)
    assert not any(pattern.startswith("alembic/") for pattern in backend_patterns)
    assert not any(pattern.startswith("scripts/") for pattern in backend_patterns)


def test_env_rc_example_uses_placeholders_and_no_real_secrets() -> None:
    content = _read(ENV_RC_EXAMPLE)
    lowered = content.lower()
    assert "sk-" not in lowered
    assert "openrouter" not in lowered
    assert "sellerai_rc_test" in content
    assert DB_PASSWORD_PLACEHOLDER in content
    assert JWT_PLACEHOLDER in content
    assert "rc-placeholder-not-for-real-llm" in content
    assert "rc-local-only-change-me" not in content


def test_env_rc_example_placeholders_are_rejected_by_validator() -> None:
    example_lines = [
        line
        for line in _read(ENV_RC_EXAMPLE).splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    env = dict(line.split("=", 1) for line in example_lines)
    with pytest.raises(RCEnvironmentError):
        validate_rc_environment(env)


def test_next_config_enables_standalone_output() -> None:
    content = _read(REPO_ROOT / "frontend" / "next.config.js")
    assert 'output: "standalone"' in content or "output: 'standalone'" in content


def test_api_client_uses_relative_base_without_double_api_prefix() -> None:
    constants = _read(REPO_ROOT / "frontend" / "lib" / "constants.ts")
    client = _read(REPO_ROOT / "frontend" / "app/api/client.ts")
    assert "NEXT_PUBLIC_API_URL" in constants
    assert "`${this.baseUrl}${path}`" in client
    assert "/auth/register" in _read(REPO_ROOT / "frontend" / "hooks/useAuth.ts")


def test_nginx_rc_proxy_preserves_api_prefix() -> None:
    nginx_conf = _read(REPO_ROOT / "nginx/nginx.rc.conf")
    assert "location /api/" in nginx_conf
    assert "proxy_pass http://rc_backend;" in nginx_conf
    assert "proxy_pass http://rc_backend/api/" not in nginx_conf


def test_runbook_documents_403_and_container_pg_dump() -> None:
    runbook = _read(RUNBOOK)
    assert "403" in runbook
    assert "401" not in runbook.split("Non-LLM smoke test")[1].split("## 10.")[0]
    assert "sh -c 'pg_dump -U \"$POSTGRES_USER\" \"$POSTGRES_DB\"'" in runbook
    assert 'docker volume inspect sellerai_rc_postgres_data' in runbook
    assert "com.docker.compose.project=sellerai_rc" in runbook
    assert "com.docker.compose.volume=postgres_data" in runbook
    assert "validate_rc_environment.py" in runbook
    assert "POSTGRES_USER" in runbook.split("## 3.")[1].split("## 4.")[0]
    assert "must match POSTGRES_USER" in runbook or "must match `POSTGRES_USER`" in runbook
    assert "32 characters" in runbook


def test_alembic_head_unchanged() -> None:
    result = subprocess.run(
        ["alembic", "heads"],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "e8f9a0b1c2d3 (head)" in result.stdout


def test_validator_accepts_valid_rc_environment() -> None:
    validate_rc_environment(_valid_rc_env())
    result = _run_validator_main(_valid_rc_env())
    assert result.returncode == 0
    assert result.stdout.strip() == SUCCESS_MESSAGE


@pytest.mark.parametrize(
    ("overrides", "reason_fragment"),
    [
        ({"POSTGRES_DB": "sellerai_rc_prod"}, "database name must end with _test"),
        ({"DATABASE_URL": "mysql://sellerai_rc:pw@postgres:5432/sellerai_rc_test"}, "PostgreSQL scheme"),
        ({"DATABASE_URL": "postgresql://sellerai_rc:pw@localhost:5432/sellerai_rc_test"}, "RC postgres service"),
        ({"DATABASE_URL": "postgresql://sellerai_rc:pw@127.0.0.1:5432/sellerai_rc_test"}, "RC postgres service"),
        ({"DATABASE_URL": "postgresql://sellerai_rc:pw@8.8.8.8:5432/sellerai_rc_test"}, "RC postgres service"),
        ({"DATABASE_URL": "postgresql://sellerai_rc:pw@postgres:5432/other_db_test"}, "must match POSTGRES_DB"),
        ({"JWT_SECRET_KEY": JWT_PLACEHOLDER}, "JWT_SECRET_KEY placeholder"),
        ({"POSTGRES_PASSWORD": DB_PASSWORD_PLACEHOLDER}, "POSTGRES_PASSWORD placeholder"),
        (
            {
                "POSTGRES_PASSWORD": "real-password-value",
                "DATABASE_URL": f"postgresql://sellerai_rc:{DB_PASSWORD_PLACEHOLDER}@postgres:5432/sellerai_rc_test",
            },
            "DATABASE_URL password placeholder",
        ),
        ({"ENVIRONMENT": "production"}, "disposable RC values"),
        (
            {"POSTGRES_USER": "other_user"},
            "username must match POSTGRES_USER",
        ),
        (
            {
                "POSTGRES_PASSWORD": "actual-password-value",
                "DATABASE_URL": "postgresql://sellerai_rc:wrong-password@postgres:5432/sellerai_rc_test",
            },
            "password must match POSTGRES_PASSWORD",
        ),
        (
            {"DATABASE_URL": "postgresql://:password@postgres:5432/sellerai_rc_test"},
            "must include a username",
        ),
        (
            {"DATABASE_URL": "postgresql://sellerai_rc@postgres:5432/sellerai_rc_test"},
            "must include a password",
        ),
        (
            {"DATABASE_URL": "postgresql://sellerai_rc:pw@postgres:5433/sellerai_rc_test"},
            "port must be 5432 when specified",
        ),
        (
            {"DATABASE_URL": "postgresql://sellerai_rc:pw@postgres:badport/sellerai_rc_test"},
            "port must be 5432 when specified",
        ),
        (
            {"DATABASE_URL": "postgresql://sellerai_rc:pw@postgres:5432/sellerai_rc_test?sslmode=disable"},
            "must not include query parameters",
        ),
        (
            {"DATABASE_URL": "postgresql://sellerai_rc:pw@postgres:5432/sellerai_rc_test#fragment"},
            "must not include a fragment",
        ),
        ({"JWT_SECRET_KEY": "a" * 31}, "JWT_SECRET_KEY must be at least 32 characters"),
    ],
)
def test_validator_rejects_unsafe_configuration(
    overrides: dict[str, str],
    reason_fragment: str,
) -> None:
    env = _valid_rc_env(**overrides)
    with pytest.raises(RCEnvironmentError) as exc_info:
        validate_rc_environment(env)
    assert reason_fragment in exc_info.value.reason


def test_validator_accepts_percent_encoded_password() -> None:
    password = "p@ss:w/rd"
    encoded = quote(password, safe="")
    env = _valid_rc_env(
        POSTGRES_PASSWORD=password,
        DATABASE_URL=f"postgresql://sellerai_rc:{encoded}@postgres:5432/sellerai_rc_test",
    )
    validate_rc_environment(env)


def test_validator_accepts_explicit_port_5432() -> None:
    env = _valid_rc_env(
        DATABASE_URL="postgresql://sellerai_rc:rc-valid-password-urlsafe-value@postgres:5432/sellerai_rc_test",
    )
    validate_rc_environment(env)


def test_validator_accepts_jwt_with_exactly_32_characters() -> None:
    env = _valid_rc_env(JWT_SECRET_KEY="a" * 32)
    validate_rc_environment(env)


def test_validator_invalid_port_does_not_raise_traceback() -> None:
    env = _valid_rc_env(
        DATABASE_URL="postgresql://sellerai_rc:pw@postgres:badport/sellerai_rc_test",
    )
    with pytest.raises(RCEnvironmentError) as exc_info:
        validate_rc_environment(env)
    assert exc_info.value.reason == "DATABASE_URL port must be 5432 when specified"
    assert isinstance(exc_info.value, RCEnvironmentError)


def test_validator_failure_output_does_not_leak_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    secret_password = "super-secret-rc-password-value"
    secret_user = "secret-rc-user"
    secret_jwt = "x" * 31
    env = _valid_rc_env(
        POSTGRES_USER=secret_user,
        JWT_SECRET_KEY=secret_jwt,
        POSTGRES_PASSWORD=secret_password,
        DATABASE_URL=f"postgresql://{secret_user}:{secret_password}@postgres:5432/sellerai_rc_test",
    )
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    stderr_buffer = io.StringIO()
    with redirect_stderr(stderr_buffer):
        exit_code = main()

    assert exit_code == 1
    output = stderr_buffer.getvalue()
    assert output.startswith(f"{FAILURE_PREFIX}:")
    assert secret_password not in output
    assert secret_user not in output
    assert secret_jwt not in output
    assert "postgresql://" not in output

    proc = _run_validator_main(env)
    assert proc.returncode == 1
    assert secret_password not in proc.stderr
    assert secret_user not in proc.stderr
    assert secret_jwt not in proc.stderr
    assert "postgresql://" not in proc.stderr


def test_docker_compose_rc_config_validates_with_safe_env(tmp_path: Path) -> None:
    _require_docker_compose()
    env_file = tmp_path / ".env.rc"
    _write_env_file(env_file, _valid_rc_env())
    result = subprocess.run(
        [
            "docker",
            "compose",
            "-p",
            RC_COMPOSE_PROJECT,
            "--env-file",
            str(env_file),
            "-f",
            str(RC_COMPOSE),
            "config",
            "--quiet",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_docker_compose_rc_config_json_structure(tmp_path: Path) -> None:
    _require_docker_compose()
    env_file = tmp_path / ".env.rc"
    _write_env_file(env_file, _valid_rc_env())
    config = _compose_config_json(env_file)

    assert set(config["services"]) == {"postgres", "migrate", "backend", "frontend", "nginx"}

    for service_name, service in config["services"].items():
        for mount in service.get("volumes", []):
            assert mount["type"] != "bind", f"{service_name} must not bind-mount host paths"

    migrate = config["services"]["migrate"]
    backend = config["services"]["backend"]
    postgres = config["services"]["postgres"]
    nginx = config["services"]["nginx"]

    assert migrate["image"] == "sellerai-backend-prod:rc"
    assert backend["image"] == "sellerai-backend-prod:rc"
    assert migrate["depends_on"]["postgres"]["condition"] == "service_healthy"
    assert backend["depends_on"]["migrate"]["condition"] == "service_completed_successfully"

    migrate_env = migrate["environment"]
    assert isinstance(migrate_env, dict)
    assert "POSTGRES_DB" in migrate_env
    assert "POSTGRES_PASSWORD" in migrate_env
    assert "POSTGRES_USER" in migrate_env

    migrate_command = " ".join(migrate["command"])
    assert "validate_rc_environment.py" in migrate_command
    assert migrate_command.index("validate_rc_environment.py") < migrate_command.index("alembic")

    postgres_mounts = postgres["volumes"]
    assert postgres_mounts[0]["source"] == "postgres_data"

    volume_def = config["volumes"]["postgres_data"]
    assert volume_def.get("external") is not True
    assert volume_def["name"] == f"{RC_COMPOSE_PROJECT}_postgres_data"

    nginx_port = nginx["ports"][0]
    assert nginx_port["host_ip"] == "127.0.0.1"
    assert sum(len(service.get("ports", [])) for service in config["services"].values()) == 1

    assert all("env_file" not in service for service in config["services"].values())

    assert config["name"] == RC_COMPOSE_PROJECT
