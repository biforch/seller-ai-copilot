"""Disposable RC Compose environment safety checks.

This guard applies only to the disposable RC docker-compose stack.
It does not replace staging/production deployment approval or migration guards.
"""

from __future__ import annotations

import base64
import binascii
import ipaddress
import os
import sys
from urllib.parse import unquote, urlparse

RC_ALLOWED_ENVIRONMENTS = frozenset({"staging"})
RC_POSTGRES_HOST = "postgres"
RC_POSTGRES_PORT = 5432
JWT_PLACEHOLDER = "REPLACE_WITH_RUNTIME_GENERATED_SECRET_MIN_32_CHARS"
MFA_KEY_PLACEHOLDER = "REPLACE_WITH_BASE64_ENCODED_32_BYTE_KEY"
DB_PASSWORD_PLACEHOLDER = "REPLACE_WITH_RC_DATABASE_PASSWORD"
LEGACY_DB_PASSWORD = "rc-local-only-change-me"
SUCCESS_MESSAGE = "RC environment safety check passed"
FAILURE_PREFIX = "RC environment safety check failed"


class RCEnvironmentError(Exception):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _require(env: dict[str, str], key: str) -> str:
    value = env.get(key, "").strip()
    if not value:
        raise RCEnvironmentError(f"{key} is required")
    return value


def _strict_bool(env: dict[str, str], key: str, *, default: bool = False) -> bool:
    raw = env.get(key, "true" if default else "false").strip().lower()
    if raw not in {"true", "false"}:
        raise RCEnvironmentError(f"{key} must be true or false")
    return raw == "true"


def _validate_https_url(env: dict[str, str], key: str) -> None:
    value = _require(env, key)
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc:
        raise RCEnvironmentError(f"{key} must be an absolute HTTPS URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise RCEnvironmentError(f"{key} must not include userinfo, query, or fragment")


def _decode_32_byte_base64url(value: str) -> None:
    padding = "=" * (-len(value) % 4)
    try:
        raw = base64.b64decode(value + padding, altchars=b"-_", validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("invalid base64url value") from None
    if len(raw) != 32:
        raise ValueError("value must decode to 32 bytes")


def _validate_amazon_configuration(env: dict[str, str]) -> None:
    sp_api_enabled = _strict_bool(env, "AMAZON_SP_API_ENABLED")
    oauth_enabled = _strict_bool(env, "AMAZON_OAUTH_ENABLED")
    if oauth_enabled and not sp_api_enabled:
        raise RCEnvironmentError(
            "AMAZON_OAUTH_ENABLED requires AMAZON_SP_API_ENABLED=true"
        )
    if not sp_api_enabled:
        return

    if _require(env, "AMAZON_SP_API_ENDPOINT_MODE") != "production":
        raise RCEnvironmentError(
            "enabled Amazon SP-API requires AMAZON_SP_API_ENDPOINT_MODE=production"
        )
    if _require(env, "AMAZON_SP_API_REGION") not in {"na", "eu", "fe"}:
        raise RCEnvironmentError("AMAZON_SP_API_REGION must be na, eu, or fe")
    _require(env, "AMAZON_LWA_CLIENT_ID")
    _require(env, "AMAZON_LWA_CLIENT_SECRET")
    _require(env, "AMAZON_SP_API_USER_AGENT")
    token_url = _require(env, "AMAZON_LWA_TOKEN_URL")
    parsed_token_url = urlparse(token_url)
    if (
        parsed_token_url.scheme != "https"
        or parsed_token_url.hostname != "api.amazon.com"
        or parsed_token_url.path != "/auth/o2/token"
        or parsed_token_url.username
        or parsed_token_url.password
        or parsed_token_url.query
        or parsed_token_url.fragment
    ):
        raise RCEnvironmentError("AMAZON_LWA_TOKEN_URL must be the official Amazon endpoint")

    if _require(env, "AMAZON_TOKEN_ACTIVE_KEY_VERSION") != "1":
        raise RCEnvironmentError("AMAZON_TOKEN_ACTIVE_KEY_VERSION must be 1")
    for key in ("AMAZON_TOKEN_KEY_V1", "AMAZON_TOKEN_FINGERPRINT_PEPPER"):
        try:
            _decode_32_byte_base64url(_require(env, key))
        except ValueError:
            raise RCEnvironmentError(f"{key} must be a base64url 32-byte value") from None

    if not oauth_enabled:
        return
    _require(env, "AMAZON_SP_API_APPLICATION_ID")
    for key in (
        "AMAZON_OAUTH_REDIRECT_URI",
        "AMAZON_OAUTH_FRONTEND_SUCCESS_URL",
        "AMAZON_OAUTH_FRONTEND_ERROR_URL",
    ):
        _validate_https_url(env, key)
    if env.get("AMAZON_OAUTH_CONSENT_VERSION", "").strip() not in {"", "beta"}:
        raise RCEnvironmentError("AMAZON_OAUTH_CONSENT_VERSION must be empty or beta")
    try:
        ttl = int(_require(env, "AMAZON_OAUTH_STATE_TTL_SECONDS"))
    except ValueError:
        raise RCEnvironmentError("AMAZON_OAUTH_STATE_TTL_SECONDS must be 300-900") from None
    if ttl < 300 or ttl > 900:
        raise RCEnvironmentError("AMAZON_OAUTH_STATE_TTL_SECONDS must be 300-900")


def _validate_postgres_db(postgres_db: str) -> None:
    if not postgres_db.endswith("_test"):
        raise RCEnvironmentError("database name must end with _test")


def _validate_jwt_secret(jwt_secret_key: str) -> None:
    if jwt_secret_key == JWT_PLACEHOLDER:
        raise RCEnvironmentError("JWT_SECRET_KEY placeholder must be replaced before startup")
    if len(jwt_secret_key) < 32:
        raise RCEnvironmentError("JWT_SECRET_KEY must be at least 32 characters")


def _validate_mfa_key(value: str) -> None:
    if value == MFA_KEY_PLACEHOLDER:
        raise RCEnvironmentError("MFA_ENCRYPTION_KEY placeholder must be replaced before startup")
    try:
        decoded = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        raise RCEnvironmentError("MFA_ENCRYPTION_KEY must be valid base64") from None
    if len(decoded) != 32:
        raise RCEnvironmentError("MFA_ENCRYPTION_KEY must encode exactly 32 bytes")


def _validate_database_url_host(hostname: str) -> None:
    lowered = hostname.lower()
    if lowered in {"localhost", "127.0.0.1", "::1"}:
        raise RCEnvironmentError("database host must be the RC postgres service")

    try:
        ip = ipaddress.ip_address(lowered.strip("[]"))
    except ValueError:
        if lowered != RC_POSTGRES_HOST:
            raise RCEnvironmentError("database host must be the RC postgres service")
        return

    if ip.is_loopback or ip.is_private or ip.is_link_local:
        raise RCEnvironmentError("database host must be the RC postgres service")

    raise RCEnvironmentError("database host must be the RC postgres service")


def _validate_database_url_port(parsed) -> None:
    host_part = parsed.netloc.rsplit("@", 1)[-1]
    if not parsed.hostname or ":" not in host_part:
        return

    if host_part.startswith("["):
        bracket_end = host_part.find("]")
        if bracket_end != -1 and len(host_part) > bracket_end + 1 and host_part[bracket_end + 1] == ":":
            port_text = host_part[bracket_end + 2 :]
        else:
            return
    else:
        port_text = host_part.rsplit(":", 1)[-1]

    if not port_text.isdigit():
        raise RCEnvironmentError("DATABASE_URL port must be 5432 when specified")

    if int(port_text) != RC_POSTGRES_PORT:
        raise RCEnvironmentError("DATABASE_URL port must be 5432 when specified")


def _parse_database_url(database_url: str) -> dict[str, str | int | None]:
    parsed = urlparse(database_url)

    if parsed.query:
        raise RCEnvironmentError("DATABASE_URL must not include query parameters")
    if parsed.fragment:
        raise RCEnvironmentError("DATABASE_URL must not include a fragment")
    if parsed.params:
        raise RCEnvironmentError("DATABASE_URL must not include params")

    scheme = parsed.scheme.lower()
    if scheme not in {"postgresql", "postgres"}:
        raise RCEnvironmentError("DATABASE_URL must use a PostgreSQL scheme")

    if not parsed.hostname:
        raise RCEnvironmentError("DATABASE_URL must include a database host")

    username = unquote(parsed.username or "")
    password = unquote(parsed.password or "")

    if not username:
        raise RCEnvironmentError("DATABASE_URL must include a username")
    if not password:
        raise RCEnvironmentError("DATABASE_URL must include a password")

    database_name = parsed.path.lstrip("/").split("/", 1)[0]
    if not database_name:
        raise RCEnvironmentError("DATABASE_URL must include a database name")

    _validate_database_url_port(parsed)

    return {
        "hostname": parsed.hostname,
        "port": parsed.port,
        "username": username,
        "password": password,
        "database_name": database_name,
    }


def _validate_placeholders(
    *,
    postgres_password: str,
    database_url: str,
) -> None:
    if postgres_password in {DB_PASSWORD_PLACEHOLDER, LEGACY_DB_PASSWORD}:
        raise RCEnvironmentError("POSTGRES_PASSWORD placeholder must be replaced before startup")

    if DB_PASSWORD_PLACEHOLDER in database_url or LEGACY_DB_PASSWORD in database_url:
        raise RCEnvironmentError("DATABASE_URL password placeholder must be replaced before startup")


def validate_rc_environment(environ: dict[str, str] | None = None) -> None:
    env = dict(environ if environ is not None else os.environ)

    environment = _require(env, "ENVIRONMENT")
    if environment not in RC_ALLOWED_ENVIRONMENTS:
        allowed = ", ".join(sorted(RC_ALLOWED_ENVIRONMENTS))
        raise RCEnvironmentError(
            f"ENVIRONMENT must be one of the disposable RC values: {allowed}"
        )

    postgres_user = _require(env, "POSTGRES_USER")
    postgres_db = _require(env, "POSTGRES_DB")
    _validate_postgres_db(postgres_db)

    postgres_password = _require(env, "POSTGRES_PASSWORD")
    database_url = _require(env, "DATABASE_URL")
    jwt_secret_key = _require(env, "JWT_SECRET_KEY")
    mfa_encryption_key = _require(env, "MFA_ENCRYPTION_KEY")

    _validate_jwt_secret(jwt_secret_key)
    _validate_mfa_key(mfa_encryption_key)
    _validate_placeholders(
        postgres_password=postgres_password,
        database_url=database_url,
    )

    url_parts = _parse_database_url(database_url)
    hostname = str(url_parts["hostname"])
    database_name = str(url_parts["database_name"])
    url_username = str(url_parts["username"])
    url_password = str(url_parts["password"])

    _validate_database_url_host(hostname)
    _validate_postgres_db(database_name)

    if database_name != postgres_db:
        raise RCEnvironmentError("DATABASE_URL database name must match POSTGRES_DB")

    if url_username != postgres_user:
        raise RCEnvironmentError("DATABASE_URL username must match POSTGRES_USER")

    if url_password != postgres_password:
        raise RCEnvironmentError("DATABASE_URL password must match POSTGRES_PASSWORD")

    session_cookie_secure = env.get("SESSION_COOKIE_SECURE", "").strip().lower()
    if session_cookie_secure not in {"true", "false"}:
        raise RCEnvironmentError("SESSION_COOKIE_SECURE must be true or false")
    if session_cookie_secure != "false":
        raise RCEnvironmentError(
            "SESSION_COOKIE_SECURE must be false for the loopback HTTP RC stack"
        )

    _validate_amazon_configuration(env)


def main() -> int:
    try:
        validate_rc_environment()
    except RCEnvironmentError as exc:
        print(f"{FAILURE_PREFIX}: {exc.reason}", file=sys.stderr)
        return 1

    print(SUCCESS_MESSAGE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
