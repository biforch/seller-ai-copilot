"""Static baseline checks for RC1.1 production container release artifacts."""

from __future__ import annotations

import base64
import io
import json
import re
import shutil
import subprocess
import sys
from contextlib import redirect_stderr
from pathlib import Path
from urllib.parse import quote, urlparse

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
QUALITY_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "quality.yml"
FRONTEND_NPMRC = REPO_ROOT / "frontend" / ".npmrc"
FRONTEND_PACKAGE_LOCK = REPO_ROOT / "frontend" / "package-lock.json"
ALLOWED_NPM_REGISTRY_HOST = "registry.npmjs.org"
NODE_24_ALPINE_DIGEST = (
    "node:24-alpine@sha256:d32cdf619f63fe0471182d08996dd516c6275bb5fd31ae06e55a570bd9e1ad43"
)
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


def _quality_job_block(content: str, job_name: str, next_job_name: str) -> str:
    start = content.index(f"  {job_name}:")
    end = content.index(f"  {next_job_name}:")
    return content[start:end]


def _named_step_block(job_block: str, step_name: str) -> str:
    marker = f"- name: {step_name}\n"
    start = job_block.index(marker)
    remainder = job_block[start + len(marker) :]
    next_offset: int | None = None
    for token in ("\n      - name:", "\n      - uses:"):
        found = remainder.find(token)
        if found != -1 and (next_offset is None or found < next_offset):
            next_offset = found
    end = start + len(marker) + (len(remainder) if next_offset is None else next_offset)
    return job_block[start:end]


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
        "SESSION_COOKIE_SECURE": "false",
    }
    env.update(overrides)
    return env


def _amazon_enabled_rc_env(**overrides: str) -> dict[str, str]:
    key = base64.urlsafe_b64encode(b"k" * 32).decode().rstrip("=")
    pepper = base64.urlsafe_b64encode(b"p" * 32).decode().rstrip("=")
    env = _valid_rc_env(
        AMAZON_SP_API_ENABLED="true",
        AMAZON_SP_API_ENDPOINT_MODE="production",
        AMAZON_SP_API_REGION="na",
        AMAZON_LWA_CLIENT_ID="amzn-client-id-placeholder-for-rc",
        AMAZON_LWA_CLIENT_SECRET="amzn-client-secret-placeholder-for-rc",
        AMAZON_LWA_TOKEN_URL="https://api.amazon.com/auth/o2/token",
        AMAZON_SP_API_USER_AGENT="SellerAI-Copilot/1.0.0 (Language=Python)",
        AMAZON_TOKEN_ACTIVE_KEY_VERSION="1",
        AMAZON_TOKEN_KEY_V1=key,
        AMAZON_TOKEN_FINGERPRINT_PEPPER=pepper,
        AMAZON_OAUTH_ENABLED="false",
    )
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
    assert "/health/ready" in content
    assert "urllib.request" in content
    assert "curl" not in content.lower()
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
        "SESSION_COOKIE_SECURE",
    ):
        assert f"${{{var}:?" in content, f"missing required env guard for {var}"


def test_rc_compose_passes_amazon_capability_configuration_explicitly() -> None:
    content = _read(RC_COMPOSE)
    for var in (
        "AMAZON_SP_API_ENABLED",
        "AMAZON_SP_API_ENDPOINT_MODE",
        "AMAZON_LWA_CLIENT_ID",
        "AMAZON_LWA_CLIENT_SECRET",
        "AMAZON_TOKEN_KEY_V1",
        "AMAZON_TOKEN_FINGERPRINT_PEPPER",
        "AMAZON_OAUTH_ENABLED",
        "AMAZON_OAUTH_REDIRECT_URI",
    ):
        assert len(re.findall(rf"^\s+{var}:", content, flags=re.MULTILINE)) == 2
    assert "backend/.env" not in content
    assert "/health/ready" in content


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
    assert "SESSION_COOKIE_SECURE=false" in content


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
    assert "ignoreBuildErrors" not in content
    assert "ignoreDuringBuilds" not in content


def test_frontend_build_has_no_remote_google_font_dependency() -> None:
    layout = _read(REPO_ROOT / "frontend" / "app" / "layout.tsx")
    assert "next/font/google" not in layout
    assert "fonts.googleapis.com" not in layout


def test_quality_workflow_runs_container_image_pin_validator_before_docker_builds() -> None:
    content = _read(QUALITY_WORKFLOW)
    backend_start = content.index("  backend:")
    frontend_start = content.index("  frontend:")
    containers_start = content.index("  containers:")
    backend_block = content[backend_start:frontend_start]
    containers_block = content[containers_start:]

    assert "python scripts/validate_container_image_pins.py" in backend_block
    backend_pin_index = backend_block.index("python scripts/validate_container_image_pins.py")
    ruff_index = backend_block.index("ruff check app tests scripts")
    assert backend_pin_index < ruff_index

    assert "python backend/scripts/validate_container_image_pins.py" in containers_block
    pin_index = containers_block.index("python backend/scripts/validate_container_image_pins.py")
    compose_index = containers_block.index("docker compose --env-file .env.rc.example")
    build_index = containers_block.index("docker build --file backend/Dockerfile.prod")
    assert pin_index < compose_index < build_index
    assert "continue-on-error" not in containers_block
    assert "|| true" not in containers_block


def test_quality_workflow_uses_supported_node_runtime() -> None:
    content = _read(QUALITY_WORKFLOW)
    node_version_lines = [
        line.strip()
        for line in content.splitlines()
        if line.strip().startswith("node-version:")
    ]
    assert node_version_lines == ['node-version: "24.19.0"']
    assert 'node-version: "20"' not in content


def test_frontend_runtime_contract_requires_pinned_node_npm_toolchain() -> None:
    nvmrc = _read(REPO_ROOT / "frontend" / ".nvmrc").strip()
    package_json = _read(REPO_ROOT / "frontend" / "package.json")
    npmrc = _read(REPO_ROOT / "frontend" / ".npmrc")
    lockfile = json.loads(_read(FRONTEND_PACKAGE_LOCK))

    assert nvmrc == "24.19.0"
    assert '"node": ">=24.19.0 <25"' in package_json
    assert '"npm": ">=11.17.0 <12"' in package_json
    assert '"packageManager": "npm@11.17.0"' in package_json
    assert "node scripts/check-node-engine.mjs" in package_json
    assert "validate-node-toolchain.mjs" in package_json
    assert "validate-installed-dependency-tree.mjs" in package_json
    assert lockfile["packages"][""]["engines"] == {
        "node": ">=24.19.0 <25",
        "npm": ">=11.17.0 <12",
    }
    assert "engine-strict=true" in npmrc
    assert NODE_24_ALPINE_DIGEST in _read(FRONTEND_DOCKERFILE_PROD)
    assert NODE_24_ALPINE_DIGEST in _read(REPO_ROOT / "frontend" / "Dockerfile")


def test_nginx_runtime_uses_current_stable_branch() -> None:
    nginx_digest = (
        "nginx:1.30-alpine@sha256:97d490c12ba55b4946b01546d1c3ed324e8d41ab1c9fcb2a616aa470620e5b46"
    )
    assert nginx_digest in _read(REPO_ROOT / "nginx" / "Dockerfile.rc")
    assert nginx_digest in _read(REPO_ROOT / "docker-compose.yml")
    assert "nginx:1.28-alpine" not in _read(REPO_ROOT / "docs" / "runtime-image-policy.md")


def test_quality_workflow_runs_backend_and_frontend_release_gates() -> None:
    content = _read(QUALITY_WORKFLOW)
    frontend_block = _quality_job_block(content, "frontend", "containers")
    assert "permissions:\n  contents: read" in content
    assert "postgres:16-alpine@sha256:cf78e76683b9ca8c5733cbbdce6c9262b45b6767934dd0a95e671f9a0fc20685" in content
    assert "sellerai_migration_test" in content
    assert "ruff check app tests scripts" in content
    assert "mypy app scripts" in content
    assert "pytest -q" in content
    assert "run: npm run lint -- --max-warnings=0" in frontend_block
    assert "run: ./node_modules/.bin/tsc --noEmit" in frontend_block
    assert "npx tsc" not in frontend_block
    assert "npm exec tsc" not in frontend_block
    assert "npm run build" in content
    assert "pull_request:" in content
    assert "actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683" in content
    assert "actions/setup-python@42375524e23c412d93fb67b49958b491fce71c38" in content
    assert "actions/setup-node@49933ea5288caeca8642d1e84afbd3f7d6820020" in content
    assert "actions/checkout@v" not in content
    assert "actions/setup-python@v" not in content
    assert "actions/setup-node@v" not in content


def test_quality_workflow_runs_frontend_unit_tests_before_build() -> None:
    content = _read(QUALITY_WORKFLOW)
    frontend_block = _quality_job_block(content, "frontend", "containers")

    toolchain_index = frontend_block.index("node scripts/validate-node-toolchain.mjs")
    validate_index = frontend_block.index("node scripts/validate-lockfile-registry.mjs")
    validator_test_index = frontend_block.index("node --test scripts/validate-lockfile-registry.test.mjs")
    toolchain_test_index = frontend_block.index("node --test scripts/validate-node-toolchain.test.mjs")
    installed_tree_test_index = frontend_block.index(
        "node --test scripts/validate-installed-dependency-tree.test.mjs"
    )
    npm_ci_index = frontend_block.index("run: npm ci")
    installed_tree_index = frontend_block.index("node scripts/validate-installed-dependency-tree.mjs")
    lint_index = frontend_block.index("run: npm run lint -- --max-warnings=0")
    test_index = frontend_block.index("run: npm test -- --run")
    tsc_index = frontend_block.index("run: ./node_modules/.bin/tsc --noEmit")
    build_index = frontend_block.index("run: npm run build")

    assert (
        toolchain_index
        < validate_index
        < validator_test_index
        < toolchain_test_index
        < installed_tree_test_index
        < npm_ci_index
        < installed_tree_index
        < lint_index
        < test_index
        < tsc_index
        < build_index
    )
    assert "npm install -g npm" not in frontend_block
    assert "continue-on-error" not in frontend_block
    assert "|| true" not in frontend_block
    assert "vitest watch" not in frontend_block


def test_quality_workflow_frontend_eslint_gate_blocks_errors_and_warnings() -> None:
    content = _read(QUALITY_WORKFLOW)
    frontend_block = _quality_job_block(content, "frontend", "containers")
    lint_step = _named_step_block(frontend_block, "Run frontend lint")
    test_step = _named_step_block(frontend_block, "Frontend unit tests")
    typecheck_step = _named_step_block(frontend_block, "Run frontend type check")
    build_step = _named_step_block(frontend_block, "Production build")
    installed_tree_step = _named_step_block(frontend_block, "Validate installed dependency tree")

    lint_run_lines = [line.strip() for line in lint_step.splitlines() if line.strip().startswith("run:")]
    typecheck_run_lines = [
        line.strip() for line in typecheck_step.splitlines() if line.strip().startswith("run:")
    ]
    assert lint_run_lines == ["run: npm run lint -- --max-warnings=0"]
    assert typecheck_run_lines == ["run: ./node_modules/.bin/tsc --noEmit"]
    assert "--quiet" not in lint_step
    assert "--fix" not in lint_step
    assert "continue-on-error" not in lint_step
    assert "|| true" not in lint_step
    assert "if:" not in lint_step
    assert "npx" not in lint_step
    assert "eslint-disable" not in lint_step

    assert frontend_block.index(installed_tree_step) < frontend_block.index(lint_step)
    assert frontend_block.index(lint_step) < frontend_block.index(test_step)
    assert frontend_block.index(lint_step) < frontend_block.index(typecheck_step)
    assert frontend_block.index(lint_step) < frontend_block.index(build_step)
    assert frontend_block.index(typecheck_step) < frontend_block.index(build_step)
    assert frontend_block.index(test_step) < frontend_block.index(typecheck_step)

    assert "npx tsc" not in typecheck_step
    assert "npm exec" not in typecheck_step
    assert "continue-on-error" not in typecheck_step
    assert "|| true" not in typecheck_step
    assert "if:" not in typecheck_step
    assert "command -v" not in typecheck_step
    assert "npx tsc" not in frontend_block
    assert "npm exec tsc" not in frontend_block

    containers_onward = content[content.index("  containers:") :]
    assert "npm run lint" not in containers_onward
    assert "./node_modules/.bin/tsc --noEmit" not in containers_onward
    assert "npx tsc" not in containers_onward
    assert "needs: [backend, frontend]" in containers_onward
    assert "Evaluate vulnerability policy" in containers_onward
    assert "backend-alpine-candidate-audit:" not in content
    assert "backend-alpine-hardened-candidate:" not in content
    assert "Evaluate Alpine candidate vulnerability policy" not in content
    assert "Evaluate hardened Alpine candidate vulnerability policy" not in content


def _assert_official_npm_registry_resolved(resolved: str) -> None:
    assert isinstance(resolved, str)
    assert not resolved.startswith("git+")
    assert not resolved.startswith("file:")
    assert not resolved.startswith("http://")
    assert not resolved.startswith("//")
    assert "registry.npmmirror.com" not in resolved

    parsed = urlparse(resolved)
    assert parsed.scheme == "https"
    assert parsed.hostname == ALLOWED_NPM_REGISTRY_HOST
    assert parsed.port in (None, 443)
    assert not parsed.username
    assert not parsed.password
    assert parsed.query == ""
    assert parsed.fragment == ""
    assert parsed.path.startswith("/")
    assert "\\" not in parsed.path


def test_frontend_npmrc_points_to_official_registry() -> None:
    content = _read(FRONTEND_NPMRC)
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    assert lines == [
        "registry=https://registry.npmjs.org/",
        "replace-registry-host=always",
        "engine-strict=true",
    ]
    assert "strict-ssl=false" not in content
    assert "registry=http://" not in content
    assert "legacy-peer-deps=true" not in content
    assert "force=true" not in content
    assert "ignore-scripts=true" not in content
    assert "_auth" not in content
    assert "_authToken" not in content
    assert "${" not in content
    assert "proxy=" not in content
    assert content.endswith("\n")


def test_frontend_lockfile_resolved_sources_use_official_registry_only() -> None:
    lockfile = json.loads(_read(FRONTEND_PACKAGE_LOCK))
    packages = lockfile.get("packages", {})
    checked = 0

    for package_path, meta in packages.items():
        if not isinstance(meta, dict):
            continue
        resolved = meta.get("resolved")
        if resolved is None:
            assert package_path == ""
            continue

        checked += 1
        _assert_official_npm_registry_resolved(resolved)

    assert checked == 652


def test_frontend_dockerfile_runs_toolchain_and_installed_tree_validators_around_npm_ci() -> None:
    content = _read(FRONTEND_DOCKERFILE_PROD)
    assert "COPY package.json package-lock.json .npmrc ./" in content
    assert "COPY scripts/validate-node-toolchain.mjs ./scripts/validate-node-toolchain.mjs" in content
    assert "COPY scripts/validate-lockfile-registry.mjs ./scripts/validate-lockfile-registry.mjs" in content
    assert (
        "COPY scripts/validate-installed-dependency-tree.mjs "
        "./scripts/validate-installed-dependency-tree.mjs"
    ) in content
    assert "node scripts/validate-node-toolchain.mjs" in content
    assert "node scripts/validate-lockfile-registry.mjs" in content
    assert "node scripts/validate-installed-dependency-tree.mjs" in content
    toolchain_index = content.index("node scripts/validate-node-toolchain.mjs")
    lockfile_index = content.index("node scripts/validate-lockfile-registry.mjs")
    npm_ci_index = content.index("npm ci")
    installed_tree_index = content.index("node scripts/validate-installed-dependency-tree.mjs")
    assert toolchain_index < lockfile_index < npm_ci_index < installed_tree_index
    assert "validate-installed-dependency-tree.test.mjs" not in content
    assert "npm install -g npm" not in content
    assert "continue-on-error" not in content
    assert "|| true" not in content


def test_frontend_dev_dockerfile_runs_toolchain_and_installed_tree_validators_around_npm_ci() -> None:
    content = _read(REPO_ROOT / "frontend" / "Dockerfile")
    assert NODE_24_ALPINE_DIGEST in content
    assert "COPY package.json package-lock.json .npmrc ./" in content
    assert "node scripts/validate-node-toolchain.mjs" in content
    assert "node scripts/validate-lockfile-registry.mjs" in content
    assert "node scripts/validate-installed-dependency-tree.mjs" in content
    assert "npm ci" in content
    assert "npm install" not in content
    toolchain_index = content.index("node scripts/validate-node-toolchain.mjs")
    lockfile_index = content.index("node scripts/validate-lockfile-registry.mjs")
    npm_ci_index = content.index("npm ci")
    installed_tree_index = content.index("node scripts/validate-installed-dependency-tree.mjs")
    assert toolchain_index < lockfile_index < npm_ci_index < installed_tree_index
    assert "validate-installed-dependency-tree.test.mjs" not in content


def test_frontend_production_dockerfile_runner_excludes_governance_artifacts() -> None:
    content = _read(FRONTEND_DOCKERFILE_PROD)
    runner_start = content.index("AS runner")
    runner_block = content[runner_start:]
    assert "validate-node-toolchain.mjs" not in runner_block
    assert "validate-installed-dependency-tree.mjs" not in runner_block
    assert "package-lock.json" not in runner_block
    assert ".npmrc" not in runner_block


def test_quality_workflow_validates_and_builds_release_containers() -> None:
    content = _read(QUALITY_WORKFLOW)
    assert "containers:" in content
    assert "needs: [backend, frontend]" in content
    assert "docker compose --env-file .env.rc.example" in content
    assert "-f docker-compose.rc.yml config --quiet" in content
    assert "docker build --file backend/Dockerfile.prod" in content
    assert "docker build --file frontend/Dockerfile.prod" in content
    assert "docker build --file nginx/Dockerfile.rc" in content
    assert "--build-arg NEXT_PUBLIC_API_URL=/api/v1" in content
    assert "secrets." not in content


def test_quality_workflow_s3c_sbom_and_vulnerability_scan() -> None:
    content = _read(QUALITY_WORKFLOW)

    pin_index = content.index("- name: Validate pinned container base images")
    compose_index = content.index("- name: Validate RC Compose configuration")
    build_backend_index = content.index("- name: Build production backend image")
    runtime_smoke_index = content.index("- name: Validate backend production runtime environment")
    build_frontend_index = content.index("- name: Build production frontend image")
    frontend_runtime_smoke_index = content.index("- name: Validate frontend production runtime environment")
    save_index = content.index("- name: Save production images for offline scan")
    syft_index = content.index("- name: Generate CycloneDX SBOMs")
    sbom_validate_index = content.index("- name: Validate SBOM artifacts")
    trivy_index = content.index("- name: Generate Trivy vulnerability reports")
    policy_index = content.index("- name: Evaluate vulnerability policy")
    upload_index = content.index("- name: Upload supply-chain scan artifacts")

    assert (
        pin_index
        < compose_index
        < build_backend_index
        < runtime_smoke_index
        < build_frontend_index
        < frontend_runtime_smoke_index
        < save_index
    )
    assert save_index < syft_index < sbom_validate_index < trivy_index < policy_index < upload_index

    assert "anchore/syft:v1.51.0@sha256:678bfa565b60f747aac0f8e964fe5588a24445b8d0a480e91f6efd70020dfbb0" in content
    assert "aquasec/trivy:0.74.0@sha256:62b1e65e8869bc4b4c6aa4fa2b21595256c7c2f6018a9d9ad61caf87187c1969" in content
    assert "/var/run/docker.sock" not in content.split("containers:", 1)[1]
    assert "continue-on-error" not in content.split("containers:", 1)[1]
    assert "|| true" not in content.split("containers:", 1)[1]
    assert "sellerai-scan/input" in content
    assert "sellerai-scan/output" in content
    assert "retention-days: 14" in content
    assert "if-no-files-found: error" in content
    assert "name: sellerai-supply-chain-${{ github.sha }}" in content

    upload_block = content.split("- name: Upload supply-chain scan artifacts", 1)[1].split("- name:", 1)[0]
    assert ".tar" not in upload_block
    assert "backend.cdx.json" in upload_block
    assert "backend-arm64.cdx.json" in upload_block
    assert "frontend.cdx.json" in upload_block
    assert "nginx.cdx.json" in upload_block
    assert "backend.trivy.json" in upload_block
    assert "backend-arm64.trivy.json" in upload_block
    assert "frontend.trivy.json" in upload_block
    assert "nginx.trivy.json" in upload_block
    assert "scan-summary.json" in upload_block
    assert len([line for line in upload_block.splitlines() if line.strip().endswith(".json")]) == 9
    assert "timeout-minutes: 45" in content
    assert "SYFT_CHECK_FOR_APP_UPDATE=false" in content
    assert "docker-archive:/input/backend.tar" in content
    assert "docker-archive:/input/backend-arm64.tar" in content
    assert "docker-archive:/input/frontend.tar" in content
    assert "docker-archive:/input/nginx.tar" in content
    assert "file:/input/" not in content.split("Generate CycloneDX SBOMs", 1)[1].split("Validate SBOM artifacts", 1)[0]
    assert "cyclonedx-json@1.6=/output/backend.cdx.json" in content
    assert "cyclonedx-json@1.6=/output/backend-arm64.cdx.json" in content
    assert "cyclonedx-json@1.6=/output/frontend.cdx.json" in content
    assert "cyclonedx-json@1.6=/output/nginx.cdx.json" in content
    assert "backend: trivy scan command failed" in content
    assert "backend-arm64: trivy scan command failed" in content
    assert "frontend: trivy scan command failed" in content
    assert "nginx: trivy scan command failed" in content
    assert "Cleanup supply-chain scan workspace" in content
    assert 'rm -rf "${CLEANUP_TARGET}"' in content
    assert 'CLEANUP_TARGET="${RUNNER_TEMP}/sellerai-scan"' in content
    assert "--user \"${RUNNER_UID}:${RUNNER_GID}\"" in content
    assert "scanner-user-validated" in content
    assert "--cache-dir /trivy-cache" in content
    assert '"${TRIVY_CACHE_DIR}:/trivy-cache:rw"' in content
    assert "/root/.cache/trivy" not in content.split("Generate Trivy", 1)[1].split("Evaluate vulnerability", 1)[0]
    assert "--privileged" not in content.split("containers:", 1)[1]
    assert "--env-file" not in content.split("Generate Trivy", 1)[1].split("Evaluate vulnerability", 1)[0]

    runtime_smoke_block = content.split("- name: Validate backend production runtime environment", 1)[1].split("- name:", 1)[0]
    containers_block = content.split("containers:", 1)[1]
    assert "--network none" in runtime_smoke_block
    assert "--read-only" in runtime_smoke_block
    assert "--tmpfs /tmp:rw,noexec,nosuid,nodev" in runtime_smoke_block
    assert "--cap-drop ALL" in runtime_smoke_block
    assert "--security-opt no-new-privileges" in runtime_smoke_block
    assert "python scripts/validate_backend_runtime_environment.py" in runtime_smoke_block
    assert "python scripts/validate_backend_alpine_os_packages.py" in runtime_smoke_block
    assert "python scripts/validate_backend_production_smoke.py" in runtime_smoke_block
    assert "python scripts/validate_alpine_hardened_smoke.py" in runtime_smoke_block
    assert "docker/setup-qemu-action@c7c53464625b32c7a7e944ae62b3e17d2b600130" in containers_block
    assert "Build production backend arm64 image" in containers_block
    assert "Validate production backend arm64 build" in containers_block
    assert "backend-arm64.tar" in containers_block
    assert "validate_alpine_hardened_smoke.py" in runtime_smoke_block
    arm64_block = content.split("- name: Validate production backend arm64 build", 1)[1].split("- name:", 1)[0]
    assert "validate_backend_runtime_environment.py" in arm64_block
    assert "validate_backend_alpine_os_packages.py" in arm64_block
    assert "validate_alpine_hardened_smoke.py" not in arm64_block
    assert "validate_backend_production_smoke.py" not in arm64_block
    assert "--network none" in arm64_block
    assert "|| true" not in runtime_smoke_block
    assert "continue-on-error" not in runtime_smoke_block
    assert "continue-on-error" not in containers_block
    assert "|| true" not in containers_block
    jobs_header = content.split("jobs:", 1)[1]
    job_names = [
        line[2:-1]
        for line in jobs_header.splitlines()
        if line.startswith("  ") and not line.startswith("    ") and line.endswith(":")
    ]
    assert job_names == ["backend", "frontend", "containers"]


def test_quality_workflow_retired_alpine_candidate_jobs() -> None:
    content = _read(QUALITY_WORKFLOW)
    assert "backend-alpine-candidate-audit:" not in content
    assert "backend-alpine-hardened-candidate:" not in content
    assert "sellerai-alpine-candidate-" not in content
    assert "sellerai-alpine-hardened-" not in content
    assert "ALPINE_CANDIDATE_" not in content
    assert "evaluate_alpine_candidate_reports.py" not in content
    assert "evaluate_alpine_hardened_candidate_reports.py" not in content
    assert "validate_alpine_candidate_wheel_manifest.py" not in content
    assert "cc19a3e1085aba7d26690cf0725d9a3e083cbea0feec34ba8133d40a8ac1d399" not in content
    assert "df8376721de6f98515643fca8e7aac56e6a39bc178697a1d8c020ffa050b655e" not in content
    assert "docker/setup-qemu-action@c7c53464625b32c7a7e944ae62b3e17d2b600130" in content
    assert "docker/setup-buildx-action@8d2750c68a42422c14e847fe6c8ac0403b4cbd6f" in content
    assert "validate_alpine_hardened_smoke.py" in content
    assert "evaluate_vulnerability_report.py" in content


BACKEND_ALPINE_SECURITY_CONTRACT_TOKENS = (
    "AS wheels",
    "AS install",
    "AS runtime",
    "pip download --only-binary=:all:",
    "pip install --no-index",
    "validate_backend_alpine_os_packages.py",
    "ca-certificates",
    "libstdc++",
    "postgresql-libs",
    "USER app",
    "python:3.11-alpine3.24@sha256:6857d2dae63e052057f2db389a7061188ac9a92a3fa8d402bde68f36df6fada1",
)


def test_backend_production_alpine_dockerfile_contract() -> None:
    prod_content = _read(BACKEND_DOCKERFILE_PROD)
    for token in BACKEND_ALPINE_SECURITY_CONTRACT_TOKENS:
        assert token in prod_content
    assert "perl" not in prod_content
    assert "util-linux" not in prod_content
    assert "3.11-slim-trixie" not in prod_content
    assert prod_content.count("FROM python:3.11-alpine3.24@") == 3
    assert not (REPO_ROOT / "backend" / "Dockerfile.alpine-candidate").exists()


def test_frontend_production_dockerfile_runner_toolchain_removal() -> None:
    content = _read(FRONTEND_DOCKERFILE_PROD)
    deps_block = content.split("AS deps", 1)[1].split("AS builder", 1)[0]
    runner_block = content.split("AS runner", 1)[1]

    assert "npm ci" in deps_block
    assert "npm run build" in content.split("AS builder", 1)[1].split("AS runner", 1)[0]
    assert 'CMD ["node", "server.js"]' in runner_block
    assert "npm uninstall -g npm" in runner_block
    assert "corepack disable" in runner_block
    assert "/usr/local/lib/node_modules/corepack" in runner_block
    assert "scripts/validate-frontend-runtime.mjs" in runner_block
    assert "USER nextjs" in runner_block
    assert runner_block.index("npm uninstall") < runner_block.index("USER nextjs")
    assert "rm -rf /usr/local/lib/node_modules/*" not in runner_block
    assert "find " not in runner_block


def test_quality_workflow_frontend_runtime_smoke_contract() -> None:
    content = _read(QUALITY_WORKFLOW)
    frontend_runtime_smoke_block = content.split(
        "- name: Validate frontend production runtime environment", 1
    )[1].split("- name:", 1)[0]
    assert "--network none" in frontend_runtime_smoke_block
    assert "--read-only" in frontend_runtime_smoke_block
    assert "--tmpfs /tmp:rw,noexec,nosuid,nodev" in frontend_runtime_smoke_block
    assert "--cap-drop ALL" in frontend_runtime_smoke_block
    assert "--security-opt no-new-privileges" in frontend_runtime_smoke_block
    assert "node scripts/validate-frontend-runtime.mjs" in frontend_runtime_smoke_block
    assert "node scripts/validate-frontend-runtime.mjs --smoke" in frontend_runtime_smoke_block
    assert "|| true" not in frontend_runtime_smoke_block
    assert "continue-on-error" not in frontend_runtime_smoke_block


def test_backend_production_dockerfile_removes_build_tooling_from_runtime() -> None:
    content = _read(BACKEND_DOCKERFILE_PROD)
    install_block = content.split("AS install", 1)[1].split("AS runtime", 1)[0]
    runtime_block = content.split("AS runtime", 1)[1]

    assert "python:3.11-alpine3.24@sha256:" in content
    assert "AS wheels" in content
    assert "AS install" in content
    assert "AS runtime" in content
    assert "ca-certificates" in runtime_block
    assert "libstdc++" in runtime_block
    assert "postgresql-libs" in runtime_block
    assert "util-linux" not in content
    assert "perl" not in content
    assert "apt-get" not in content
    assert "apk upgrade" not in content
    assert "pip download --only-binary=:all:" in content
    assert "pip install --no-index" in install_block
    assert "python -m pip check" in content
    assert "python3.11 -m pip uninstall -y jaraco.context wheel setuptools" in runtime_block
    assert "python3.11 -m pip uninstall -y pip" in runtime_block
    uninstall_block = runtime_block.split("pip uninstall", 1)[1].split("validate_backend_runtime_environment", 1)[0]
    assert "setuptools" in uninstall_block
    assert "scripts/validate_backend_runtime_environment.py" in runtime_block
    assert "scripts/validate_backend_alpine_os_packages.py" in runtime_block
    assert "PYTHONPATH=/app" in runtime_block
    assert "USER app" in runtime_block
    assert runtime_block.index("pip uninstall") < runtime_block.index("USER app")
    assert "rm -rf /usr/local/lib/python" not in runtime_block


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


def test_nginx_rc_oauth_callback_access_log_isolated() -> None:
    nginx_conf = _read(REPO_ROOT / "nginx/nginx.rc.conf")
    callback_block_start = nginx_conf.index("location = /api/v1/amazon/oauth/callback")
    api_block_start = nginx_conf.index("location /api/ {")
    assert callback_block_start < api_block_start

    callback_block = nginx_conf[callback_block_start:api_block_start]
    assert "access_log off;" in callback_block
    assert "limit_req zone=oauth_callback_per_ip burst=10 nodelay;" in callback_block
    assert "limit_req_status 429;" in callback_block
    assert "proxy_pass http://rc_backend;" in callback_block
    assert "proxy_set_header Host $host;" in callback_block
    assert "proxy_set_header X-Real-IP $remote_addr;" in callback_block
    assert "proxy_set_header X-Forwarded-For $remote_addr;" in callback_block
    assert "proxy_set_header X-Forwarded-Proto $scheme;" in callback_block
    assert "$request_uri" not in callback_block
    assert "$args" not in callback_block
    assert "access_log" not in callback_block.replace("access_log off;", "")
    assert "state-canary-secret" not in nginx_conf
    assert "spapi_oauth_code" not in nginx_conf
    assert (
        "limit_req_zone $binary_remote_addr "
        "zone=oauth_callback_per_ip:10m rate=30r/m;"
    ) in nginx_conf
    assert "error_log stderr error;" in nginx_conf
    assert "limit_req_log_level notice;" in nginx_conf


def test_runbook_documents_401_and_container_pg_dump() -> None:
    runbook = _read(RUNBOOK)
    assert "401" in runbook
    smoke_section = runbook.split("Non-LLM smoke test")[1].split("## 11.")[0]
    assert "401" in smoke_section
    assert "AUTH_SESSION_INVALID" in runbook
    assert "pg_dump -Fc -U \"$POSTGRES_USER\" \"$POSTGRES_DB\"" in runbook
    assert "pg_restore --list" in runbook
    assert "sellerai_restore_test" in runbook
    assert "--exit-on-error --no-owner --no-privileges" in runbook
    assert 'docker volume inspect sellerai_rc_postgres_data' in runbook
    assert "com.docker.compose.project=sellerai_rc" in runbook
    assert "com.docker.compose.volume=postgres_data" in runbook
    assert "validate_rc_environment.py" in runbook
    assert "POSTGRES_USER" in runbook.split("## 3.")[1].split("## 4.")[0]
    assert "must match POSTGRES_USER" in runbook or "must match `POSTGRES_USER`" in runbook
    assert "32 characters" in runbook
    assert "limit_req_log_level notice" in runbook
    assert "error_log stderr error" in runbook


def test_operations_contract_includes_fail_closed_health_and_restore_gates() -> None:
    operations = _read(REPO_ROOT / "docs" / "operations-readiness.md")
    health_script = _read(BACKEND_ROOT / "scripts" / "check_service_health.py")
    assert "scripts/check_service_health.py" in operations
    assert "2 consecutive failures" in operations
    assert "OAuth callback 429" in operations
    assert "RPO <=24 hours" in operations
    assert "RTO <=4 hours" in operations
    assert "quarterly restore rehearsal" in operations
    assert "SERVICE_HEALTH_CHECK_FAILED" in health_script
    assert "HTTPRedirectHandler" in health_script
    assert "Authorization" not in health_script


def test_nginx_rc_sets_browser_security_headers_without_false_hsts() -> None:
    nginx_conf = _read(REPO_ROOT / "nginx" / "nginx.rc.conf")
    assert 'add_header Content-Security-Policy "' in nginx_conf
    assert "default-src 'self'" in nginx_conf
    assert "object-src 'none'" in nginx_conf
    assert "frame-ancestors 'none'" in nginx_conf
    assert 'add_header Referrer-Policy "strict-origin-when-cross-origin" always;' in nginx_conf
    assert 'add_header X-Content-Type-Options "nosniff" always;' in nginx_conf
    assert 'add_header X-Frame-Options "DENY" always;' in nginx_conf
    assert 'add_header Permissions-Policy "' in nginx_conf
    assert "Strict-Transport-Security" not in nginx_conf
    for path in ("/docs", "/redoc", "/openapi.json"):
        location = nginx_conf.split(f"location {path} {{", 1)[1].split("}", 1)[0]
        assert "return 404;" in location
        assert "proxy_pass" not in location


def test_alembic_head_unchanged() -> None:
    result = subprocess.run(
        ["alembic", "heads"],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "a0b1c2d3e4f6 (head)" in result.stdout


def test_validator_accepts_valid_rc_environment() -> None:
    validate_rc_environment(_valid_rc_env())
    result = _run_validator_main(_valid_rc_env())
    assert result.returncode == 0
    assert result.stdout.strip() == SUCCESS_MESSAGE


def test_validator_rejects_secure_session_cookie_on_http_rc() -> None:
    with pytest.raises(RCEnvironmentError, match="SESSION_COOKIE_SECURE"):
        validate_rc_environment(_valid_rc_env(SESSION_COOKIE_SECURE="true"))
    with pytest.raises(RCEnvironmentError, match="SESSION_COOKIE_SECURE"):
        validate_rc_environment(_valid_rc_env(SESSION_COOKIE_SECURE=""))


def test_validator_accepts_secure_amazon_sp_api_profile() -> None:
    validate_rc_environment(_amazon_enabled_rc_env())


def test_validator_accepts_secure_amazon_oauth_profile() -> None:
    validate_rc_environment(
        _amazon_enabled_rc_env(
            AMAZON_OAUTH_ENABLED="true",
            AMAZON_SP_API_APPLICATION_ID="amzn1.sp.solution.test",
            AMAZON_OAUTH_REDIRECT_URI="https://rc.example.test/api/v1/amazon/oauth/callback",
            AMAZON_OAUTH_FRONTEND_SUCCESS_URL="https://rc.example.test/amazon/oauth/success",
            AMAZON_OAUTH_FRONTEND_ERROR_URL="https://rc.example.test/amazon/oauth/error",
            AMAZON_OAUTH_STATE_TTL_SECONDS="600",
        )
    )


@pytest.mark.parametrize(
    ("overrides", "reason_fragment"),
    [
        ({"AMAZON_SP_API_ENDPOINT_MODE": "sandbox"}, "requires AMAZON_SP_API_ENDPOINT_MODE=production"),
        ({"AMAZON_LWA_CLIENT_SECRET": ""}, "AMAZON_LWA_CLIENT_SECRET is required"),
        ({"AMAZON_TOKEN_ACTIVE_KEY_VERSION": "0"}, "must be 1"),
        ({"AMAZON_TOKEN_KEY_V1": "not-a-key"}, "base64url 32-byte"),
        ({"AMAZON_TOKEN_FINGERPRINT_PEPPER": "not-a-pepper"}, "base64url 32-byte"),
        (
            {"AMAZON_LWA_TOKEN_URL": "https://user:secret@api.amazon.com/auth/o2/token"},
            "official Amazon endpoint",
        ),
        (
            {"AMAZON_LWA_TOKEN_URL": "https://api.amazon.com/auth/o2/token?target=other"},
            "official Amazon endpoint",
        ),
        ({"AMAZON_OAUTH_ENABLED": "maybe"}, "must be true or false"),
    ],
)
def test_validator_rejects_unsafe_amazon_profile(overrides, reason_fragment) -> None:
    with pytest.raises(RCEnvironmentError) as exc_info:
        validate_rc_environment(_amazon_enabled_rc_env(**overrides))
    assert reason_fragment in exc_info.value.reason


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
