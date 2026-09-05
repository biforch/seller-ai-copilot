"""Pytest environment bootstrap — must set env vars before importing the app."""

from __future__ import annotations

import os

pytest_plugins = ("pytest_asyncio", "tests.fixtures.amazon_a32")

os.environ["ENVIRONMENT"] = "testing"
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://sellerai:sellerai123@localhost:5432/sellerai_test",
)
os.environ["JWT_SECRET_KEY"] = "pytest-jwt-secret-key-min-32-chars-long"
os.environ["OPENAI_API_KEY"] = "test-openai-key-not-used"
os.environ.setdefault(
    "MIGRATION_TEST_DATABASE_URL",
    "postgresql://sellerai:sellerai123@localhost:5432/sellerai_migration_test",
)
os.environ["CORS_ORIGINS"] = "http://localhost:3000"
os.environ["AUTH_TESTING_AUTO_VERIFY_MFA"] = "true"
os.environ["AMAZON_TOKEN_ACTIVE_KEY_VERSION"] = "1"
os.environ["AMAZON_TOKEN_KEY_V1"] = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY"
os.environ["AMAZON_TOKEN_FINGERPRINT_PEPPER"] = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY"
# Legacy generation remains covered by its regression suite while production
# defaults to frozen/off. Individual freeze tests instantiate default settings.
os.environ["LEGACY_GENERATION_ENABLED"] = "true"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.core.auth_session_constants import CSRF_COOKIE_NAME, CSRF_HEADER_NAME
from app.core.config import settings
from app.core.rate_limit import limiter
from app.core.security import get_password_hash
from app.database.session import Base, get_db
from app.db.listing_version_immutability import (
    LISTING_VERSION_IMMUTABILITY_FUNCTION,
    LISTING_VERSION_IMMUTABILITY_TRIGGER_SQL,
)
from app.main import app
from app.models.product import Product
from app.models.project import Project
from app.models.user import User

TEST_ORIGIN = "http://localhost:3000"
LOGIN_URL = "/api/v1/auth/login"


def _assert_test_database(url: str) -> None:
    db_name = url.rsplit("/", 1)[-1]
    if "_test" not in db_name and not db_name.endswith("test"):
        raise RuntimeError(f"Refusing to run tests against non-test database: {db_name}")


_assert_test_database(settings.DATABASE_URL)


@pytest.fixture(autouse=True)
def reset_rate_limit_storage():
    limiter.reset()
    yield
    limiter.reset()


def _reset_test_schema(engine) -> None:
    with engine.begin() as connection:
        table_names = connection.execute(
            text(
                """
                SELECT tablename
                FROM pg_tables
                WHERE schemaname = 'public'
                  AND tablename != 'alembic_version'
                """
            )
        ).scalars()
        for table_name in table_names:
            connection.execute(text(f'DROP TABLE IF EXISTS "{table_name}" CASCADE'))
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(text(LISTING_VERSION_IMMUTABILITY_FUNCTION))
        connection.execute(text(LISTING_VERSION_IMMUTABILITY_TRIGGER_SQL))
        connection.execute(
            text(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS uq_listing_proposals_generation_request_id
                ON listing_proposals (generation_request_id)
                WHERE generation_request_id IS NOT NULL
                """
            )
        )


@pytest.fixture(scope="session")
def engine():
    eng = create_engine(settings.DATABASE_URL, pool_pre_ping=True)
    try:
        with eng.connect() as connection:
            connection.execute(text("SELECT 1"))
    except OperationalError as exc:
        pytest.skip(f"PostgreSQL test database unavailable: {exc}")

    _reset_test_schema(eng)
    yield eng
    _reset_test_schema(eng)


@pytest.fixture
def db_session(engine) -> Session:
    connection = engine.connect()
    transaction = connection.begin()
    session = sessionmaker(bind=connection, autocommit=False, autoflush=False)()
    try:
        yield session
    finally:
        session.close()
        if transaction.is_active:
            transaction.rollback()
        connection.close()


@pytest.fixture
def client(db_session: Session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def user_factory(db_session: Session):
    def _create_user(email: str, password: str = "Password1") -> User:
        user = User(
            email=email,
            password_hash=get_password_hash(password),
            plan="free",
            monthly_tokens=100_000,
            used_tokens=0,
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)
        return user

    return _create_user


@pytest.fixture
def auth_header(client):
    active_email: dict[str, str | None] = {"value": None}

    def _header(user: User, *, password: str = "Password1") -> dict[str, str]:
        if active_email["value"] != user.email:
            response = client.post(
                LOGIN_URL,
                json={"email": user.email, "password": password},
                headers={"Origin": TEST_ORIGIN},
            )
            assert response.status_code == 200, response.text
            active_email["value"] = user.email
        csrf = client.cookies.get(CSRF_COOKIE_NAME)
        headers = {"Origin": TEST_ORIGIN}
        if csrf:
            headers[CSRF_HEADER_NAME] = csrf
        return headers

    return _header


@pytest.fixture
def tenant_bundle(user_factory, db_session: Session):
    def _bundle(prefix: str) -> dict[str, object]:
        user = user_factory(f"{prefix}@example.com")
        project = Project(
            user_id=user.id,
            name=f"{prefix} project",
            platform="Amazon",
            market="USA",
        )
        db_session.add(project)
        db_session.commit()
        db_session.refresh(project)

        product = Product(
            user_id=user.id,
            project_id=project.id,
            name=f"{prefix} product",
            category="Electronics",
            platform="Amazon",
            market="USA",
        )
        db_session.add(product)
        db_session.commit()
        db_session.refresh(product)
        return {"user": user, "project": project, "product": product}

    return _bundle


@pytest.fixture
def valid_listing_payload():
    def _payload(project_id, **overrides):
        body = {
            "project_id": str(project_id),
            "name": "Wireless Earbuds",
            "category": "Electronics",
            "market": "USA",
            "platform": "Amazon",
        }
        body.update(overrides)
        return body

    return _payload


@pytest.fixture
def isolated_client_ip():
    """Documented hook for tests that need a dedicated rate-limit bucket."""

    def _headers(ip: str) -> dict[str, str]:
        return {"X-Test-Client-IP": ip}

    return _headers


@pytest.fixture
def idempotency_header():
    import uuid

    def _header(key: str | None = None) -> dict[str, str]:
        return {"Idempotency-Key": key or str(uuid.uuid4())}

    return _header


@pytest.fixture
def auth_and_idempotency(auth_header, idempotency_header):
    def _headers(user, idempotency_key: str | None = None, **extra: str) -> dict[str, str]:
        return {
            **auth_header(user),
            **idempotency_header(idempotency_key),
            **extra,
        }

    return _headers


@pytest.fixture
def valid_listing_ai_result():
    from tests.fixtures.ai_outputs import VALID_LISTING_OUTPUT

    return {**VALID_LISTING_OUTPUT, "tokens_used": 321}
