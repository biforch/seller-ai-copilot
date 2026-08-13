"""Safety checks before destructive migration-test database operations."""

from __future__ import annotations

import os
from urllib.parse import urlparse

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

ALLOWED_MIGRATION_TEST_DATABASES = frozenset(
    {
        "sellerai_migration_test",
        "sellerai_test",
    }
)


class MigrationGuardError(RuntimeError):
    """Raised when a destructive migration operation must be aborted."""


def _database_name_from_url(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path.lstrip("/")
    if not path:
        raise MigrationGuardError(f"Database URL has no database name: {url}")
    return path


def validate_migration_test_target(
    *,
    environment: str | None = None,
    migration_test_database_url: str | None = None,
) -> str:
    """Validate that destructive migration tests may run against the target database."""
    env = environment if environment is not None else os.environ.get("ENVIRONMENT", "")
    if env != "testing":
        raise MigrationGuardError(
            f"Refusing destructive migration operation: ENVIRONMENT must be 'testing', got {env!r}"
        )

    url = migration_test_database_url or os.environ.get("MIGRATION_TEST_DATABASE_URL")
    if not url:
        raise MigrationGuardError(
            "Refusing destructive migration operation: MIGRATION_TEST_DATABASE_URL is required"
        )

    fallback_url = os.environ.get("DATABASE_URL")
    if fallback_url and url == fallback_url:
        raise MigrationGuardError(
            "Refusing destructive migration operation: MIGRATION_TEST_DATABASE_URL "
            "must not equal DATABASE_URL"
        )

    db_name = _database_name_from_url(url)
    if not db_name.endswith("_test") and db_name not in ALLOWED_MIGRATION_TEST_DATABASES:
        raise MigrationGuardError(
            f"Refusing destructive migration operation: database {db_name!r} is not allowed"
        )

    return url


def assert_live_database_allowed(url: str, engine: Engine | None = None) -> str:
    """Verify current_database() matches the URL and is in the allow-list."""
    own_engine = engine is None
    live_engine = engine or create_engine(url, pool_pre_ping=True)
    try:
        with live_engine.connect() as connection:
            current_db = connection.execute(text("SELECT current_database()")).scalar_one()
    finally:
        if own_engine:
            live_engine.dispose()

    expected_db = _database_name_from_url(url)
    if current_db != expected_db:
        raise MigrationGuardError(
            f"Refusing destructive migration operation: connected database {current_db!r} "
            f"does not match URL database {expected_db!r}"
        )

    if not current_db.endswith("_test") and current_db not in ALLOWED_MIGRATION_TEST_DATABASES:
        raise MigrationGuardError(
            f"Refusing destructive migration operation: current_database() {current_db!r} "
            "is not in the migration test allow-list"
        )

    return current_db


def validate_before_destructive_migration(
    *,
    environment: str | None = None,
    migration_test_database_url: str | None = None,
    engine: Engine | None = None,
) -> str:
    """Run all checks required before DROP/DELETE/TRUNCATE in migration tests."""
    url = validate_migration_test_target(
        environment=environment,
        migration_test_database_url=migration_test_database_url,
    )
    assert_live_database_allowed(url, engine=engine)
    return url
