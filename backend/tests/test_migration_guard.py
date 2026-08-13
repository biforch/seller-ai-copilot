"""Pure validation tests for migration destructive-operation guard."""

import pytest

from app.core.migration_guard import MigrationGuardError, validate_before_destructive_migration


def test_migration_guard_rejects_missing_url(monkeypatch):
    monkeypatch.delenv("MIGRATION_TEST_DATABASE_URL", raising=False)
    with pytest.raises(MigrationGuardError, match="MIGRATION_TEST_DATABASE_URL is required"):
        validate_before_destructive_migration(
            environment="testing",
            migration_test_database_url=None,
        )


def test_migration_guard_rejects_non_testing_environment():
    with pytest.raises(MigrationGuardError, match="ENVIRONMENT must be 'testing'"):
        validate_before_destructive_migration(
            environment="production",
            migration_test_database_url="postgresql://localhost:5432/sellerai_migration_test",
        )


def test_migration_guard_rejects_dev_database_name():
    with pytest.raises(MigrationGuardError, match="not allowed"):
        validate_before_destructive_migration(
            environment="testing",
            migration_test_database_url="postgresql://localhost:5432/sellerai",
        )


def test_migration_guard_rejects_url_matching_database_url(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost:5432/sellerai_migration_test")
    with pytest.raises(MigrationGuardError, match="must not equal DATABASE_URL"):
        validate_before_destructive_migration(
            environment="testing",
            migration_test_database_url="postgresql://localhost:5432/sellerai_migration_test",
        )


def test_migration_guard_rejects_disguised_url_when_live_database_differs():
    with pytest.raises(MigrationGuardError, match="does not match URL database"):
        validate_before_destructive_migration(
            environment="testing",
            migration_test_database_url="postgresql://localhost:5432/sellerai_migration_test",
            engine=_FakeEngine("sellerai_prod"),
        )


def test_migration_guard_allows_valid_test_database():
    url = validate_before_destructive_migration(
        environment="testing",
        migration_test_database_url="postgresql://localhost:5432/sellerai_migration_test",
        engine=_FakeEngine("sellerai_migration_test"),
    )
    assert url.endswith("sellerai_migration_test")


class _FakeEngine:
    def __init__(self, database_name: str) -> None:
        self.database_name = database_name

    def connect(self):
        return _FakeConnection(self.database_name)

    def dispose(self) -> None:
        return None


class _FakeConnection:
    def __init__(self, database_name: str) -> None:
        self.database_name = database_name

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def execute(self, statement):
        return _FakeResult(self.database_name)


class _FakeResult:
    def __init__(self, database_name: str) -> None:
        self.database_name = database_name

    def scalar_one(self):
        return self.database_name
