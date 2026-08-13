import os
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import OperationalError

from alembic import command
from app.core.migration_guard import validate_before_destructive_migration
from app.database.session import Base

EXPECTED_TABLES = {
    "users",
    "projects",
    "products",
    "generations",
    "generation_requests",
    "subscriptions",
    "alembic_version",
}


def _reset_migration_database(url: str) -> None:
    engine = create_engine(url, pool_pre_ping=True)
    validate_before_destructive_migration(
        environment=os.environ.get("ENVIRONMENT"),
        migration_test_database_url=url,
        engine=engine,
    )
    Base.metadata.drop_all(bind=engine)
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE IF EXISTS alembic_version"))
    engine.dispose()


@pytest.fixture(scope="module")
def migration_database_url():
    url = os.environ.get("MIGRATION_TEST_DATABASE_URL")
    if not url:
        pytest.fail("MIGRATION_TEST_DATABASE_URL is required for migration integration tests")

    database_url = os.environ.get("DATABASE_URL")
    if database_url and url == database_url:
        pytest.fail("MIGRATION_TEST_DATABASE_URL must differ from DATABASE_URL")

    validate_before_destructive_migration(
        environment=os.environ.get("ENVIRONMENT"),
        migration_test_database_url=url,
    )

    try:
        engine = create_engine(url, pool_pre_ping=True)
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        engine.dispose()
    except OperationalError as exc:
        pytest.fail(f"Migration test database unavailable: {exc}")

    _reset_migration_database(url)
    yield url
    _reset_migration_database(url)


def _normalize_ondelete(options: dict) -> str | None:
    value = options.get("ondelete")
    if value is None:
        return None
    return str(value).upper().replace(" ", "")


def _fk_ondelete(inspector, table: str, column: str) -> str | None:
    for fk in inspector.get_foreign_keys(table):
        if fk.get("constrained_columns") == [column]:
            return _normalize_ondelete(fk.get("options") or {})
    return None


def test_alembic_upgrade_downgrade_cycle(migration_database_url, monkeypatch):
    backend_root = Path(__file__).resolve().parents[1]
    cfg = Config(str(backend_root / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", migration_database_url)
    monkeypatch.setenv("ALEMBIC_DATABASE_URL", migration_database_url)

    command.upgrade(cfg, "head")

    engine = create_engine(migration_database_url, pool_pre_ping=True)
    inspector = inspect(engine)

    tables = set(inspector.get_table_names())
    assert EXPECTED_TABLES.issubset(tables)

    gen_req_columns = {column["name"] for column in inspector.get_columns("generation_requests")}
    assert {"estimated_tokens", "reserved_tokens", "idempotency_key", "request_hash"}.issubset(
        gen_req_columns
    )

    indexes = {idx["name"] for idx in inspector.get_indexes("generation_requests")}
    assert "ix_generation_requests_user_id" in indexes
    assert "ix_generation_requests_status_started_at" in indexes

    checks = {c["name"] for c in inspector.get_check_constraints("generation_requests")}
    assert "ck_generation_requests_status" in checks
    assert "ck_generation_requests_reserved_nonneg" in checks
    assert "ck_generation_requests_tokens_used_nonneg" in checks

    user_checks = {c["name"] for c in inspector.get_check_constraints("users")}
    assert "ck_users_used_tokens_nonneg" in user_checks
    assert "ck_users_reserved_tokens_nonneg" in user_checks

    reserved_col = next(
        c for c in inspector.get_columns("users") if c["name"] == "reserved_tokens"
    )
    assert reserved_col.get("default") is not None or reserved_col.get("server_default") is not None

    fks = inspector.get_foreign_keys("generation_requests")
    fk_map = {
        (tuple(fk["constrained_columns"]), fk["referred_table"]): fk.get("options", {})
        for fk in fks
    }
    assert (("user_id",), "users") in fk_map
    assert (("project_id",), "projects") in fk_map
    assert (("product_id",), "products") in fk_map
    assert (("generation_id",), "generations") in fk_map

    assert _fk_ondelete(inspector, "generation_requests", "user_id") == "CASCADE"
    assert _fk_ondelete(inspector, "generation_requests", "project_id") == "SETNULL"
    assert _fk_ondelete(inspector, "generation_requests", "product_id") == "SETNULL"
    assert _fk_ondelete(inspector, "generation_requests", "generation_id") == "SETNULL"

    user_columns = {column["name"] for column in inspector.get_columns("users")}
    assert "reserved_tokens" in user_columns

    unique = {
        tuple(constraint["column_names"])
        for constraint in inspector.get_unique_constraints("generation_requests")
    }
    assert ("user_id", "request_type", "idempotency_key") in unique

    with engine.connect() as connection:
        current = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        assert current == "a1b2c3d4e5f6"

    command.downgrade(cfg, "34b6d855017a")

    inspector_after_down = inspect(engine)
    assert "generation_requests" not in inspector_after_down.get_table_names()
    down_user_columns = {column["name"] for column in inspector_after_down.get_columns("users")}
    assert "reserved_tokens" not in down_user_columns
    down_user_checks = {c["name"] for c in inspector_after_down.get_check_constraints("users")}
    assert "ck_users_reserved_tokens_nonneg" not in down_user_checks

    command.upgrade(cfg, "head")

    inspector_reup = inspect(engine)
    assert "generation_requests" in inspector_reup.get_table_names()

    for table_name in [
        "users",
        "projects",
        "products",
        "generations",
        "generation_requests",
        "subscriptions",
    ]:
        model_columns = {column.name for column in Base.metadata.tables[table_name].columns}
        db_columns = {column["name"] for column in inspector_reup.get_columns(table_name)}
        missing = model_columns - db_columns
        assert not missing, f"{table_name} missing columns after re-upgrade: {missing}"

    engine.dispose()
