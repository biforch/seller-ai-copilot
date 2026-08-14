"""Domain services for listing proposal lifecycle."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fastapi import status
from pydantic import ValidationError
from sqlalchemy import func, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import (
    LISTING_DECISIONS_INCOMPLETE,
    LISTING_NO_BASE_PARTIAL_ACCEPT_FORBIDDEN,
    LISTING_PROPOSAL_NOT_REVIEWING,
    LISTING_PROPOSAL_REVISION_CONFLICT,
    LISTING_PROPOSAL_STALE,
    AppException,
)
from app.core.orm_utils import orm_str, orm_uuid
from app.models.generation_request import GenerationRequest, GenerationRequestStatus
from app.models.listing_proposal import ListingProposal, ListingProposalStatus
from app.models.listing_version import ListingVersion, ListingVersionSource
from app.models.product import Product
from app.schemas.listing import (
    LISTING_FIELDS,
    FieldDecisions,
    ListingSnapshot,
    default_pending_field_decisions,
)
from app.services.listing_diff import build_listing_diff, compute_final_snapshot
from app.services.listing_version import set_product_current_listing_version


@dataclass(frozen=True)
class ApproveProposalResult:
    proposal: ListingProposal
    version: ListingVersion
    replay: bool


@dataclass(frozen=True)
class RejectProposalResult:
    proposal: ListingProposal
    replay: bool


@dataclass(frozen=True)
class ListingProposalDetailResult:
    proposal: ListingProposal
    base_version: ListingVersion | None
    approved_version: ListingVersion | None
    diff: dict[str, dict[str, Any]]
    current_listing_version_id: uuid.UUID | None


def _lock_product_for_user(
    db: Session,
    product_id: uuid.UUID,
    user_id: uuid.UUID,
) -> Product:
    product = (
        db.query(Product)
        .filter(Product.id == product_id, Product.user_id == user_id)
        .with_for_update()
        .one_or_none()
    )
    if product is None:
        raise AppException(
            message="Product not found",
            code=status.HTTP_404_NOT_FOUND,
        )
    return product


def _get_proposal_for_product(
    db: Session,
    proposal_id: uuid.UUID,
    product_id: uuid.UUID,
) -> ListingProposal | None:
    return (
        db.query(ListingProposal)
        .filter(
            ListingProposal.id == proposal_id,
            ListingProposal.product_id == product_id,
        )
        .one_or_none()
    )


def _snapshot_to_version_fields(snapshot: ListingSnapshot) -> dict[str, object]:
    return {
        "title": snapshot.title,
        "bullets": snapshot.bullets,
        "description": snapshot.description,
        "backend_keywords": snapshot.backend_keywords,
    }


def _load_base_snapshot(db: Session, base_version_id: uuid.UUID | None) -> ListingSnapshot | None:
    if base_version_id is None:
        return None
    base_version = db.query(ListingVersion).filter(ListingVersion.id == base_version_id).one()
    return ListingSnapshot(
        title=base_version.title,
        bullets=base_version.bullets,
        description=base_version.description,
        backend_keywords=base_version.backend_keywords,
    )


def _version_to_snapshot(version: ListingVersion) -> ListingSnapshot:
    return ListingSnapshot(
        title=version.title,
        bullets=version.bullets,
        description=version.description,
        backend_keywords=version.backend_keywords,
    )


def proposal_summary_dict(proposal: ListingProposal) -> dict[str, Any]:
    """Public proposal summary for generation response payloads."""
    return {
        "id": str(proposal.id),
        "status": proposal.status,
        "revision": proposal.revision,
        "base_version_id": str(proposal.base_version_id) if proposal.base_version_id else None,
    }


def _proposal_base_version_id(product: Product) -> uuid.UUID | None:
    if product.current_listing_version_id is None:
        return None
    return orm_uuid(product.current_listing_version_id)


def _validate_proposal_creation_context(
    *,
    product: Product,
    generation_request: GenerationRequest,
    allowed_statuses: frozenset[str],
) -> None:
    if generation_request.product_id != product.id:
        raise AppException(
            message="Proposal creation rejected",
            code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
    if generation_request.user_id != product.user_id:
        raise AppException(
            message="Proposal creation rejected",
            code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
    if generation_request.request_type != "listing":
        raise AppException(
            message="Proposal creation rejected",
            code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
    if generation_request.generation_id is None:
        raise AppException(
            message="Proposal creation rejected",
            code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
    if orm_str(generation_request.status) not in allowed_statuses:
        raise AppException(
            message="Proposal creation rejected",
            code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


def _return_existing_proposal_for_product(
    existing: ListingProposal,
    *,
    product: Product,
) -> ListingProposal:
    if existing.product_id != product.id:
        raise AppException(
            message="Proposal creation rejected",
            code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
    return existing


def create_proposal_in_transaction(
    db: Session,
    *,
    product: Product,
    generation_request: GenerationRequest,
    candidate: ListingSnapshot,
    allowed_statuses: frozenset[str],
) -> ListingProposal:
    """Insert a reviewing proposal within the caller's transaction (no commit)."""
    _validate_proposal_creation_context(
        product=product,
        generation_request=generation_request,
        allowed_statuses=allowed_statuses,
    )
    base_version_id = _proposal_base_version_id(product)

    existing = (
        db.query(ListingProposal)
        .filter(ListingProposal.generation_request_id == generation_request.id)
        .one_or_none()
    )
    if existing is not None:
        return _return_existing_proposal_for_product(existing, product=product)

    pending_decisions = default_pending_field_decisions()
    proposal = ListingProposal(
        product_id=product.id,
        base_version_id=base_version_id,
        candidate_snapshot=candidate.canonical_dict(),
        field_decisions=pending_decisions.to_json(),
        status=ListingProposalStatus.REVIEWING,
        revision=1,
        generation_request_id=generation_request.id,
    )
    savepoint = db.begin_nested()
    try:
        db.add(proposal)
        db.flush()
    except IntegrityError:
        savepoint.rollback()
        replay = (
            db.query(ListingProposal)
            .filter(ListingProposal.generation_request_id == generation_request.id)
            .one()
        )
        return _return_existing_proposal_for_product(replay, product=product)
    return proposal


def create_proposal_from_generation(
    db: Session,
    *,
    product_id: uuid.UUID,
    current_user_id: uuid.UUID,
    generation_request_id: uuid.UUID,
    candidate: ListingSnapshot,
) -> ListingProposal:
    """Create a reviewing proposal from a succeeded listing generation request."""
    product = _lock_product_for_user(db, product_id, current_user_id)

    generation_request = (
        db.query(GenerationRequest)
        .filter(
            GenerationRequest.id == generation_request_id,
            GenerationRequest.user_id == current_user_id,
            GenerationRequest.product_id == product_id,
        )
        .one_or_none()
    )
    if (
        generation_request is None
        or generation_request.status != GenerationRequestStatus.SUCCEEDED
        or generation_request.request_type != "listing"
        or generation_request.generation_id is None
    ):
        raise AppException(
            message="Generation request not found",
            code=status.HTTP_404_NOT_FOUND,
        )

    existing = (
        db.query(ListingProposal)
        .filter(ListingProposal.generation_request_id == generation_request_id)
        .one_or_none()
    )
    if existing is not None:
        db.commit()
        db.refresh(existing)
        return _return_existing_proposal_for_product(existing, product=product)

    proposal = create_proposal_in_transaction(
        db,
        product=product,
        generation_request=generation_request,
        candidate=candidate,
        allowed_statuses=frozenset({GenerationRequestStatus.SUCCEEDED}),
    )
    db.commit()
    db.refresh(proposal)
    return proposal


def get_listing_proposal_detail(
    db: Session,
    *,
    product_id: uuid.UUID,
    current_user_id: uuid.UUID,
    proposal_id: uuid.UUID,
) -> ListingProposalDetailResult:
    """Load proposal detail with scoped base/approved versions and diff."""
    product = (
        db.query(Product)
        .filter(Product.id == product_id, Product.user_id == current_user_id)
        .one_or_none()
    )
    if product is None:
        raise AppException(
            message="Proposal not found",
            code=status.HTTP_404_NOT_FOUND,
        )

    proposal = _get_proposal_for_product(db, proposal_id, product_id)
    if proposal is None:
        raise AppException(
            message="Proposal not found",
            code=status.HTTP_404_NOT_FOUND,
        )

    try:
        candidate = ListingSnapshot.model_validate(proposal.candidate_snapshot)
        FieldDecisions.model_validate(proposal.field_decisions)
    except ValidationError:
        raise AppException(
            message="Proposal not found",
            code=status.HTTP_404_NOT_FOUND,
        ) from None

    base_version: ListingVersion | None = None
    base_snapshot: ListingSnapshot | None = None
    if proposal.base_version_id is not None:
        base_version = (
            db.query(ListingVersion)
            .filter(
                ListingVersion.id == proposal.base_version_id,
                ListingVersion.product_id == product_id,
            )
            .one_or_none()
        )
        if base_version is None:
            raise AppException(
                message="Proposal not found",
                code=status.HTTP_404_NOT_FOUND,
            )
        base_snapshot = _version_to_snapshot(base_version)

    approved_version: ListingVersion | None = None
    if proposal.approved_version_id is not None:
        approved_version = (
            db.query(ListingVersion)
            .filter(
                ListingVersion.id == proposal.approved_version_id,
                ListingVersion.product_id == product_id,
            )
            .one_or_none()
        )
        if approved_version is None:
            raise AppException(
                message="Proposal not found",
                code=status.HTTP_404_NOT_FOUND,
            )

    diff = build_listing_diff(base_snapshot, candidate)
    return ListingProposalDetailResult(
        proposal=proposal,
        base_version=base_version,
        approved_version=approved_version,
        diff=diff,
        current_listing_version_id=(
            orm_uuid(product.current_listing_version_id)
            if product.current_listing_version_id is not None
            else None
        ),
    )


def patch_proposal_decisions(
    db: Session,
    *,
    product_id: uuid.UUID,
    current_user_id: uuid.UUID,
    proposal_id: uuid.UUID,
    decisions: FieldDecisions,
    expected_revision: int,
) -> ListingProposal:
    """Atomically patch field decisions on a reviewing proposal."""
    product = _lock_product_for_user(db, product_id, current_user_id)

    stmt = (
        update(ListingProposal)
        .where(
            ListingProposal.id == proposal_id,
            ListingProposal.product_id == product.id,
            ListingProposal.status == ListingProposalStatus.REVIEWING,
            ListingProposal.revision == expected_revision,
        )
        .values(
            field_decisions=decisions.to_json(),
            revision=ListingProposal.revision + 1,
            updated_at=func.now(),
        )
        .returning(ListingProposal.id)
    )
    updated_id = db.execute(stmt).scalar_one_or_none()
    if updated_id is not None:
        db.commit()
        return db.query(ListingProposal).filter(ListingProposal.id == updated_id).one()

    proposal = _get_proposal_for_product(db, proposal_id, uuid.UUID(str(product.id)))
    if proposal is None:
        raise AppException(
            message="Proposal not found",
            code=status.HTTP_404_NOT_FOUND,
        )
    if proposal.status != ListingProposalStatus.REVIEWING:
        raise AppException(
            message="Proposal is not reviewing",
            code=status.HTTP_409_CONFLICT,
            error_code=LISTING_PROPOSAL_NOT_REVIEWING,
        )
    if proposal.revision != expected_revision:
        raise AppException(
            message="Proposal revision conflict",
            code=status.HTTP_409_CONFLICT,
            error_code=LISTING_PROPOSAL_REVISION_CONFLICT,
        )
    raise AppException(
        message="Proposal not found",
        code=status.HTTP_404_NOT_FOUND,
    )


def approve_listing_proposal(
    db: Session,
    *,
    product_id: uuid.UUID,
    current_user_id: uuid.UUID,
    proposal_id: uuid.UUID,
    expected_revision: int,
    decisions: FieldDecisions | None = None,
    marketplace: str | None = None,
    language: str = "en-US",
) -> ApproveProposalResult:
    """Approve a proposal and materialize an immutable AI listing version."""
    product = _lock_product_for_user(db, product_id, current_user_id)
    resolved_marketplace = marketplace if marketplace is not None else orm_str(product.platform)

    proposal = (
        db.query(ListingProposal)
        .filter(
            ListingProposal.id == proposal_id,
            ListingProposal.product_id == product.id,
        )
        .with_for_update()
        .one_or_none()
    )
    if proposal is None:
        raise AppException(
            message="Proposal not found",
            code=status.HTTP_404_NOT_FOUND,
        )

    if (
        proposal.status == ListingProposalStatus.APPROVED
        and proposal.approved_version_id is not None
    ):
        version = (
            db.query(ListingVersion)
            .filter(ListingVersion.id == proposal.approved_version_id)
            .one()
        )
        db.commit()
        db.refresh(proposal)
        db.refresh(version)
        return ApproveProposalResult(proposal=proposal, version=version, replay=True)

    if proposal.status in {
        ListingProposalStatus.REJECTED,
        ListingProposalStatus.SUPERSEDED,
    }:
        raise AppException(
            message="Proposal is not reviewing",
            code=status.HTTP_409_CONFLICT,
            error_code=LISTING_PROPOSAL_NOT_REVIEWING,
        )

    if proposal.revision != expected_revision:
        raise AppException(
            message="Proposal revision conflict",
            code=status.HTTP_409_CONFLICT,
            error_code=LISTING_PROPOSAL_REVISION_CONFLICT,
        )

    if proposal.status != ListingProposalStatus.REVIEWING:
        raise AppException(
            message="Proposal is not reviewing",
            code=status.HTTP_409_CONFLICT,
            error_code=LISTING_PROPOSAL_NOT_REVIEWING,
        )

    effective_decisions = decisions or FieldDecisions.model_validate(proposal.field_decisions)
    candidate = ListingSnapshot.model_validate(proposal.candidate_snapshot)

    if effective_decisions.has_pending():
        raise AppException(
            message="All field decisions must be resolved before approval",
            code=status.HTTP_409_CONFLICT,
            error_code=LISTING_DECISIONS_INCOMPLETE,
        )

    if all(getattr(effective_decisions, field_name) == "reject" for field_name in LISTING_FIELDS):
        raise AppException(
            message="Full reject must use the reject service",
            code=status.HTTP_409_CONFLICT,
            error_code=LISTING_PROPOSAL_NOT_REVIEWING,
        )

    base_snapshot = _load_base_snapshot(db, proposal.base_version_id)

    if proposal.base_version_id is not None:
        if product.current_listing_version_id != proposal.base_version_id:
            raise AppException(
                message="Proposal base version is stale",
                code=status.HTTP_409_CONFLICT,
                error_code=LISTING_PROPOSAL_STALE,
            )
    elif product.current_listing_version_id is not None:
        raise AppException(
            message="Proposal base version is stale",
            code=status.HTTP_409_CONFLICT,
            error_code=LISTING_PROPOSAL_STALE,
        )

    try:
        final_snapshot = compute_final_snapshot(base_snapshot, candidate, effective_decisions)
    except AppException as exc:
        if exc.error_code == LISTING_NO_BASE_PARTIAL_ACCEPT_FORBIDDEN:
            raise
        raise

    generation_request = (
        db.query(GenerationRequest)
        .filter(GenerationRequest.id == proposal.generation_request_id)
        .one_or_none()
    )
    generation_id = generation_request.generation_id if generation_request else None

    next_version_number = (
        db.query(func.coalesce(func.max(ListingVersion.version_number), 0))
        .filter(ListingVersion.product_id == product.id)
        .scalar()
        or 0
    ) + 1

    version_fields = _snapshot_to_version_fields(final_snapshot)
    version = ListingVersion(
        product_id=product.id,
        version_number=next_version_number,
        source=ListingVersionSource.AI,
        marketplace=resolved_marketplace,
        language=language,
        generation_id=generation_id,
        parent_version_id=proposal.base_version_id,
        created_by=current_user_id,
        **version_fields,
    )
    db.add(version)
    db.flush()

    set_product_current_listing_version(product, version)
    db.add(product)

    now = datetime.now(UTC)
    proposal.status = ListingProposalStatus.APPROVED
    proposal.approved_version_id = version.id
    proposal.field_decisions = effective_decisions.to_json()
    proposal.reviewed_by = current_user_id
    proposal.reviewed_at = now
    proposal.revision = proposal.revision + 1
    proposal.updated_at = now
    db.add(proposal)

    (
        db.query(ListingProposal)
        .filter(
            ListingProposal.product_id == product.id,
            ListingProposal.status == ListingProposalStatus.REVIEWING,
            ListingProposal.id != proposal.id,
        )
        .update(
            {
                ListingProposal.status: ListingProposalStatus.SUPERSEDED,
                ListingProposal.updated_at: now,
            },
            synchronize_session=False,
        )
    )

    db.commit()
    db.refresh(proposal)
    db.refresh(version)
    return ApproveProposalResult(proposal=proposal, version=version, replay=False)


def reject_listing_proposal(
    db: Session,
    *,
    product_id: uuid.UUID,
    current_user_id: uuid.UUID,
    proposal_id: uuid.UUID,
    expected_revision: int,
) -> RejectProposalResult:
    """Reject a reviewing proposal without creating a version."""
    product = _lock_product_for_user(db, product_id, current_user_id)

    proposal = (
        db.query(ListingProposal)
        .filter(
            ListingProposal.id == proposal_id,
            ListingProposal.product_id == product.id,
        )
        .with_for_update()
        .one_or_none()
    )
    if proposal is None:
        raise AppException(
            message="Proposal not found",
            code=status.HTTP_404_NOT_FOUND,
        )

    if proposal.status == ListingProposalStatus.REJECTED:
        db.commit()
        db.refresh(proposal)
        return RejectProposalResult(proposal=proposal, replay=True)

    if proposal.status in {
        ListingProposalStatus.APPROVED,
        ListingProposalStatus.SUPERSEDED,
    }:
        raise AppException(
            message="Proposal is not reviewing",
            code=status.HTTP_409_CONFLICT,
            error_code=LISTING_PROPOSAL_NOT_REVIEWING,
        )

    if proposal.revision != expected_revision:
        raise AppException(
            message="Proposal revision conflict",
            code=status.HTTP_409_CONFLICT,
            error_code=LISTING_PROPOSAL_REVISION_CONFLICT,
        )

    if proposal.status != ListingProposalStatus.REVIEWING:
        raise AppException(
            message="Proposal is not reviewing",
            code=status.HTTP_409_CONFLICT,
            error_code=LISTING_PROPOSAL_NOT_REVIEWING,
        )

    now = datetime.now(UTC)
    proposal.status = ListingProposalStatus.REJECTED
    proposal.reviewed_by = current_user_id
    proposal.reviewed_at = now
    proposal.revision = proposal.revision + 1
    proposal.updated_at = now
    db.add(proposal)
    db.commit()
    db.refresh(proposal)
    return RejectProposalResult(proposal=proposal, replay=False)
