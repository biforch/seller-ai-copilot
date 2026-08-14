"""Migration-backed delete behavior tests for listing schema."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from alembic import command
from alembic.config import Config
from app.core.migration_guard import validate_before_destructive_migration
from app.core.security import get_password_hash
from app.models.generation import Generation
from app.models.listing_proposal import ListingProposal
from app.models.listing_version import ListingVersion
from app.models.product import Product
from app.models.project import Project
from app.models.user import User
from tests.test_alembic_migration import _fk_ondelete, _reset_migration_database
from tests.test_listing_versions import sample_listing_snapshot


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
    _reset_migration_database(url)
    yield url
    _reset_migration_database(url)


def test_migration_schema_delete_behaviors(migration_database_url, monkeypatch):
    backend_root = Path(__file__).resolve().parents[1]
    cfg = Config(str(backend_root / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", migration_database_url)
    monkeypatch.setenv("ALEMBIC_DATABASE_URL", migration_database_url)
    command.upgrade(cfg, "head")

    engine = create_engine(migration_database_url, pool_pre_ping=True)
    inspector = inspect(engine)
    assert _fk_ondelete(inspector, "listing_versions", "generation_id") == "SETNULL"
    assert _fk_ondelete(inspector, "listing_versions", "created_by") == "SETNULL"
    assert _fk_ondelete(inspector, "listing_versions", "parent_version_id") == "RESTRICT"
    assert _fk_ondelete(inspector, "listing_proposals", "reviewed_by") == "SETNULL"

    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    db = session_factory()
    try:
        user = User(
            email="migration-delete@example.com",
            password_hash=get_password_hash("Password1"),
            plan="free",
            monthly_tokens=100_000,
            used_tokens=0,
        )
        db.add(user)
        db.flush()
        project = Project(user_id=user.id, name="Delete Project", platform="Amazon", market="USA")
        db.add(project)
        db.flush()
        product = Product(
            user_id=user.id,
            project_id=project.id,
            name="Delete Product",
            category="Electronics",
            platform="Amazon",
            market="USA",
        )
        db.add(product)
        db.flush()
        generation = Generation(
            user_id=user.id,
            product_id=product.id,
            project_id=project.id,
            type="listing",
            input={"name": "x"},
            output={"title": "x"},
            tokens_used=1,
        )
        db.add(generation)
        db.flush()
        snapshot = sample_listing_snapshot()
        version = ListingVersion(
            product_id=product.id,
            version_number=1,
            source="manual",
            title=snapshot.title,
            bullets=snapshot.bullets,
            description=snapshot.description,
            backend_keywords=snapshot.backend_keywords,
            marketplace="Amazon",
            language="en-US",
            created_by=user.id,
            generation_id=generation.id,
        )
        db.add(version)
        db.flush()
        product.current_listing_version_id = version.id
        proposal = ListingProposal(
            product_id=product.id,
            base_version_id=version.id,
            candidate_snapshot=snapshot.canonical_dict(),
            field_decisions={
                "title": "pending",
                "bullets": "pending",
                "description": "pending",
                "backend_keywords": "pending",
            },
            status="reviewing",
            revision=1,
        )
        db.add(proposal)
        db.commit()

        version_id = version.id
        proposal_id = proposal.id

        db.delete(generation)
        db.commit()
        db.refresh(version)
        assert version.generation_id is None

        reviewer = User(
            email="migration-reviewer@example.com",
            password_hash=get_password_hash("Password1"),
            plan="free",
            monthly_tokens=100_000,
            used_tokens=0,
        )
        db.add(reviewer)
        db.flush()
        proposal.reviewed_by = reviewer.id
        db.commit()

        db.delete(reviewer)
        db.commit()
        db.refresh(proposal)
        assert proposal.reviewed_by is None

        db.delete(product)
        db.commit()
        assert db.query(ListingVersion).filter(ListingVersion.id == version_id).count() == 0
        assert db.query(ListingProposal).filter(ListingProposal.id == proposal_id).count() == 0
    finally:
        db.close()
        engine.dispose()


def test_migration_delete_creator_user_sets_created_by_null(migration_database_url, monkeypatch):
    backend_root = Path(__file__).resolve().parents[1]
    cfg = Config(str(backend_root / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", migration_database_url)
    monkeypatch.setenv("ALEMBIC_DATABASE_URL", migration_database_url)
    command.upgrade(cfg, "head")

    engine = create_engine(migration_database_url, pool_pre_ping=True)
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    db = session_factory()
    try:
        owner = User(
            email="migration-owner@example.com",
            password_hash=get_password_hash("Password1"),
            plan="free",
            monthly_tokens=100_000,
            used_tokens=0,
        )
        creator = User(
            email="migration-creator@example.com",
            password_hash=get_password_hash("Password1"),
            plan="free",
            monthly_tokens=100_000,
            used_tokens=0,
        )
        db.add_all([owner, creator])
        db.flush()
        project = Project(user_id=owner.id, name="Owner Project", platform="Amazon", market="USA")
        db.add(project)
        db.flush()
        product = Product(
            user_id=owner.id,
            project_id=project.id,
            name="Owner Product",
            category="Electronics",
            platform="Amazon",
            market="USA",
        )
        db.add(product)
        db.flush()
        snapshot = sample_listing_snapshot()
        version = ListingVersion(
            product_id=product.id,
            version_number=1,
            source="manual",
            title=snapshot.title,
            bullets=snapshot.bullets,
            description=snapshot.description,
            backend_keywords=snapshot.backend_keywords,
            marketplace="Amazon",
            language="en-US",
            created_by=creator.id,
        )
        db.add(version)
        db.flush()
        product.current_listing_version_id = version.id
        db.commit()

        version_id = version.id
        product_id = product.id

        db.delete(creator)
        db.commit()
        db.refresh(version)
        assert db.query(Product).filter(Product.id == product_id).count() == 1
        assert db.query(ListingVersion).filter(ListingVersion.id == version_id).count() == 1
        assert version.created_by is None
    finally:
        db.close()
        engine.dispose()
