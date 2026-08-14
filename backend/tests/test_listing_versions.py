"""Listing version system integration and concurrency tests."""

from __future__ import annotations

import threading
import uuid

import pytest
from fastapi import status
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError, OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.core.exceptions import (
    IDEMPOTENCY_CONFLICT,
    LISTING_DECISIONS_INCOMPLETE,
    LISTING_NO_BASE_PARTIAL_ACCEPT_FORBIDDEN,
    LISTING_PROPOSAL_NOT_REVIEWING,
    LISTING_PROPOSAL_REVISION_CONFLICT,
    LISTING_PROPOSAL_STALE,
    AppException,
)
from app.models.generation import Generation
from app.models.generation_request import GenerationRequest, GenerationRequestStatus
from app.models.listing_proposal import ListingProposal, ListingProposalStatus
from app.models.listing_version import ListingVersion, ListingVersionSource
from app.models.product import Product
from app.models.user import User
from app.schemas.listing import FieldDecisions, ListingSnapshot, default_pending_field_decisions
from app.services.idempotency import canonical_request_hash
from app.services.listing_diff import build_listing_diff, compute_final_snapshot
from app.services.listing_proposal import (
    approve_listing_proposal,
    create_proposal_from_generation,
    create_proposal_in_transaction,
    patch_proposal_decisions,
    reject_listing_proposal,
)
from app.services.listing_version import import_listing_version, set_product_current_listing_version
from tests.fixtures.ai_outputs import VALID_LISTING_OUTPUT


def sample_listing_snapshot(**overrides) -> ListingSnapshot:
    base = {
        "title": "Premium Wireless Earbuds with Active Noise Cancellation",
        "bullets": VALID_LISTING_OUTPUT["bullets"],
        "description": VALID_LISTING_OUTPUT["description"],
        "backend_keywords": VALID_LISTING_OUTPUT["keywords"][:10],
    }
    base.update(overrides)
    return ListingSnapshot.model_validate(base)


def accept_all_decisions() -> FieldDecisions:
    return FieldDecisions(
        title="accept",
        bullets="accept",
        description="accept",
        backend_keywords="accept",
    )


def reject_all_decisions() -> FieldDecisions:
    return FieldDecisions(
        title="reject",
        bullets="reject",
        description="reject",
        backend_keywords="reject",
    )


def create_generation_request(
    db: Session,
    *,
    user_id: uuid.UUID,
    product_id: uuid.UUID,
    project_id: uuid.UUID,
    with_generation: bool = True,
) -> GenerationRequest:
    generation_id = None
    if with_generation:
        generation = Generation(
            user_id=user_id,
            product_id=product_id,
            project_id=project_id,
            type="listing",
            input={"name": "test"},
            output=VALID_LISTING_OUTPUT,
            tokens_used=10,
        )
        db.add(generation)
        db.flush()
        generation_id = generation.id

    request = GenerationRequest(
        user_id=user_id,
        request_type="listing",
        idempotency_key=str(uuid.uuid4()),
        request_hash=canonical_request_hash({"name": "test"}),
        status=GenerationRequestStatus.SUCCEEDED,
        project_id=project_id,
        product_id=product_id,
        input={"name": "test"},
        generation_id=generation_id,
        tokens_used=10,
    )
    db.add(request)
    db.commit()
    db.refresh(request)
    return request


def test_listing_snapshot_validation_rules():
    with pytest.raises(ValueError):
        sample_listing_snapshot(bullets=["one", "two", "three"])

    with pytest.raises(ValueError):
        sample_listing_snapshot(backend_keywords=[])

    snapshot = sample_listing_snapshot(
        backend_keywords=[" Alpha ", "alpha", "Beta", "  "],
    )
    assert snapshot.backend_keywords == ["Alpha", "Beta"]


def test_default_pending_field_decisions_are_independent():
    first = default_pending_field_decisions()
    second = default_pending_field_decisions()
    first.title = "accept"
    assert second.title == "pending"


def test_build_listing_diff_without_base():
    candidate = sample_listing_snapshot()
    diff = build_listing_diff(None, candidate)
    assert diff["title"]["base"] is None
    assert diff["title"]["changed"] is True


def test_compute_final_snapshot_with_base_partial_accept():
    base = sample_listing_snapshot(title="Base Title")
    candidate = sample_listing_snapshot(title="Candidate Title")
    decisions = FieldDecisions(
        title="accept",
        bullets="reject",
        description="reject",
        backend_keywords="reject",
    )
    final = compute_final_snapshot(base, candidate, decisions)
    assert final.title == candidate.title
    assert final.bullets == base.bullets


def test_compute_final_snapshot_without_base_requires_all_accept():
    candidate = sample_listing_snapshot()
    decisions = FieldDecisions(
        title="accept",
        bullets="accept",
        description="accept",
        backend_keywords="reject",
    )
    with pytest.raises(AppException) as exc:
        compute_final_snapshot(None, candidate, decisions)
    assert exc.value.error_code == LISTING_NO_BASE_PARTIAL_ACCEPT_FORBIDDEN


def test_compute_final_snapshot_pending_raises():
    base = sample_listing_snapshot()
    candidate = sample_listing_snapshot(title="New")
    decisions = default_pending_field_decisions()
    with pytest.raises(AppException) as exc:
        compute_final_snapshot(base, candidate, decisions)
    assert exc.value.error_code == LISTING_DECISIONS_INCOMPLETE


def test_import_replay_same_key_same_payload(db_session, tenant_bundle):
    tenant = tenant_bundle("listing-import-replay")
    snapshot = sample_listing_snapshot()
    key = str(uuid.uuid4())

    first = import_listing_version(
        db_session,
        product_id=tenant["product"].id,
        current_user_id=tenant["user"].id,
        snapshot=snapshot,
        idempotency_key=key,
        marketplace="Amazon",
    )
    second = import_listing_version(
        db_session,
        product_id=tenant["product"].id,
        current_user_id=tenant["user"].id,
        snapshot=snapshot,
        idempotency_key=key,
        marketplace="Amazon",
    )
    assert first.replay is False
    assert second.replay is True
    assert first.version.id == second.version.id


def test_import_same_key_different_payload_conflict(db_session, tenant_bundle):
    tenant = tenant_bundle("listing-import-conflict")
    key = str(uuid.uuid4())
    import_listing_version(
        db_session,
        product_id=tenant["product"].id,
        current_user_id=tenant["user"].id,
        snapshot=sample_listing_snapshot(title="First Title"),
        idempotency_key=key,
        marketplace="Amazon",
    )
    with pytest.raises(AppException) as exc:
        import_listing_version(
            db_session,
            product_id=tenant["product"].id,
            current_user_id=tenant["user"].id,
            snapshot=sample_listing_snapshot(title="Second Title"),
            idempotency_key=key,
            marketplace="Amazon",
        )
    assert exc.value.error_code == IDEMPOTENCY_CONFLICT


def test_import_first_version_has_null_parent(db_session, tenant_bundle):
    tenant = tenant_bundle("listing-import-parent")
    result = import_listing_version(
        db_session,
        product_id=tenant["product"].id,
        current_user_id=tenant["user"].id,
        snapshot=sample_listing_snapshot(),
        idempotency_key=str(uuid.uuid4()),
        marketplace="Amazon",
    )
    assert result.version.parent_version_id is None
    db_session.refresh(tenant["product"])
    assert tenant["product"].current_listing_version_id == result.version.id


def test_listing_snapshot_rejects_four_bullets():
    with pytest.raises(ValidationError):
        sample_listing_snapshot(
            bullets=VALID_LISTING_OUTPUT["bullets"][:4],
        )


def test_product_current_cannot_point_to_other_product_version(db_session, tenant_bundle):
    tenant_a = tenant_bundle("listing-current-a")
    tenant_b = tenant_bundle("listing-current-b")

    version_a = import_listing_version(
        db_session,
        product_id=tenant_a["product"].id,
        current_user_id=tenant_a["user"].id,
        snapshot=sample_listing_snapshot(),
        idempotency_key=str(uuid.uuid4()),
        marketplace="Amazon",
    ).version

    with pytest.raises(AppException):
        set_product_current_listing_version(tenant_b["product"], version_a)


def test_version_orm_update_blocked_by_trigger(db_session, tenant_bundle):
    tenant = tenant_bundle("listing-trigger-orm")
    version = import_listing_version(
        db_session,
        product_id=tenant["product"].id,
        current_user_id=tenant["user"].id,
        snapshot=sample_listing_snapshot(),
        idempotency_key=str(uuid.uuid4()),
        marketplace="Amazon",
    ).version

    version.title = "Mutated Title"
    with pytest.raises((OperationalError, DBAPIError)):
        db_session.commit()


def test_version_sql_update_blocked_by_trigger(db_session, tenant_bundle):
    tenant = tenant_bundle("listing-trigger-sql")
    version = import_listing_version(
        db_session,
        product_id=tenant["product"].id,
        current_user_id=tenant["user"].id,
        snapshot=sample_listing_snapshot(),
        idempotency_key=str(uuid.uuid4()),
        marketplace="Amazon",
    ).version

    with pytest.raises((OperationalError, DBAPIError)):
        db_session.execute(
            text("UPDATE listing_versions SET description = :desc WHERE id = :id"),
            {"desc": "Changed", "id": str(version.id)},
        )
        db_session.commit()


def test_generation_delete_allows_generation_id_set_null(db_session, tenant_bundle):
    tenant = tenant_bundle("listing-gen-null")
    generation_request = create_generation_request(
        db_session,
        user_id=tenant["user"].id,
        product_id=tenant["product"].id,
        project_id=tenant["project"].id,
    )
    proposal = create_proposal_from_generation(
        db_session,
        product_id=tenant["product"].id,
        current_user_id=tenant["user"].id,
        generation_request_id=generation_request.id,
        candidate=sample_listing_snapshot(title="AI Version"),
    )
    approved = approve_listing_proposal(
        db_session,
        product_id=tenant["product"].id,
        current_user_id=tenant["user"].id,
        proposal_id=proposal.id,
        expected_revision=proposal.revision,
        decisions=accept_all_decisions(),
    )
    assert approved.version.generation_id is not None

    db_session.delete(
        db_session.query(Generation).filter(Generation.id == generation_request.generation_id).one()
    )
    db_session.commit()
    db_session.refresh(approved.version)
    assert approved.version.generation_id is None


def test_create_proposal_defaults_all_pending(db_session, tenant_bundle):
    tenant = tenant_bundle("listing-proposal-pending")
    generation_request = create_generation_request(
        db_session,
        user_id=tenant["user"].id,
        product_id=tenant["product"].id,
        project_id=tenant["project"].id,
    )
    proposal = create_proposal_from_generation(
        db_session,
        product_id=tenant["product"].id,
        current_user_id=tenant["user"].id,
        generation_request_id=generation_request.id,
        candidate=sample_listing_snapshot(),
    )
    assert proposal.field_decisions == default_pending_field_decisions().to_json()
    assert proposal.status == ListingProposalStatus.REVIEWING


def test_create_proposal_is_idempotent_per_generation_request(db_session, tenant_bundle):
    tenant = tenant_bundle("listing-proposal-idem")
    generation_request = create_generation_request(
        db_session,
        user_id=tenant["user"].id,
        product_id=tenant["product"].id,
        project_id=tenant["project"].id,
    )
    first = create_proposal_from_generation(
        db_session,
        product_id=tenant["product"].id,
        current_user_id=tenant["user"].id,
        generation_request_id=generation_request.id,
        candidate=sample_listing_snapshot(),
    )
    second = create_proposal_from_generation(
        db_session,
        product_id=tenant["product"].id,
        current_user_id=tenant["user"].id,
        generation_request_id=generation_request.id,
        candidate=sample_listing_snapshot(title="Different"),
    )
    assert first.id == second.id


def test_patch_proposal_decisions_revision_conflict(db_session, tenant_bundle):
    tenant = tenant_bundle("listing-patch-revision")
    generation_request = create_generation_request(
        db_session,
        user_id=tenant["user"].id,
        product_id=tenant["product"].id,
        project_id=tenant["project"].id,
    )
    proposal = create_proposal_from_generation(
        db_session,
        product_id=tenant["product"].id,
        current_user_id=tenant["user"].id,
        generation_request_id=generation_request.id,
        candidate=sample_listing_snapshot(),
    )
    updated = patch_proposal_decisions(
        db_session,
        product_id=tenant["product"].id,
        current_user_id=tenant["user"].id,
        proposal_id=proposal.id,
        decisions=accept_all_decisions(),
        expected_revision=1,
    )
    assert updated.revision == 2

    with pytest.raises(AppException) as exc:
        patch_proposal_decisions(
            db_session,
            product_id=tenant["product"].id,
            current_user_id=tenant["user"].id,
            proposal_id=proposal.id,
            decisions=accept_all_decisions(),
            expected_revision=1,
        )
    assert exc.value.error_code == LISTING_PROPOSAL_REVISION_CONFLICT


def test_approve_without_base_requires_all_accept(db_session, tenant_bundle):
    tenant = tenant_bundle("listing-approve-no-base")
    generation_request = create_generation_request(
        db_session,
        user_id=tenant["user"].id,
        product_id=tenant["product"].id,
        project_id=tenant["project"].id,
    )
    proposal = create_proposal_from_generation(
        db_session,
        product_id=tenant["product"].id,
        current_user_id=tenant["user"].id,
        generation_request_id=generation_request.id,
        candidate=sample_listing_snapshot(title="Candidate Only"),
    )
    partial = FieldDecisions(
        title="accept",
        bullets="accept",
        description="accept",
        backend_keywords="reject",
    )
    with pytest.raises(AppException) as exc:
        approve_listing_proposal(
            db_session,
            product_id=tenant["product"].id,
            current_user_id=tenant["user"].id,
            proposal_id=proposal.id,
            expected_revision=proposal.revision,
            decisions=partial,
        )
    assert exc.value.error_code == LISTING_NO_BASE_PARTIAL_ACCEPT_FORBIDDEN


def test_approve_without_base_all_accept_creates_v1(db_session, tenant_bundle):
    tenant = tenant_bundle("listing-approve-v1")
    generation_request = create_generation_request(
        db_session,
        user_id=tenant["user"].id,
        product_id=tenant["product"].id,
        project_id=tenant["project"].id,
    )
    proposal = create_proposal_from_generation(
        db_session,
        product_id=tenant["product"].id,
        current_user_id=tenant["user"].id,
        generation_request_id=generation_request.id,
        candidate=sample_listing_snapshot(title="Version One"),
    )
    result = approve_listing_proposal(
        db_session,
        product_id=tenant["product"].id,
        current_user_id=tenant["user"].id,
        proposal_id=proposal.id,
        expected_revision=proposal.revision,
        decisions=accept_all_decisions(),
    )
    assert result.version.version_number == 1
    assert result.version.source == ListingVersionSource.AI
    db_session.refresh(tenant["product"])
    assert tenant["product"].current_listing_version_id == result.version.id


def test_pending_blocks_approve(db_session, tenant_bundle):
    tenant = tenant_bundle("listing-approve-pending")
    generation_request = create_generation_request(
        db_session,
        user_id=tenant["user"].id,
        product_id=tenant["product"].id,
        project_id=tenant["project"].id,
    )
    proposal = create_proposal_from_generation(
        db_session,
        product_id=tenant["product"].id,
        current_user_id=tenant["user"].id,
        generation_request_id=generation_request.id,
        candidate=sample_listing_snapshot(),
    )
    with pytest.raises(AppException) as exc:
        approve_listing_proposal(
            db_session,
            product_id=tenant["product"].id,
            current_user_id=tenant["user"].id,
            proposal_id=proposal.id,
            expected_revision=proposal.revision,
        )
    assert exc.value.error_code == LISTING_DECISIONS_INCOMPLETE


def test_all_reject_does_not_create_version_via_approve(db_session, tenant_bundle):
    tenant = tenant_bundle("listing-approve-all-reject")
    generation_request = create_generation_request(
        db_session,
        user_id=tenant["user"].id,
        product_id=tenant["product"].id,
        project_id=tenant["project"].id,
    )
    proposal = create_proposal_from_generation(
        db_session,
        product_id=tenant["product"].id,
        current_user_id=tenant["user"].id,
        generation_request_id=generation_request.id,
        candidate=sample_listing_snapshot(),
    )
    with pytest.raises(AppException) as exc:
        approve_listing_proposal(
            db_session,
            product_id=tenant["product"].id,
            current_user_id=tenant["user"].id,
            proposal_id=proposal.id,
            expected_revision=proposal.revision,
            decisions=reject_all_decisions(),
        )
    assert exc.value.error_code == LISTING_PROPOSAL_NOT_REVIEWING
    assert (
        db_session.query(ListingVersion)
        .filter(ListingVersion.product_id == tenant["product"].id)
        .count()
        == 0
    )


def test_reject_does_not_create_version(db_session, tenant_bundle):
    tenant = tenant_bundle("listing-reject")
    generation_request = create_generation_request(
        db_session,
        user_id=tenant["user"].id,
        product_id=tenant["product"].id,
        project_id=tenant["project"].id,
    )
    proposal = create_proposal_from_generation(
        db_session,
        product_id=tenant["product"].id,
        current_user_id=tenant["user"].id,
        generation_request_id=generation_request.id,
        candidate=sample_listing_snapshot(),
    )
    rejected = reject_listing_proposal(
        db_session,
        product_id=tenant["product"].id,
        current_user_id=tenant["user"].id,
        proposal_id=proposal.id,
        expected_revision=proposal.revision,
    )
    assert rejected.proposal.status == ListingProposalStatus.REJECTED
    assert (
        db_session.query(ListingVersion)
        .filter(ListingVersion.product_id == tenant["product"].id)
        .count()
        == 0
    )


def test_reject_is_idempotent(db_session, tenant_bundle):
    tenant = tenant_bundle("listing-reject-idem")
    generation_request = create_generation_request(
        db_session,
        user_id=tenant["user"].id,
        product_id=tenant["product"].id,
        project_id=tenant["project"].id,
    )
    proposal = create_proposal_from_generation(
        db_session,
        product_id=tenant["product"].id,
        current_user_id=tenant["user"].id,
        generation_request_id=generation_request.id,
        candidate=sample_listing_snapshot(),
    )
    first = reject_listing_proposal(
        db_session,
        product_id=tenant["product"].id,
        current_user_id=tenant["user"].id,
        proposal_id=proposal.id,
        expected_revision=proposal.revision,
    )
    second = reject_listing_proposal(
        db_session,
        product_id=tenant["product"].id,
        current_user_id=tenant["user"].id,
        proposal_id=proposal.id,
        expected_revision=first.proposal.revision,
    )
    assert second.proposal.status == ListingProposalStatus.REJECTED
    assert second.replay is True


def test_duplicate_approve_does_not_create_second_version(db_session, tenant_bundle):
    tenant = tenant_bundle("listing-approve-idem")
    generation_request = create_generation_request(
        db_session,
        user_id=tenant["user"].id,
        product_id=tenant["product"].id,
        project_id=tenant["project"].id,
    )
    proposal = create_proposal_from_generation(
        db_session,
        product_id=tenant["product"].id,
        current_user_id=tenant["user"].id,
        generation_request_id=generation_request.id,
        candidate=sample_listing_snapshot(),
    )
    first = approve_listing_proposal(
        db_session,
        product_id=tenant["product"].id,
        current_user_id=tenant["user"].id,
        proposal_id=proposal.id,
        expected_revision=proposal.revision,
        decisions=accept_all_decisions(),
    )
    second = approve_listing_proposal(
        db_session,
        product_id=tenant["product"].id,
        current_user_id=tenant["user"].id,
        proposal_id=first.proposal.id,
        expected_revision=first.proposal.revision,
        decisions=accept_all_decisions(),
    )
    assert second.replay is True
    assert (
        db_session.query(ListingVersion)
        .filter(ListingVersion.product_id == tenant["product"].id)
        .count()
        == 1
    )


def test_stale_base_blocks_approve(db_session, tenant_bundle):
    tenant = tenant_bundle("listing-stale-base")
    import_listing_version(
        db_session,
        product_id=tenant["product"].id,
        current_user_id=tenant["user"].id,
        snapshot=sample_listing_snapshot(title="Imported Base"),
        idempotency_key=str(uuid.uuid4()),
        marketplace="Amazon",
    )
    generation_request = create_generation_request(
        db_session,
        user_id=tenant["user"].id,
        product_id=tenant["product"].id,
        project_id=tenant["project"].id,
    )
    proposal = create_proposal_from_generation(
        db_session,
        product_id=tenant["product"].id,
        current_user_id=tenant["user"].id,
        generation_request_id=generation_request.id,
        candidate=sample_listing_snapshot(title="Stale Candidate"),
    )
    import_listing_version(
        db_session,
        product_id=tenant["product"].id,
        current_user_id=tenant["user"].id,
        snapshot=sample_listing_snapshot(title="Newer Current"),
        idempotency_key=str(uuid.uuid4()),
        marketplace="Amazon",
    )
    with pytest.raises(AppException) as exc:
        approve_listing_proposal(
            db_session,
            product_id=tenant["product"].id,
            current_user_id=tenant["user"].id,
            proposal_id=proposal.id,
            expected_revision=proposal.revision,
            decisions=accept_all_decisions(),
        )
    assert exc.value.error_code == LISTING_PROPOSAL_STALE


def test_approve_supersedes_other_reviewing_proposals(db_session, tenant_bundle):
    tenant = tenant_bundle("listing-supersede")
    first_request = create_generation_request(
        db_session,
        user_id=tenant["user"].id,
        product_id=tenant["product"].id,
        project_id=tenant["project"].id,
    )
    second_request = create_generation_request(
        db_session,
        user_id=tenant["user"].id,
        product_id=tenant["product"].id,
        project_id=tenant["project"].id,
    )
    first_proposal = create_proposal_from_generation(
        db_session,
        product_id=tenant["product"].id,
        current_user_id=tenant["user"].id,
        generation_request_id=first_request.id,
        candidate=sample_listing_snapshot(title="First"),
    )
    second_proposal = create_proposal_from_generation(
        db_session,
        product_id=tenant["product"].id,
        current_user_id=tenant["user"].id,
        generation_request_id=second_request.id,
        candidate=sample_listing_snapshot(title="Second"),
    )
    approve_listing_proposal(
        db_session,
        product_id=tenant["product"].id,
        current_user_id=tenant["user"].id,
        proposal_id=second_proposal.id,
        expected_revision=second_proposal.revision,
        decisions=accept_all_decisions(),
    )
    db_session.refresh(first_proposal)
    assert first_proposal.status == ListingProposalStatus.SUPERSEDED


def test_tenant_isolation_returns_404(db_session, tenant_bundle):
    owner = tenant_bundle("listing-owner")
    intruder = tenant_bundle("listing-intruder")
    generation_request = create_generation_request(
        db_session,
        user_id=owner["user"].id,
        product_id=owner["product"].id,
        project_id=owner["project"].id,
    )
    proposal = create_proposal_from_generation(
        db_session,
        product_id=owner["product"].id,
        current_user_id=owner["user"].id,
        generation_request_id=generation_request.id,
        candidate=sample_listing_snapshot(),
    )
    with pytest.raises(AppException) as exc:
        approve_listing_proposal(
            db_session,
            product_id=owner["product"].id,
            current_user_id=intruder["user"].id,
            proposal_id=proposal.id,
            expected_revision=proposal.revision,
            decisions=accept_all_decisions(),
        )
    assert exc.value.code == status.HTTP_404_NOT_FOUND


def test_product_delete_cascades_versions_and_proposals(db_session, tenant_bundle):
    tenant = tenant_bundle("listing-delete-product")
    imported = import_listing_version(
        db_session,
        product_id=tenant["product"].id,
        current_user_id=tenant["user"].id,
        snapshot=sample_listing_snapshot(),
        idempotency_key=str(uuid.uuid4()),
        marketplace="Amazon",
    )
    generation_request = create_generation_request(
        db_session,
        user_id=tenant["user"].id,
        product_id=tenant["product"].id,
        project_id=tenant["project"].id,
    )
    proposal = create_proposal_from_generation(
        db_session,
        product_id=tenant["product"].id,
        current_user_id=tenant["user"].id,
        generation_request_id=generation_request.id,
        candidate=sample_listing_snapshot(title="To Approve"),
    )
    approved = approve_listing_proposal(
        db_session,
        product_id=tenant["product"].id,
        current_user_id=tenant["user"].id,
        proposal_id=proposal.id,
        expected_revision=proposal.revision,
        decisions=accept_all_decisions(),
    )
    version_ids = {imported.version.id, approved.version.id}
    proposal_ids = {proposal.id, approved.proposal.id}

    db_session.delete(tenant["product"])
    db_session.commit()

    assert db_session.query(ListingVersion).filter(ListingVersion.id.in_(version_ids)).count() == 0
    assert db_session.query(ListingProposal).filter(ListingProposal.id.in_(proposal_ids)).count() == 0


def test_user_delete_succeeds_with_listing_versions(db_session, tenant_bundle):
    tenant = tenant_bundle("listing-delete-user")
    import_listing_version(
        db_session,
        product_id=tenant["product"].id,
        current_user_id=tenant["user"].id,
        snapshot=sample_listing_snapshot(),
        idempotency_key=str(uuid.uuid4()),
        marketplace="Amazon",
    )

    db_session.delete(tenant["user"])
    db_session.commit()


def test_metadata_create_all_exposes_current_version_fk(engine):
    from sqlalchemy import inspect

    inspector = inspect(engine)
    product_fks = inspector.get_foreign_keys("products")
    current_fk = next(
        (
            fk
            for fk in product_fks
            if fk.get("constrained_columns") == ["current_listing_version_id"]
        ),
        None,
    )
    assert current_fk is not None
    assert current_fk["name"] == "fk_products_current_listing_version_id_listing_versions"
    assert current_fk.get("options", {}).get("ondelete") == "SET NULL"


def _create_tenant(session: Session, prefix: str) -> dict[str, object]:
    from app.core.security import get_password_hash
    from app.models.project import Project

    user = User(
        email=f"{prefix}@example.com",
        password_hash=get_password_hash("Password1"),
        plan="free",
        monthly_tokens=100_000,
        used_tokens=0,
    )
    session.add(user)
    session.flush()
    project = Project(
        user_id=user.id,
        name=f"{prefix} project",
        platform="Amazon",
        market="USA",
    )
    session.add(project)
    session.flush()
    product = Product(
        user_id=user.id,
        project_id=project.id,
        name=f"{prefix} product",
        category="Electronics",
        platform="Amazon",
        market="USA",
    )
    session.add(product)
    session.commit()
    session.refresh(user)
    session.refresh(project)
    session.refresh(product)
    return {"user": user, "project": project, "product": product}


def test_concurrent_import_version_numbers(engine):
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    setup = session_factory()
    try:
        tenant = _create_tenant(setup, "listing-concurrent-version")
        product_id = tenant["product"].id
        user_id = tenant["user"].id
    finally:
        setup.close()

    barrier = threading.Barrier(2)
    thread_errors: list[BaseException] = []
    version_numbers: list[int] = []

    def worker(key_suffix: str):
        db = session_factory()
        try:
            barrier.wait(timeout=5)
            result = import_listing_version(
                db,
                product_id=product_id,
                current_user_id=user_id,
                snapshot=sample_listing_snapshot(title=f"Title {key_suffix}"),
                idempotency_key=str(uuid.uuid4()),
                marketplace="Amazon",
            )
            version_numbers.append(result.version.version_number)
        except BaseException as exc:
            thread_errors.append(exc)
        finally:
            db.close()

    threads = [
        threading.Thread(target=worker, args=("a",)),
        threading.Thread(target=worker, args=("b",)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
        assert not thread.is_alive()

    if thread_errors:
        raise thread_errors[0]

    assert sorted(version_numbers) == [1, 2]

    verify = session_factory()
    try:
        product = verify.query(Product).filter(Product.id == product_id).one()
        current_version = (
            verify.query(ListingVersion)
            .filter(ListingVersion.id == product.current_listing_version_id)
            .one()
        )
        assert current_version.version_number == 2
    finally:
        verify.close()


def test_concurrent_import_same_key_same_hash_single_version(engine):
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    setup = session_factory()
    shared_key = str(uuid.uuid4())
    snapshot = sample_listing_snapshot(title="Same Payload")
    try:
        tenant = _create_tenant(setup, "listing-concurrent-idem")
        product_id = tenant["product"].id
        user_id = tenant["user"].id
    finally:
        setup.close()

    barrier = threading.Barrier(2)
    thread_errors: list[BaseException] = []
    version_ids: list[uuid.UUID] = []

    def worker():
        db = session_factory()
        try:
            barrier.wait(timeout=5)
            result = import_listing_version(
                db,
                product_id=product_id,
                current_user_id=user_id,
                snapshot=snapshot,
                idempotency_key=shared_key,
                marketplace="Amazon",
            )
            version_ids.append(result.version.id)
        except BaseException as exc:
            thread_errors.append(exc)
        finally:
            db.close()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
        assert not thread.is_alive()

    if thread_errors:
        raise thread_errors[0]

    assert len(set(version_ids)) == 1
    verify = session_factory()
    try:
        assert (
            verify.query(ListingVersion).filter(ListingVersion.product_id == product_id).count()
            == 1
        )
    finally:
        verify.close()


def test_concurrent_import_same_key_different_hash_conflict(engine):
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    setup = session_factory()
    shared_key = str(uuid.uuid4())
    try:
        tenant = _create_tenant(setup, "listing-concurrent-idem-conflict")
        product_id = tenant["product"].id
        user_id = tenant["user"].id
    finally:
        setup.close()

    barrier = threading.Barrier(2)
    thread_errors: list[BaseException] = []
    outcomes: list[str] = []
    success_titles: list[str] = []

    def worker(title: str):
        db = session_factory()
        try:
            barrier.wait(timeout=5)
            import_listing_version(
                db,
                product_id=product_id,
                current_user_id=user_id,
                snapshot=sample_listing_snapshot(title=title),
                idempotency_key=shared_key,
                marketplace="Amazon",
            )
            outcomes.append("ok")
            success_titles.append(title)
        except AppException as exc:
            if exc.error_code == IDEMPOTENCY_CONFLICT:
                outcomes.append(IDEMPOTENCY_CONFLICT)
            else:
                thread_errors.append(exc)
        except BaseException as exc:
            thread_errors.append(exc)
        finally:
            db.close()

    threads = [
        threading.Thread(target=worker, args=("Winner Title",)),
        threading.Thread(target=worker, args=("Loser Title",)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
        assert not thread.is_alive()

    if thread_errors:
        raise thread_errors[0]

    assert outcomes.count("ok") == 1
    assert outcomes.count(IDEMPOTENCY_CONFLICT) == 1

    verify = session_factory()
    try:
        product = verify.query(Product).filter(Product.id == product_id).one()
        versions = (
            verify.query(ListingVersion)
            .filter(ListingVersion.product_id == product_id)
            .order_by(ListingVersion.version_number)
            .all()
        )
        assert len(versions) == 1
        assert versions[0].version_number == 1
        assert versions[0].title == success_titles[0]
        assert product.current_listing_version_id == versions[0].id
    finally:
        verify.close()


def test_import_idempotency_conflict_does_not_session_rollback(db_session, tenant_bundle):
    tenant = tenant_bundle("listing-import-savepoint")
    tenant["product"].name = "Pending Rename"
    db_session.add(tenant["product"])
    db_session.flush()

    key = str(uuid.uuid4())
    import_listing_version(
        db_session,
        product_id=tenant["product"].id,
        current_user_id=tenant["user"].id,
        snapshot=sample_listing_snapshot(title="Winner"),
        idempotency_key=key,
        marketplace="Amazon",
    )

    with pytest.raises(AppException) as exc:
        import_listing_version(
            db_session,
            product_id=tenant["product"].id,
            current_user_id=tenant["user"].id,
            snapshot=sample_listing_snapshot(title="Loser"),
            idempotency_key=key,
            marketplace="Amazon",
        )
    assert exc.value.error_code == IDEMPOTENCY_CONFLICT
    assert tenant["product"].name == "Pending Rename"


def test_import_savepoint_integrity_error_replay(engine, monkeypatch):
    """Deterministic coverage of except IntegrityError branch (defensive fallback)."""
    from app.services import listing_version as listing_version_module

    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    setup = session_factory()
    shared_key = str(uuid.uuid4())
    snapshot = sample_listing_snapshot(title="Savepoint Winner")
    try:
        tenant = _create_tenant(setup, "listing-savepoint-replay")
        product_id = tenant["product"].id
        user_id = tenant["user"].id
        import_listing_version(
            setup,
            product_id=product_id,
            current_user_id=user_id,
            snapshot=snapshot,
            idempotency_key=shared_key,
            marketplace="Amazon",
        )
    finally:
        setup.close()

    original_find = listing_version_module._find_idempotent_version

    def find_returns_none_once(db, product_id, idempotency_key):
        find_returns_none_once.calls += 1
        if find_returns_none_once.calls == 1:
            return None
        return original_find(db, product_id, idempotency_key)

    find_returns_none_once.calls = 0
    monkeypatch.setattr(listing_version_module, "_find_idempotent_version", find_returns_none_once)

    db = session_factory()
    try:
        product = db.query(Product).filter(Product.id == product_id).one()
        product.name = "Pending Rename"
        db.add(product)
        db.flush()

        result = import_listing_version(
            db,
            product_id=product_id,
            current_user_id=user_id,
            snapshot=snapshot,
            idempotency_key=shared_key,
            marketplace="Amazon",
        )
        assert result.replay is True
        assert product.name == "Pending Rename"
    finally:
        db.close()


def test_import_replay_releases_product_row_lock(engine):
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    setup = session_factory()
    shared_key = str(uuid.uuid4())
    snapshot = sample_listing_snapshot(title="Lock Release")
    try:
        tenant = _create_tenant(setup, "listing-lock-release")
        product_id = tenant["product"].id
        user_id = tenant["user"].id
        import_listing_version(
            setup,
            product_id=product_id,
            current_user_id=user_id,
            snapshot=snapshot,
            idempotency_key=shared_key,
            marketplace="Amazon",
        )
    finally:
        setup.close()

    replay_session = session_factory()
    replay = import_listing_version(
        replay_session,
        product_id=product_id,
        current_user_id=user_id,
        snapshot=snapshot,
        idempotency_key=shared_key,
        marketplace="Amazon",
    )
    assert replay.replay is True

    lock_session = session_factory()
    try:
        locked = (
            lock_session.query(Product)
            .filter(Product.id == product_id)
            .with_for_update(nowait=True)
            .one()
        )
        locked.name = "Locked Successfully"
        lock_session.commit()
    finally:
        lock_session.close()
        replay_session.close()


def test_create_proposal_replay_releases_product_row_lock(engine):
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    setup = session_factory()
    try:
        tenant = _create_tenant(setup, "listing-create-replay-lock")
        generation_request = create_generation_request(
            setup,
            user_id=tenant["user"].id,
            product_id=tenant["product"].id,
            project_id=tenant["project"].id,
        )
        product_id = tenant["product"].id
        user_id = tenant["user"].id
        generation_request_id = generation_request.id
        candidate = sample_listing_snapshot(title="Create Replay Lock")
        create_proposal_from_generation(
            setup,
            product_id=product_id,
            current_user_id=user_id,
            generation_request_id=generation_request_id,
            candidate=candidate,
        )
    finally:
        setup.close()

    replay_session = session_factory()
    replay_proposal = create_proposal_from_generation(
        replay_session,
        product_id=product_id,
        current_user_id=user_id,
        generation_request_id=generation_request_id,
        candidate=sample_listing_snapshot(title="Different"),
    )

    lock_session = session_factory()
    try:
        lock_session.query(Product).filter(Product.id == product_id).with_for_update(nowait=True).one()
        lock_session.commit()
    finally:
        lock_session.close()
        replay_session.close()

    assert replay_proposal.candidate_snapshot["title"] == candidate.title


def test_approve_replay_releases_product_and_proposal_locks(engine):
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    setup = session_factory()
    try:
        tenant = _create_tenant(setup, "listing-approve-lock")
        generation_request = create_generation_request(
            setup,
            user_id=tenant["user"].id,
            product_id=tenant["product"].id,
            project_id=tenant["project"].id,
        )
        proposal = create_proposal_from_generation(
            setup,
            product_id=tenant["product"].id,
            current_user_id=tenant["user"].id,
            generation_request_id=generation_request.id,
            candidate=sample_listing_snapshot(title="Approved Once"),
        )
        product_id = tenant["product"].id
        user_id = tenant["user"].id
        proposal_id = proposal.id
        revision = proposal.revision
        approve_listing_proposal(
            setup,
            product_id=product_id,
            current_user_id=user_id,
            proposal_id=proposal_id,
            expected_revision=revision,
            decisions=accept_all_decisions(),
        )
    finally:
        setup.close()

    replay_session = session_factory()
    replay = approve_listing_proposal(
        replay_session,
        product_id=product_id,
        current_user_id=user_id,
        proposal_id=proposal_id,
        expected_revision=revision + 1,
        decisions=accept_all_decisions(),
    )
    assert replay.replay is True

    lock_session = session_factory()
    try:
        lock_session.query(Product).filter(Product.id == product_id).with_for_update(nowait=True).one()
        lock_session.query(ListingProposal).filter(ListingProposal.id == proposal_id).with_for_update(
            nowait=True
        ).one()
        lock_session.commit()
    finally:
        lock_session.close()
        replay_session.close()


def test_reject_replay_releases_product_and_proposal_locks(engine):
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    setup = session_factory()
    try:
        tenant = _create_tenant(setup, "listing-reject-replay-lock")
        generation_request = create_generation_request(
            setup,
            user_id=tenant["user"].id,
            product_id=tenant["product"].id,
            project_id=tenant["project"].id,
        )
        proposal = create_proposal_from_generation(
            setup,
            product_id=tenant["product"].id,
            current_user_id=tenant["user"].id,
            generation_request_id=generation_request.id,
            candidate=sample_listing_snapshot(title="Reject Replay Lock"),
        )
        product_id = tenant["product"].id
        user_id = tenant["user"].id
        proposal_id = proposal.id
        revision = proposal.revision
        reject_listing_proposal(
            setup,
            product_id=product_id,
            current_user_id=user_id,
            proposal_id=proposal_id,
            expected_revision=revision,
        )
    finally:
        setup.close()

    replay_session = session_factory()
    replay = reject_listing_proposal(
        replay_session,
        product_id=product_id,
        current_user_id=user_id,
        proposal_id=proposal_id,
        expected_revision=revision + 1,
    )
    assert replay.proposal.status == ListingProposalStatus.REJECTED
    assert replay.replay is True

    lock_session = session_factory()
    try:
        lock_session.query(Product).filter(Product.id == product_id).with_for_update(nowait=True).one()
        lock_session.query(ListingProposal).filter(ListingProposal.id == proposal_id).with_for_update(
            nowait=True
        ).one()
        lock_session.commit()
    finally:
        lock_session.close()
        replay_session.close()


def test_delete_parent_version_with_child_fails(db_session, tenant_bundle):
    tenant = tenant_bundle("listing-parent-restrict")
    first = import_listing_version(
        db_session,
        product_id=tenant["product"].id,
        current_user_id=tenant["user"].id,
        snapshot=sample_listing_snapshot(title="Parent Version"),
        idempotency_key=str(uuid.uuid4()),
        marketplace="Amazon",
    )
    second = import_listing_version(
        db_session,
        product_id=tenant["product"].id,
        current_user_id=tenant["user"].id,
        snapshot=sample_listing_snapshot(title="Child Version"),
        idempotency_key=str(uuid.uuid4()),
        marketplace="Amazon",
    )
    parent = db_session.query(ListingVersion).filter(ListingVersion.id == first.version.id).one()
    child = db_session.query(ListingVersion).filter(ListingVersion.id == second.version.id).one()
    assert child.parent_version_id == parent.id

    db_session.delete(parent)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_created_by_manual_update_to_other_user_blocked(db_session, tenant_bundle, user_factory):
    tenant = tenant_bundle("listing-created-by-block")
    other = user_factory("listing-created-by-other@example.com")
    version = import_listing_version(
        db_session,
        product_id=tenant["product"].id,
        current_user_id=tenant["user"].id,
        snapshot=sample_listing_snapshot(),
        idempotency_key=str(uuid.uuid4()),
        marketplace="Amazon",
    ).version

    with pytest.raises((OperationalError, DBAPIError)):
        db_session.execute(
            text("UPDATE listing_versions SET created_by = :uid WHERE id = :id"),
            {"uid": str(other.id), "id": str(version.id)},
        )
        db_session.commit()
    db_session.rollback()


def test_create_proposal_cross_tenant_generation_request_returns_404(db_session, tenant_bundle):
    owner = tenant_bundle("listing-gr-owner")
    intruder = tenant_bundle("listing-gr-intruder")
    generation_request = create_generation_request(
        db_session,
        user_id=owner["user"].id,
        product_id=owner["product"].id,
        project_id=owner["project"].id,
    )
    with pytest.raises(AppException) as exc:
        create_proposal_from_generation(
            db_session,
            product_id=owner["product"].id,
            current_user_id=intruder["user"].id,
            generation_request_id=generation_request.id,
            candidate=sample_listing_snapshot(),
        )
    assert exc.value.code == status.HTTP_404_NOT_FOUND


def test_approve_version_matches_compute_final_snapshot(db_session, tenant_bundle):
    tenant = tenant_bundle("listing-approve-final")
    imported = import_listing_version(
        db_session,
        product_id=tenant["product"].id,
        current_user_id=tenant["user"].id,
        snapshot=sample_listing_snapshot(title="Base Title", description="<p>Base</p>"),
        idempotency_key=str(uuid.uuid4()),
        marketplace="Amazon",
    )
    generation_request = create_generation_request(
        db_session,
        user_id=tenant["user"].id,
        product_id=tenant["product"].id,
        project_id=tenant["project"].id,
    )
    candidate = sample_listing_snapshot(title="Candidate Title", description="<p>Candidate</p>")
    proposal = create_proposal_from_generation(
        db_session,
        product_id=tenant["product"].id,
        current_user_id=tenant["user"].id,
        generation_request_id=generation_request.id,
        candidate=candidate,
    )
    decisions = FieldDecisions(
        title="accept",
        bullets="reject",
        description="accept",
        backend_keywords="reject",
    )
    base_snapshot = sample_listing_snapshot(
        title=imported.version.title,
        description=imported.version.description,
        bullets=imported.version.bullets,
        backend_keywords=imported.version.backend_keywords,
    )
    expected = compute_final_snapshot(base_snapshot, candidate, decisions)
    result = approve_listing_proposal(
        db_session,
        product_id=tenant["product"].id,
        current_user_id=tenant["user"].id,
        proposal_id=proposal.id,
        expected_revision=proposal.revision,
        decisions=decisions,
    )
    assert result.version.title == expected.title
    assert result.version.bullets == expected.bullets
    assert result.version.description == expected.description
    assert result.version.backend_keywords == expected.backend_keywords


def test_concurrent_patch_revision_only_one_succeeds(engine):
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    setup = session_factory()
    try:
        tenant = _create_tenant(setup, "listing-concurrent-patch")
        generation_request = create_generation_request(
            setup,
            user_id=tenant["user"].id,
            product_id=tenant["product"].id,
            project_id=tenant["project"].id,
        )
        proposal = create_proposal_from_generation(
            setup,
            product_id=tenant["product"].id,
            current_user_id=tenant["user"].id,
            generation_request_id=generation_request.id,
            candidate=sample_listing_snapshot(),
        )
        proposal_id = proposal.id
        product_id = tenant["product"].id
        user_id = tenant["user"].id
    finally:
        setup.close()

    barrier = threading.Barrier(2)
    thread_errors: list[BaseException] = []
    outcomes: list[str] = []

    def worker(label: str):
        db = session_factory()
        try:
            barrier.wait(timeout=5)
            patch_proposal_decisions(
                db,
                product_id=product_id,
                current_user_id=user_id,
                proposal_id=proposal_id,
                decisions=FieldDecisions(
                    title="accept" if label == "a" else "reject",
                    bullets="pending",
                    description="pending",
                    backend_keywords="pending",
                ),
                expected_revision=1,
            )
            outcomes.append("ok")
        except AppException as exc:
            if exc.error_code == LISTING_PROPOSAL_REVISION_CONFLICT:
                outcomes.append("conflict")
            else:
                thread_errors.append(exc)
        except BaseException as exc:
            thread_errors.append(exc)
        finally:
            db.close()

    threads = [
        threading.Thread(target=worker, args=("a",)),
        threading.Thread(target=worker, args=("b",)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
        assert not thread.is_alive()

    if thread_errors:
        raise thread_errors[0]

    assert outcomes.count("ok") == 1
    assert outcomes.count("conflict") == 1


def test_concurrent_approve_only_one_version(engine):
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    setup = session_factory()
    try:
        tenant = _create_tenant(setup, "listing-concurrent-approve")
        generation_request = create_generation_request(
            setup,
            user_id=tenant["user"].id,
            product_id=tenant["product"].id,
            project_id=tenant["project"].id,
        )
        proposal = create_proposal_from_generation(
            setup,
            product_id=tenant["product"].id,
            current_user_id=tenant["user"].id,
            generation_request_id=generation_request.id,
            candidate=sample_listing_snapshot(title="Concurrent Approve"),
        )
        proposal_id = proposal.id
        product_id = tenant["product"].id
        user_id = tenant["user"].id
        expected_revision = proposal.revision
    finally:
        setup.close()

    barrier = threading.Barrier(2)
    thread_errors: list[BaseException] = []
    outcomes: list[str] = []

    def worker():
        db = session_factory()
        try:
            barrier.wait(timeout=5)
            approve_listing_proposal(
                db,
                product_id=product_id,
                current_user_id=user_id,
                proposal_id=proposal_id,
                expected_revision=expected_revision,
                decisions=accept_all_decisions(),
            )
            outcomes.append("ok")
        except AppException as exc:
            outcomes.append(exc.error_code or "error")
        except BaseException as exc:
            thread_errors.append(exc)
        finally:
            db.close()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
        assert not thread.is_alive()

    if thread_errors:
        raise thread_errors[0]

    verify = session_factory()
    try:
        from app.models.user import User

        product = verify.query(Product).filter(Product.id == product_id).one()
        approved_proposal = verify.query(ListingProposal).filter(ListingProposal.id == proposal_id).one()
        versions = verify.query(ListingVersion).filter(ListingVersion.product_id == product_id).all()
        user = verify.query(User).filter(User.id == user_id).one()

        assert len(versions) == 1
        assert approved_proposal.status == ListingProposalStatus.APPROVED
        assert approved_proposal.approved_version_id == versions[0].id
        assert product.current_listing_version_id == versions[0].id
        assert user.reserved_tokens == 0
        assert outcomes.count("ok") >= 1
        replay_count = sum(1 for item in outcomes if item == "ok")
        assert replay_count == 2 or (
            replay_count == 1 and LISTING_PROPOSAL_REVISION_CONFLICT in outcomes
        )
    finally:
        verify.close()


def test_approve_failure_rolls_back(db_session, tenant_bundle):
    tenant = tenant_bundle("listing-approve-rollback")
    generation_request = create_generation_request(
        db_session,
        user_id=tenant["user"].id,
        product_id=tenant["product"].id,
        project_id=tenant["project"].id,
    )
    proposal = create_proposal_from_generation(
        db_session,
        product_id=tenant["product"].id,
        current_user_id=tenant["user"].id,
        generation_request_id=generation_request.id,
        candidate=sample_listing_snapshot(),
    )
    with pytest.raises(AppException):
        approve_listing_proposal(
            db_session,
            product_id=tenant["product"].id,
            current_user_id=tenant["user"].id,
            proposal_id=proposal.id,
            expected_revision=proposal.revision,
        )
    db_session.refresh(proposal)
    assert proposal.status == ListingProposalStatus.REVIEWING
    assert (
        db_session.query(ListingVersion)
        .filter(ListingVersion.product_id == tenant["product"].id)
        .count()
        == 0
    )


def test_proposal_state_machine_rejects_approved(db_session, tenant_bundle):
    tenant = tenant_bundle("listing-state-approved")
    generation_request = create_generation_request(
        db_session,
        user_id=tenant["user"].id,
        product_id=tenant["product"].id,
        project_id=tenant["project"].id,
    )
    proposal = create_proposal_from_generation(
        db_session,
        product_id=tenant["product"].id,
        current_user_id=tenant["user"].id,
        generation_request_id=generation_request.id,
        candidate=sample_listing_snapshot(),
    )
    approved = approve_listing_proposal(
        db_session,
        product_id=tenant["product"].id,
        current_user_id=tenant["user"].id,
        proposal_id=proposal.id,
        expected_revision=proposal.revision,
        decisions=accept_all_decisions(),
    )
    with pytest.raises(AppException) as exc:
        reject_listing_proposal(
            db_session,
            product_id=tenant["product"].id,
            current_user_id=tenant["user"].id,
            proposal_id=approved.proposal.id,
            expected_revision=approved.proposal.revision,
        )
    assert exc.value.error_code == LISTING_PROPOSAL_NOT_REVIEWING


def test_approve_explicit_marketplace_preserves_domain_override(db_session, tenant_bundle):
    tenant = tenant_bundle("listing-approve-marketplace-override")
    generation_request = create_generation_request(
        db_session,
        user_id=tenant["user"].id,
        product_id=tenant["product"].id,
        project_id=tenant["project"].id,
    )
    proposal = create_proposal_from_generation(
        db_session,
        product_id=tenant["product"].id,
        current_user_id=tenant["user"].id,
        generation_request_id=generation_request.id,
        candidate=sample_listing_snapshot(),
    )
    result = approve_listing_proposal(
        db_session,
        product_id=tenant["product"].id,
        current_user_id=tenant["user"].id,
        proposal_id=proposal.id,
        expected_revision=proposal.revision,
        decisions=accept_all_decisions(),
        marketplace="CustomMarket",
    )
    assert result.version.marketplace == "CustomMarket"


def test_create_proposal_in_transaction_rejects_product_request_mismatch(db_session, tenant_bundle):
    owner = tenant_bundle("proposal-domain-product-mismatch-a")
    other = tenant_bundle("proposal-domain-product-mismatch-b")
    generation_request = create_generation_request(
        db_session,
        user_id=owner["user"].id,
        product_id=other["product"].id,
        project_id=other["project"].id,
    )
    product = (
        db_session.query(Product)
        .filter(Product.id == owner["product"].id)
        .with_for_update()
        .one()
    )
    before = db_session.query(ListingProposal).count()
    with pytest.raises(AppException):
        create_proposal_in_transaction(
            db_session,
            product=product,
            generation_request=generation_request,
            candidate=sample_listing_snapshot(),
            allowed_statuses=frozenset({GenerationRequestStatus.SUCCEEDED}),
        )
    assert db_session.query(ListingProposal).count() == before


def test_create_proposal_in_transaction_rejects_user_mismatch(db_session, tenant_bundle, user_factory):
    owner = tenant_bundle("proposal-domain-user-owner")
    other = user_factory("proposal-domain-user-other@example.com")
    generation_request = create_generation_request(
        db_session,
        user_id=other.id,
        product_id=owner["product"].id,
        project_id=owner["project"].id,
    )
    product = (
        db_session.query(Product)
        .filter(Product.id == owner["product"].id)
        .with_for_update()
        .one()
    )
    with pytest.raises(AppException):
        create_proposal_in_transaction(
            db_session,
            product=product,
            generation_request=generation_request,
            candidate=sample_listing_snapshot(),
            allowed_statuses=frozenset({GenerationRequestStatus.SUCCEEDED}),
        )


def test_create_proposal_in_transaction_rejects_non_listing_request(db_session, tenant_bundle):
    tenant = tenant_bundle("proposal-domain-non-listing")
    generation = Generation(
        user_id=tenant["user"].id,
        product_id=tenant["product"].id,
        project_id=tenant["project"].id,
        type="analysis",
        input={"title": "x"},
        output={"strengths": [], "weaknesses": [], "opportunities": []},
        tokens_used=10,
    )
    db_session.add(generation)
    db_session.flush()
    generation_request = GenerationRequest(
        user_id=tenant["user"].id,
        request_type="analysis",
        idempotency_key=str(uuid.uuid4()),
        request_hash=str(uuid.uuid4()),
        status=GenerationRequestStatus.SUCCEEDED,
        project_id=tenant["project"].id,
        product_id=tenant["product"].id,
        input={"title": "x"},
        generation_id=generation.id,
        tokens_used=10,
    )
    db_session.add(generation_request)
    db_session.flush()
    product = (
        db_session.query(Product)
        .filter(Product.id == tenant["product"].id)
        .with_for_update()
        .one()
    )
    with pytest.raises(AppException):
        create_proposal_in_transaction(
            db_session,
            product=product,
            generation_request=generation_request,
            candidate=sample_listing_snapshot(),
            allowed_statuses=frozenset({GenerationRequestStatus.SUCCEEDED}),
        )


def test_create_proposal_in_transaction_rejects_missing_generation_id(db_session, tenant_bundle):
    tenant = tenant_bundle("proposal-domain-no-generation-id")
    generation_request = GenerationRequest(
        user_id=tenant["user"].id,
        request_type="listing",
        idempotency_key=str(uuid.uuid4()),
        request_hash=str(uuid.uuid4()),
        status=GenerationRequestStatus.SUCCEEDED,
        project_id=tenant["project"].id,
        product_id=tenant["product"].id,
        input={"name": "x"},
        generation_id=None,
        tokens_used=10,
    )
    db_session.add(generation_request)
    db_session.flush()
    product = (
        db_session.query(Product)
        .filter(Product.id == tenant["product"].id)
        .with_for_update()
        .one()
    )
    with pytest.raises(AppException):
        create_proposal_in_transaction(
            db_session,
            product=product,
            generation_request=generation_request,
            candidate=sample_listing_snapshot(),
            allowed_statuses=frozenset({GenerationRequestStatus.SUCCEEDED}),
        )


def test_create_proposal_in_transaction_rejects_cross_product_replay(db_session, tenant_bundle):
    owner = tenant_bundle("proposal-domain-replay-owner")
    other = tenant_bundle("proposal-domain-replay-other")
    generation_request = create_generation_request(
        db_session,
        user_id=owner["user"].id,
        product_id=owner["product"].id,
        project_id=owner["project"].id,
    )
    existing = ListingProposal(
        product_id=other["product"].id,
        candidate_snapshot=sample_listing_snapshot().canonical_dict(),
        field_decisions=default_pending_field_decisions().to_json(),
        status=ListingProposalStatus.REVIEWING,
        revision=1,
        generation_request_id=generation_request.id,
    )
    db_session.add(existing)
    db_session.flush()
    product = (
        db_session.query(Product)
        .filter(Product.id == owner["product"].id)
        .with_for_update()
        .one()
    )
    with pytest.raises(AppException):
        create_proposal_in_transaction(
            db_session,
            product=product,
            generation_request=generation_request,
            candidate=sample_listing_snapshot(),
            allowed_statuses=frozenset({GenerationRequestStatus.SUCCEEDED}),
        )
