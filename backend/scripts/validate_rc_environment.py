"""Disposable RC Compose environment safety checks.

This guard applies only to the disposable RC docker-compose stack.
It does not replace staging/production deployment approval or migration guards.
"""

from __future__ import annotations

import ipaddress
import os
import sys
from urllib.parse import unquote, urlparse

RC_ALLOWED_ENVIRONMENTS = frozenset({"staging"})
RC_POSTGRES_HOST = "postgres"
RC_POSTGRES_PORT = 5432
JWT_PLACEHOLDER = "REPLACE_WITH_RUNTIME_GENERATED_SECRET_MIN_32_CHARS"
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


def _validate_postgres_db(postgres_db: str) -> None:
    if not postgres_db.endswith("_test"):
        raise RCEnvironmentError("database name must end with _test")


def _validate_jwt_secret(jwt_secret_key: str) -> None:
    if jwt_secret_key == JWT_PLACEHOLDER:
        raise RCEnvironmentError("JWT_SECRET_KEY placeholder must be replaced before startup")
    if len(jwt_secret_key) < 32:
        raise RCEnvironmentError("JWT_SECRET_KEY must be at least 32 characters")


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

    _validate_jwt_secret(jwt_secret_key)
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
