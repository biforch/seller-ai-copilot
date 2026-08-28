"""Static and fail-closed checks for the non-deploying Render adapter."""

from __future__ import annotations

import base64
import os
import re
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from scripts.validate_render_production_environment import (  # noqa: E402
    RenderProductionEnvironmentError,
    validate_render_production_environment,
)

VALID_ENV = {
    "PORT": "8000",
    "ENVIRONMENT": "production",
    "DATABASE_URL": "postgresql://app:private-value@db.internal/listnara_prod",
    "JWT_SECRET_KEY": "x" * 32,
    "MFA_ENCRYPTION_KEY": base64.b64encode(b"m" * 32).decode("ascii"),
    "OPENAI_API_KEY": "private-value",
    "OPENAI_BASE_URL": "https://api.openai.com/v1",
    "OPENAI_AMAZON_DATA_ENABLED": "false",
    "CORS_ORIGINS": "https://app.listnara.com",
    "SESSION_COOKIE_SECURE": "true",
    "DEBUG": "false",
    "ANALYSIS_PUBLIC_ENABLED": "false",
    "LISTING_AUDIT_INTERNAL_ENABLED": "false",
    "AMAZON_SP_API_ENABLED": "false",
    "AMAZON_OAUTH_ENABLED": "false",
    "AMAZON_SP_API_ENDPOINT_MODE": "mock",
}

_SCALAR_TRUE = {"true", "True", "TRUE"}
_SCALAR_FALSE = {"false", "False", "FALSE"}


def load_strict_yaml_mapping(text: str) -> dict:
    """Parse a constrained YAML mapping with the stdlib only.

    The loader rejects tags, anchors, merge keys, and tabs so tests do not add
    a production YAML dependency. Unexpected syntax fails closed.
    """

    if "\t" in text:
        raise ValueError("tabs are not allowed")
    if re.search(r"(^|\s)[&*!|]>?", text, re.MULTILINE) and re.search(
        r"(^|\s)([&*][A-Za-z0-9_]+|!!?\w+)", text
    ):
        raise ValueError("YAML tags, anchors, and aliases are not allowed")

    lines: list[tuple[int, str]] = []
    for raw in text.splitlines():
        stripped = raw.split(" #", 1)[0].rstrip()
        if not stripped or stripped.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        if indent % 2 != 0:
            raise ValueError(f"non-even indent: {raw!r}")
        lines.append((indent, stripped.lstrip(" ")))
    value, next_index = _parse_block(lines, 0, lines[0][0] if lines else 0)
    if next_index != len(lines):
        raise ValueError("unconsumed YAML content")
    if not isinstance(value, dict):
        raise ValueError("blueprint root must be a mapping")
    return value


def _parse_scalar(raw: str):
    raw = raw.strip()
    if raw == "[]":
        return []
    if raw == "{}":
        return {}
    if raw in _SCALAR_TRUE:
        return True
    if raw in _SCALAR_FALSE:
        return False
    if raw in {"null", "~"}:
        return None
    if (raw.startswith('"') and raw.endswith('"')) or (
        raw.startswith("'") and raw.endswith("'")
    ):
        return raw[1:-1]
    if re.fullmatch(r"-?\d+", raw):
        return int(raw)
    return raw


def _parse_block(lines: list[tuple[int, str]], index: int, indent: int):
    if index >= len(lines):
        return {}, index
    _, content = lines[index]
    if content.startswith("- "):
        return _parse_list(lines, index, indent)
    return _parse_mapping(lines, index, indent)


def _parse_mapping(lines: list[tuple[int, str]], index: int, indent: int):
    mapping: dict[str, object] = {}
    while index < len(lines):
        current_indent, content = lines[index]
        if current_indent < indent:
            break
        if current_indent > indent:
            raise ValueError(f"unexpected nested indent at {content!r}")
        if content.startswith("- "):
            raise ValueError("list item where mapping key expected")
        if ":" not in content:
            raise ValueError(f"mapping line missing colon: {content!r}")
        key, rest = content.split(":", 1)
        key = key.strip()
        rest = rest.strip()
        index += 1
        if rest:
            mapping[key] = _parse_scalar(rest)
            continue
        if index >= len(lines) or lines[index][0] <= indent:
            mapping[key] = {}
            continue
        child_indent = lines[index][0]
        if child_indent <= indent:
            raise ValueError(f"invalid child indent for {key}")
        child, index = _parse_block(lines, index, child_indent)
        mapping[key] = child
    return mapping, index


def _parse_list(lines: list[tuple[int, str]], index: int, indent: int):
    items: list[object] = []
    while index < len(lines):
        current_indent, content = lines[index]
        if current_indent < indent:
            break
        if current_indent != indent or not content.startswith("- "):
            raise ValueError(f"invalid list item: {content!r}")
        item_body = content[2:].strip()
        index += 1
        if not item_body:
            if index >= len(lines) or lines[index][0] <= indent:
                items.append(None)
                continue
            child, index = _parse_block(lines, index, lines[index][0])
            items.append(child)
            continue
        if ":" in item_body and not (
            item_body.startswith('"') or item_body.startswith("'")
        ):
            key, rest = item_body.split(":", 1)
            item_map: dict[str, object] = {key.strip(): _parse_scalar(rest) if rest.strip() else {}}
            if rest.strip() == "" and index < len(lines) and lines[index][0] > indent:
                child, index = _parse_block(lines, index, lines[index][0])
                item_map[key.strip()] = child
            while index < len(lines):
                follow_indent, follow = lines[index]
                if follow_indent <= indent or follow.startswith("- "):
                    break
                if follow_indent != indent + 2:
                    # continuation keys of this list mapping
                    if follow_indent < indent + 2:
                        break
                nested_map, index = _parse_mapping(lines, index, follow_indent)
                if not isinstance(nested_map, dict):
                    raise ValueError("list mapping continuation must be a mapping")
                item_map.update(nested_map)
                break
            # continue consuming mapping keys at indent+2
            while index < len(lines):
                follow_indent, follow = lines[index]
                if follow_indent != indent + 2 or follow.startswith("- "):
                    break
                nested_map, index = _parse_mapping(lines, index, indent + 2)
                item_map.update(nested_map)
                break
            # The inner _parse_mapping already consumed all keys at that indent.
            # If we broke after one recursive parse, keys at indent+2 are consumed.
            items.append(item_map)
            continue
        items.append(_parse_scalar(item_body))
    return items, index


def _set_valid_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in VALID_ENV.items():
        monkeypatch.setenv(key, value)


def _env_vars_by_key(service: dict) -> dict[str, dict]:
    variables = {}
    for item in service.get("envVars", []):
        assert isinstance(item, dict), item
        key = item.get("key")
        assert isinstance(key, str) and key
        assert key not in variables, key
        variables[key] = item
    return variables


def test_environment_validator_accepts_disabled_amazon_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_valid_environment(monkeypatch)
    validate_render_production_environment()


@pytest.mark.parametrize(
    ("name", "value", "reason"),
    [
        ("AMAZON_SP_API_ENABLED", "true", "AMAZON_MUST_REMAIN_DISABLED"),
        ("AMAZON_OAUTH_ENABLED", "true", "AMAZON_MUST_REMAIN_DISABLED"),
        ("AMAZON_SP_API_ENDPOINT_MODE", "production", "AMAZON_ENDPOINT_NOT_MOCK"),
        ("OPENAI_AMAZON_DATA_ENABLED", "true", "AMAZON_AI_DATA_MUST_REMAIN_DISABLED"),
        ("OPENAI_BASE_URL", "https://openrouter.ai/api/v1", "OPENAI_BASE_URL_INVALID"),
        ("DATABASE_URL", "postgresql://app:x@db/listnara_test", "DATABASE_TARGET_INVALID"),
        ("SESSION_COOKIE_SECURE", "false", "SESSION_COOKIE_NOT_SECURE"),
        ("CORS_ORIGINS", "https://example.com", "CORS_ORIGIN_INVALID"),
        ("ENVIRONMENT", "staging", "ENVIRONMENT_NOT_PRODUCTION"),
        ("PORT", "10000", "BACKEND_PORT_INVALID"),
        ("ANALYSIS_PUBLIC_ENABLED", "true", "ANALYSIS_PUBLIC_MUST_REMAIN_DISABLED"),
        ("LISTING_AUDIT_INTERNAL_ENABLED", "true", "LISTING_AUDIT_MUST_REMAIN_DISABLED"),
    ],
)
def test_environment_validator_fails_closed(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str, reason: str
) -> None:
    _set_valid_environment(monkeypatch)
    monkeypatch.setenv(name, value)
    with pytest.raises(RenderProductionEnvironmentError, match=reason):
        validate_render_production_environment()


def test_validator_requires_mfa_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_valid_environment(monkeypatch)
    monkeypatch.delenv("MFA_ENCRYPTION_KEY", raising=False)
    with pytest.raises(RenderProductionEnvironmentError, match="MISSING:MFA_ENCRYPTION_KEY"):
        validate_render_production_environment()


@pytest.mark.parametrize(
    ("value", "reason"),
    [
        ("not-base64", "MFA_KEY_INVALID_BASE64"),
        (base64.b64encode(b"m" * 31).decode("ascii"), "MFA_KEY_INVALID_LENGTH"),
        (base64.b64encode(b"m" * 33).decode("ascii"), "MFA_KEY_INVALID_LENGTH"),
    ],
)
def test_validator_rejects_invalid_mfa_key(
    monkeypatch: pytest.MonkeyPatch, value: str, reason: str
) -> None:
    _set_valid_environment(monkeypatch)
    monkeypatch.setenv("MFA_ENCRYPTION_KEY", value)
    with pytest.raises(RenderProductionEnvironmentError, match=reason):
        validate_render_production_environment()


def test_validator_cli_does_not_echo_secrets() -> None:
    env = os.environ.copy()
    env.update(VALID_ENV)
    secret = "do-not-print-this-value"
    env["OPENAI_API_KEY"] = secret
    env["MFA_ENCRYPTION_KEY"] = secret
    env["AMAZON_SP_API_ENABLED"] = "true"
    result = subprocess.run(
        [sys.executable, str(BACKEND_ROOT / "scripts" / "validate_render_production_environment.py")],
        env=env,
        capture_output=True,
        check=False,
        text=True,
    )
    assert result.returncode == 1
    assert result.stdout.strip() == "RENDER_PRODUCTION_ENVIRONMENT_INVALID"
    assert secret not in result.stdout + result.stderr


def test_blueprint_yaml_structure_is_private_manual_and_amazon_disabled() -> None:
    blueprint_text = (REPO_ROOT / "render.yaml").read_text()
    assert "generateValue" not in blueprint_text
    blueprint = load_strict_yaml_mapping(blueprint_text)
    _assert_blueprint_release_guards(blueprint)
    services = blueprint["services"]
    databases = blueprint["databases"]
    assert isinstance(services, list) and len(services) == 3
    assert isinstance(databases, list) and len(databases) == 1

    by_name = {service["name"]: service for service in services}
    edge = by_name["listnara-edge"]
    frontend = by_name["listnara-frontend"]
    backend = by_name["listnara-backend"]
    postgres = databases[0]

    assert edge["type"] == "web"
    assert edge["dockerfilePath"] == "./nginx/Dockerfile.render"
    assert edge["autoDeployTrigger"] == "off"
    assert edge["renderSubdomainPolicy"] == "disabled"
    assert edge["domains"] == ["app.listnara.com"]
    assert edge["healthCheckPath"] == "/health/ready"

    assert frontend["type"] == "pserv"
    assert frontend["dockerfilePath"] == "./frontend/Dockerfile.prod"
    assert frontend["autoDeployTrigger"] == "off"

    assert backend["type"] == "pserv"
    assert backend["dockerfilePath"] == "./backend/Dockerfile.prod"
    assert backend["autoDeployTrigger"] == "off"
    assert backend["preDeployCommand"] == (
        "python scripts/validate_render_production_environment.py && alembic upgrade head"
    )

    # Render Blueprint `pserv` is the documented private-service type. If this
    # field is missing or a public `web` type, fail closed rather than guess.
    public_types = [service["name"] for service in services if service.get("type") != "pserv"]
    assert public_types == ["listnara-edge"]

    edge_vars = _env_vars_by_key(edge)
    assert edge_vars["BACKEND_HOSTPORT"]["fromService"] == {
        "type": "pserv",
        "name": "listnara-backend",
        "property": "hostport",
    }
    assert edge_vars["FRONTEND_HOSTPORT"]["fromService"] == {
        "type": "pserv",
        "name": "listnara-frontend",
        "property": "hostport",
    }

    backend_vars = _env_vars_by_key(backend)
    assert backend_vars["PORT"]["value"] == "8000"
    assert backend_vars["ENVIRONMENT"]["value"] == "production"
    assert backend_vars["CORS_ORIGINS"]["value"] == "https://app.listnara.com"
    assert backend_vars["SESSION_COOKIE_SECURE"]["value"] == "true"
    assert backend_vars["DEBUG"]["value"] == "false"
    assert backend_vars["ANALYSIS_PUBLIC_ENABLED"]["value"] == "false"
    assert backend_vars["LISTING_AUDIT_INTERNAL_ENABLED"]["value"] == "false"
    assert backend_vars["AMAZON_SP_API_ENABLED"]["value"] == "false"
    assert backend_vars["AMAZON_OAUTH_ENABLED"]["value"] == "false"
    assert backend_vars["AMAZON_SP_API_ENDPOINT_MODE"]["value"] == "mock"
    assert backend_vars["DATABASE_URL"]["fromDatabase"] == {
        "name": "listnara-postgres",
        "property": "connectionString",
    }
    assert backend_vars["JWT_SECRET_KEY"] == {"key": "JWT_SECRET_KEY", "sync": False}
    assert backend_vars["MFA_ENCRYPTION_KEY"] == {
        "key": "MFA_ENCRYPTION_KEY",
        "sync": False,
    }
    assert backend_vars["OPENAI_API_KEY"] == {"key": "OPENAI_API_KEY", "sync": False}
    assert "value" not in backend_vars["JWT_SECRET_KEY"]
    assert "generateValue" not in backend_vars["JWT_SECRET_KEY"]
    assert "value" not in backend_vars["MFA_ENCRYPTION_KEY"]
    assert "generateValue" not in backend_vars["MFA_ENCRYPTION_KEY"]

    for item in backend_vars.values():
        if "value" in item:
            assert item["value"] not in {"", None}
            text_value = str(item["value"])
            assert "sk-" not in text_value
            assert "postgresql://" not in text_value
        assert "generateValue" not in item

    assert postgres["name"] == "listnara-postgres"
    assert postgres["postgresMajorVersion"] == "16"
    assert postgres["ipAllowList"] == []


def _assert_blueprint_release_guards(blueprint: dict) -> None:
    services = blueprint["services"]
    by_name = {service["name"]: service for service in services}
    edge = by_name["listnara-edge"]
    backend = by_name["listnara-backend"]
    backend_vars = _env_vars_by_key(backend)
    assert edge["autoDeployTrigger"] == "off"
    assert edge["renderSubdomainPolicy"] == "disabled"
    assert backend["autoDeployTrigger"] == "off"
    assert backend_vars["PORT"] == {"key": "PORT", "value": "8000"}
    for name in ("JWT_SECRET_KEY", "MFA_ENCRYPTION_KEY", "OPENAI_API_KEY"):
        assert backend_vars[name] == {"key": name, "sync": False}
        assert "generateValue" not in backend_vars[name]


@pytest.mark.parametrize("invalid_port", [None, "10000"])
def test_blueprint_release_guards_reject_invalid_backend_port(invalid_port: str | None) -> None:
    blueprint = load_strict_yaml_mapping((REPO_ROOT / "render.yaml").read_text())
    mutated = deepcopy(blueprint)
    backend = next(service for service in mutated["services"] if service["name"] == "listnara-backend")
    port = next(item for item in backend["envVars"] if item["key"] == "PORT")
    if invalid_port is None:
        backend["envVars"].remove(port)
    else:
        port["value"] = invalid_port
    with pytest.raises((AssertionError, KeyError)):
        _assert_blueprint_release_guards(mutated)


@pytest.mark.parametrize(
    "mutation",
    ["generated-secret", "generated-mfa-secret", "auto-deploy", "public-subdomain"],
)
def test_blueprint_release_guards_reject_unsafe_mutations(mutation: str) -> None:
    blueprint = load_strict_yaml_mapping((REPO_ROOT / "render.yaml").read_text())
    mutated = deepcopy(blueprint)
    by_name = {service["name"]: service for service in mutated["services"]}
    if mutation == "generated-secret":
        jwt = next(item for item in by_name["listnara-backend"]["envVars"] if item["key"] == "JWT_SECRET_KEY")
        jwt["generateValue"] = True
    elif mutation == "generated-mfa-secret":
        mfa = next(
            item
            for item in by_name["listnara-backend"]["envVars"]
            if item["key"] == "MFA_ENCRYPTION_KEY"
        )
        mfa["generateValue"] = True
    elif mutation == "auto-deploy":
        by_name["listnara-backend"]["autoDeployTrigger"] = "commit"
    else:
        by_name["listnara-edge"]["renderSubdomainPolicy"] = "enabled"
    with pytest.raises(AssertionError):
        _assert_blueprint_release_guards(mutated)


def test_render_edge_suppresses_callback_access_log_and_overwrites_proto() -> None:
    nginx = (REPO_ROOT / "nginx" / "nginx.render.conf.template").read_text()
    callback = nginx.index("location = /api/v1/amazon/oauth/callback")
    generic_api = nginx.index("location /api/")
    assert callback < generic_api
    callback_block = nginx[callback:generic_api]
    access_log_lines = re.findall(r"(?m)^\s*access_log\s+[^;]+;", callback_block)
    assert len(access_log_lines) == 1
    assert access_log_lines[0].strip() == "access_log off;"
    assert "limit_req_log_level notice;" in nginx
    assert "proxy_set_header X-Forwarded-Proto https;" in nginx
    assert "Strict-Transport-Security" in nginx
    assert "$http_cf_connecting_ip" not in nginx
    assert "limit_req_zone $binary_remote_addr" in nginx


def test_callback_log_contract_rejects_a_second_access_log_directive() -> None:
    nginx = (REPO_ROOT / "nginx" / "nginx.render.conf.template").read_text()
    callback = nginx.index("location = /api/v1/amazon/oauth/callback")
    generic_api = nginx.index("location /api/")
    callback_block = nginx[callback:generic_api] + "\naccess_log on;\n"
    access_log_lines = re.findall(r"(?m)^\s*access_log\s+[^;]+;", callback_block)
    with pytest.raises(AssertionError):
        assert len(access_log_lines) == 1


def test_render_dockerfile_limits_template_substitution() -> None:
    dockerfile = (REPO_ROOT / "nginx" / "Dockerfile.render").read_text()
    rc_dockerfile = (REPO_ROOT / "nginx" / "Dockerfile.rc").read_text()
    assert "NGINX_ENVSUBST_FILTER" in dockerfile
    assert "BACKEND_HOSTPORT" in dockerfile
    assert "FRONTEND_HOSTPORT" in dockerfile
    assert "HEALTHCHECK" in dockerfile
    assert "CMD wget" in dockerfile
    assert "CMD-SHELL" not in dockerfile
    security_pin = "apk add --no-cache libcrypto3=3.5.8-r0 libssl3=3.5.8-r0"
    assert security_pin in dockerfile
    assert security_pin in rc_dockerfile
    assert "apk upgrade" not in dockerfile
