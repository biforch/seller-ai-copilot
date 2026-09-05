import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import OperationalError

from alembic import command
from alembic.config import Config
from app.core.migration_guard import validate_before_destructive_migration
from app.database.session import Base

EXPECTED_TABLES = {
    "users",
    "projects",
    "products",
    "generations",
    "generation_requests",
    "listing_versions",
    "listing_proposals",
    "subscriptions",
    "amazon_accounts",
    "amazon_marketplace_participations",
    "amazon_sync_logs",
    "amazon_listings",
    "amazon_oauth_states",
    "amazon_catalog_snapshots",
    "auth_sessions",
    "alembic_version",
}


def _reset_migration_database(url: str) -> None:
    engine = create_engine(url, pool_pre_ping=True)
    validate_before_destructive_migration(
        environment=os.environ.get("ENVIRONMENT"),
        migration_test_database_url=url,
        engine=engine,
    )
    with engine.begin() as connection:
        table_names = connection.execute(
            text(
                """
                SELECT tablename
                FROM pg_tables
                WHERE schemaname = 'public'
                """
            )
        ).scalars()
        for table_name in table_names:
            connection.execute(text(f'DROP TABLE IF EXISTS "{table_name}" CASCADE'))
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
    assert "ck_users_failed_login_attempts_range" in user_checks

    reserved_col = next(c for c in inspector.get_columns("users") if c["name"] == "reserved_tokens")
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
    assert {"failed_login_attempts", "locked_until"}.issubset(user_columns)

    unique = {
        tuple(constraint["column_names"])
        for constraint in inspector.get_unique_constraints("generation_requests")
    }
    assert ("user_id", "request_type", "idempotency_key") in unique

    with engine.connect() as connection:
        current = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        assert current == "4e5f6a7b8c9d"

    amazon_unique = {
        tuple(constraint["column_names"])
        for constraint in inspector.get_unique_constraints("amazon_accounts")
    }
    assert ("account_key",) in amazon_unique
    assert ("user_id", "refresh_token_fingerprint") in amazon_unique
    assert ("selling_partner_id",) in amazon_unique
    assert ("user_id", "region", "endpoint_mode") not in amazon_unique

    account_checks = {c["name"] for c in inspector.get_check_constraints("amazon_accounts")}
    assert "ck_amazon_accounts_key_version_max" in account_checks
    assert "ck_amazon_accounts_region" in account_checks
    assert "ck_amazon_accounts_endpoint_mode" in account_checks
    assert "ck_amazon_accounts_status" in account_checks
    assert "ck_amazon_accounts_selling_partner_id_format" in account_checks

    account_indexes = {idx["name"] for idx in inspector.get_indexes("amazon_accounts")}
    assert "ix_amazon_accounts_selling_partner_id" not in account_indexes

    amp_columns = {
        column["name"] for column in inspector.get_columns("amazon_marketplace_participations")
    }
    assert "sync_eligible" not in amp_columns

    amp_unique = {
        tuple(constraint["column_names"])
        for constraint in inspector.get_unique_constraints("amazon_marketplace_participations")
    }
    assert ("amazon_account_id", "marketplace_id") in amp_unique

    sync_checks = {c["name"] for c in inspector.get_check_constraints("amazon_sync_logs")}
    assert "ck_amazon_sync_logs_operation" in sync_checks
    assert "ck_amazon_sync_logs_status" in sync_checks
    assert "ck_amazon_sync_logs_items_seen_nonneg" in sync_checks

    assert _fk_ondelete(inspector, "amazon_accounts", "user_id") == "CASCADE"
    assert (
        _fk_ondelete(inspector, "amazon_marketplace_participations", "amazon_account_id")
        == "CASCADE"
    )
    assert _fk_ondelete(inspector, "amazon_sync_logs", "amazon_account_id") == "CASCADE"

    account_columns = {column["name"] for column in inspector.get_columns("amazon_accounts")}
    assert "selling_partner_id" in account_columns
    selling_partner_col = next(
        c for c in inspector.get_columns("amazon_accounts") if c["name"] == "selling_partner_id"
    )
    assert selling_partner_col["nullable"] is True

    listing_columns = {column["name"] for column in inspector.get_columns("amazon_listings")}
    assert {
        "amazon_account_id",
        "marketplace_id",
        "seller_sku",
        "asin",
        "product_id",
        "status_codes",
        "product_type",
        "upstream_created_at",
        "upstream_last_updated_at",
        "is_active",
        "last_seen_sync_id",
        "first_seen_at",
        "last_seen_at",
    }.issubset(listing_columns)

    listing_unique = {
        tuple(constraint["column_names"])
        for constraint in inspector.get_unique_constraints("amazon_listings")
    }
    assert ("amazon_account_id", "marketplace_id", "seller_sku") in listing_unique
    assert ("asin",) not in listing_unique
    assert ("marketplace_id", "asin") not in listing_unique

    listing_checks = {c["name"] for c in inspector.get_check_constraints("amazon_listings")}
    assert "ck_amazon_listings_status_codes_array" in listing_checks
    assert "ck_amazon_listings_marketplace_id_not_blank" in listing_checks
    assert "ck_amazon_listings_seller_sku_not_blank" in listing_checks

    listing_indexes = {idx["name"] for idx in inspector.get_indexes("amazon_listings")}
    assert "ix_amazon_listings_account_marketplace_updated" in listing_indexes
    assert "ix_amazon_listings_product_id" in listing_indexes
    assert "ix_amazon_listings_account_marketplace_last_seen_sync" in listing_indexes
    assert "ix_amazon_listings_asin" in listing_indexes

    assert _fk_ondelete(inspector, "amazon_listings", "amazon_account_id") == "CASCADE"
    assert _fk_ondelete(inspector, "amazon_listings", "product_id") == "SETNULL"

    catalog_columns = {
        column["name"] for column in inspector.get_columns("amazon_catalog_snapshots")
    }
    assert {
        "amazon_listing_id",
        "content_hash",
        "asin",
        "marketplace_id",
        "item_name",
        "brand",
        "manufacturer",
        "product_type",
        "source_request_id",
        "fetched_at",
        "expires_at",
    }.issubset(catalog_columns)
    catalog_unique = {
        tuple(constraint["column_names"])
        for constraint in inspector.get_unique_constraints("amazon_catalog_snapshots")
    }
    assert ("amazon_listing_id", "content_hash") in catalog_unique
    catalog_checks = {
        check["name"] for check in inspector.get_check_constraints("amazon_catalog_snapshots")
    }
    assert "ck_amazon_catalog_snapshots_content_hash_format" in catalog_checks
    assert "ck_amazon_catalog_snapshots_asin_format" in catalog_checks
    assert "ck_amazon_catalog_snapshots_marketplace_not_blank" in catalog_checks
    assert "ck_amazon_catalog_snapshots_expires_after_fetch" in catalog_checks
    catalog_indexes = {index["name"] for index in inspector.get_indexes("amazon_catalog_snapshots")}
    assert "ix_amazon_catalog_snapshots_listing_fetched" in catalog_indexes
    assert "ix_amazon_catalog_snapshots_expires_at" in catalog_indexes
    assert (
        _fk_ondelete(
            inspector,
            "amazon_catalog_snapshots",
            "amazon_listing_id",
        )
        == "CASCADE"
    )

    auth_session_columns = {column["name"] for column in inspector.get_columns("auth_sessions")}
    assert {
        "id",
        "user_id",
        "jti_hash",
        "csrf_token_hash",
        "expires_at",
        "revoked_at",
        "mfa_verified_at",
        "mfa_failed_attempts",
        "created_at",
    }.issubset(auth_session_columns)
    auth_session_checks = {
        check["name"] for check in inspector.get_check_constraints("auth_sessions")
    }
    assert "ck_auth_sessions_mfa_failed_attempts_range" in auth_session_checks
    auth_session_unique = {
        tuple(constraint["column_names"])
        for constraint in inspector.get_unique_constraints("auth_sessions")
    }
    assert ("jti_hash",) in auth_session_unique
    auth_session_indexes = {index["name"] for index in inspector.get_indexes("auth_sessions")}
    assert "ix_auth_sessions_user_id_revoked_at" in auth_session_indexes
    assert "ix_auth_sessions_expires_at" in auth_session_indexes
    assert _fk_ondelete(inspector, "auth_sessions", "user_id") == "CASCADE"

    user_columns = {column["name"] for column in inspector.get_columns("users")}
    assert {
        "mfa_secret_ciphertext",
        "mfa_enabled_at",
        "mfa_recovery_code_hashes",
        "mfa_last_totp_counter",
    }.issubset(user_columns)

    oauth_state_columns = {
        column["name"] for column in inspector.get_columns("amazon_oauth_states")
    }
    assert {
        "id",
        "state_token_hash",
        "user_id",
        "marketplace_code",
        "region",
        "intent",
        "target_account_id",
        "status",
        "expires_at",
        "consumed_at",
        "created_at",
    }.issubset(oauth_state_columns)

    oauth_state_checks = {c["name"] for c in inspector.get_check_constraints("amazon_oauth_states")}
    assert "ck_amazon_oauth_states_state_token_hash_format" in oauth_state_checks
    assert "ck_amazon_oauth_states_intent_target_account" in oauth_state_checks
    assert "ck_amazon_oauth_states_status_consumed_at" in oauth_state_checks
    assert "ck_amazon_oauth_states_expires_after_created" in oauth_state_checks

    oauth_state_indexes = {idx["name"] for idx in inspector.get_indexes("amazon_oauth_states")}
    assert "ix_amazon_oauth_states_status_expires_at" in oauth_state_indexes
    assert "ix_amazon_oauth_states_user_id_created_at" in oauth_state_indexes
    assert "ix_amazon_oauth_states_target_account_id" in oauth_state_indexes

    oauth_state_unique = {
        tuple(constraint["column_names"])
        for constraint in inspector.get_unique_constraints("amazon_oauth_states")
    }
    assert ("state_token_hash",) in oauth_state_unique

    assert _fk_ondelete(inspector, "amazon_oauth_states", "user_id") == "CASCADE"
    assert _fk_ondelete(inspector, "amazon_oauth_states", "target_account_id") == "CASCADE"

    listing_version_indexes = {idx["name"] for idx in inspector.get_indexes("listing_versions")}
    assert "ix_listing_versions_product_id_created_at" in listing_version_indexes
    listing_unique = {
        tuple(constraint["column_names"])
        for constraint in inspector.get_unique_constraints("listing_versions")
    }
    assert ("product_id", "version_number") in listing_unique
    assert ("product_id", "operation_idempotency_key") in listing_unique

    proposal_indexes = {idx["name"] for idx in inspector.get_indexes("listing_proposals")}
    assert "ix_listing_proposals_product_id_status" in proposal_indexes
    assert "ix_listing_proposals_product_id_created_at" in proposal_indexes
    assert "uq_listing_proposals_generation_request_id" in proposal_indexes

    product_columns = {column["name"] for column in inspector.get_columns("products")}
    assert "current_listing_version_id" in product_columns
    assert _fk_ondelete(inspector, "products", "current_listing_version_id") == "SETNULL"
    product_fks = inspector.get_foreign_keys("products")
    current_fk = next(
        fk for fk in product_fks if fk.get("constrained_columns") == ["current_listing_version_id"]
    )
    assert current_fk["name"] == "fk_products_current_listing_version_id_listing_versions"

    assert _fk_ondelete(inspector, "listing_versions", "product_id") == "CASCADE"
    assert _fk_ondelete(inspector, "listing_versions", "generation_id") == "SETNULL"
    assert _fk_ondelete(inspector, "listing_versions", "created_by") == "SETNULL"
    assert _fk_ondelete(inspector, "listing_proposals", "product_id") == "CASCADE"
    assert _fk_ondelete(inspector, "listing_proposals", "base_version_id") == "SETNULL"
    assert _fk_ondelete(inspector, "listing_proposals", "approved_version_id") == "SETNULL"
    assert _fk_ondelete(inspector, "listing_proposals", "reviewed_by") == "SETNULL"

    with engine.connect() as connection:
        trigger_exists = connection.execute(
            text(
                """
                SELECT 1
                FROM pg_trigger
                WHERE tgname = 'trg_listing_versions_immutable'
                """
            )
        ).scalar_one_or_none()
        assert trigger_exists == 1
        function_exists = connection.execute(
            text(
                """
                SELECT 1
                FROM pg_proc
                WHERE proname = 'prevent_listing_version_mutation'
                """
            )
        ).scalar_one_or_none()
        assert function_exists == 1

    project_indexes = {idx["name"] for idx in inspector.get_indexes("projects")}
    product_indexes = {idx["name"] for idx in inspector.get_indexes("products")}
    generation_indexes = {idx["name"] for idx in inspector.get_indexes("generations")}
    assert "ix_projects_user_id_updated_at_created_at_id" in project_indexes
    project_index = next(
        idx
        for idx in inspector.get_indexes("projects")
        if idx["name"] == "ix_projects_user_id_updated_at_created_at_id"
    )
    assert project_index["column_names"] == ["user_id", "updated_at", "created_at", "id"]
    assert "ix_products_project_id_created_at_id" in product_indexes
    assert "ix_generations_product_id" in generation_indexes

    command.downgrade(cfg, "f9a0b1c2d3e4")
    inspector_auth_down = inspect(engine)
    assert "auth_sessions" not in set(inspector_auth_down.get_table_names())

    command.downgrade(cfg, "e8f9a0b1c2d3")
    inspector_catalog_down = inspect(engine)
    assert "amazon_catalog_snapshots" not in set(inspector_catalog_down.get_table_names())

    command.downgrade(cfg, "d7e8f9a0b1c2")
    inspector_seller_down = inspect(engine)
    seller_down_unique = {
        tuple(constraint["column_names"])
        for constraint in inspector_seller_down.get_unique_constraints("amazon_accounts")
    }
    assert ("selling_partner_id",) not in seller_down_unique
    seller_down_checks = {
        c["name"] for c in inspector_seller_down.get_check_constraints("amazon_accounts")
    }
    assert "ck_amazon_accounts_selling_partner_id_format" not in seller_down_checks
    seller_down_indexes = {
        idx["name"] for idx in inspector_seller_down.get_indexes("amazon_accounts")
    }
    assert "ix_amazon_accounts_selling_partner_id" in seller_down_indexes

    command.downgrade(cfg, "1194054de91f")
    inspector_oauth_down = inspect(engine)
    oauth_down_tables = set(inspector_oauth_down.get_table_names())
    assert "amazon_oauth_states" not in oauth_down_tables
    assert "amazon_listings" in oauth_down_tables

    command.downgrade(cfg, "c3d4e5f6a7b8")
    inspector_amazon_down = inspect(engine)
    amazon_down_tables = set(inspector_amazon_down.get_table_names())
    assert "amazon_accounts" not in amazon_down_tables
    assert "amazon_marketplace_participations" not in amazon_down_tables
    assert "amazon_sync_logs" not in amazon_down_tables
    assert "amazon_listings" not in amazon_down_tables

    command.downgrade(cfg, "b2c3d4e5f6a7")
    inspector_mid = inspect(engine)
    mid_tables = set(inspector_mid.get_table_names())
    assert "listing_versions" not in mid_tables
    assert "listing_proposals" not in mid_tables
    mid_product_columns = {column["name"] for column in inspector_mid.get_columns("products")}
    assert "current_listing_version_id" not in mid_product_columns
    with engine.connect() as connection:
        assert (
            connection.execute(
                text(
                    """
                    SELECT 1
                    FROM pg_trigger
                    WHERE tgname = 'trg_listing_versions_immutable'
                    """
                )
            ).scalar_one_or_none()
            is None
        )
        assert (
            connection.execute(
                text(
                    """
                    SELECT 1
                    FROM pg_proc
                    WHERE proname = 'prevent_listing_version_mutation'
                    """
                )
            ).scalar_one_or_none()
            is None
        )

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
        "listing_versions",
        "listing_proposals",
        "subscriptions",
        "amazon_accounts",
        "amazon_marketplace_participations",
        "amazon_sync_logs",
        "amazon_listings",
        "amazon_oauth_states",
        "amazon_catalog_snapshots",
        "auth_sessions",
    ]:
        model_columns = {column.name for column in Base.metadata.tables[table_name].columns}
        db_columns = {column["name"] for column in inspector_reup.get_columns(table_name)}
        missing = model_columns - db_columns
        assert not missing, f"{table_name} missing columns after re-upgrade: {missing}"

    engine.dispose()
