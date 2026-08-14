"""ListingSnapshot and FieldDecisions validation tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.ai_output import ListingAIOutput
from app.schemas.common_fields import LISTING_BULLETS_COUNT
from app.schemas.listing import (
    LISTING_SNAPSHOT_BULLET_MAX,
    LISTING_SNAPSHOT_BULLETS_COUNT,
    LISTING_SNAPSHOT_DESCRIPTION_MAX,
    LISTING_SNAPSHOT_KEYWORD_MAX,
    LISTING_SNAPSHOT_KEYWORDS_MAX,
    LISTING_SNAPSHOT_TITLE_MAX,
    FieldDecisions,
    ListingSnapshot,
    listing_snapshot_from_ai_output,
    listing_snapshot_from_dict,
)
from tests.fixtures.ai_outputs import VALID_LISTING_OUTPUT


def _valid_snapshot_dict(**overrides):
    base = {
        "title": "Valid Listing Title",
        "bullets": VALID_LISTING_OUTPUT["bullets"][:LISTING_SNAPSHOT_BULLETS_COUNT],
        "description": VALID_LISTING_OUTPUT["description"],
        "backend_keywords": VALID_LISTING_OUTPUT["keywords"][:10],
    }
    base.update(overrides)
    return base


def test_candidate_snapshot_rejects_missing_title():
    payload = _valid_snapshot_dict()
    del payload["title"]
    with pytest.raises(ValidationError):
        ListingSnapshot.model_validate(payload)


def test_candidate_snapshot_rejects_missing_description():
    payload = _valid_snapshot_dict()
    del payload["description"]
    with pytest.raises(ValidationError):
        ListingSnapshot.model_validate(payload)


def test_candidate_snapshot_rejects_blank_title():
    with pytest.raises(ValidationError):
        ListingSnapshot.model_validate(_valid_snapshot_dict(title="   "))


def test_candidate_snapshot_rejects_blank_description():
    with pytest.raises(ValidationError):
        ListingSnapshot.model_validate(_valid_snapshot_dict(description="  \t  "))


def test_candidate_snapshot_rejects_wrong_bullets_type():
    with pytest.raises((ValidationError, TypeError)):
        ListingSnapshot.model_validate(_valid_snapshot_dict(bullets="not-a-list"))


def test_candidate_snapshot_rejects_wrong_keywords_type():
    with pytest.raises((ValidationError, TypeError)):
        ListingSnapshot.model_validate(_valid_snapshot_dict(backend_keywords="not-a-list"))


def test_candidate_snapshot_rejects_extra_field():
    payload = _valid_snapshot_dict(extra="forbidden")
    with pytest.raises(ValidationError):
        ListingSnapshot.model_validate(payload)


def test_candidate_snapshot_rejects_title_length_overflow():
    with pytest.raises(ValidationError):
        ListingSnapshot.model_validate(_valid_snapshot_dict(title="x" * (LISTING_SNAPSHOT_TITLE_MAX + 1)))


def test_candidate_snapshot_rejects_description_length_overflow():
    with pytest.raises(ValidationError):
        ListingSnapshot.model_validate(
            _valid_snapshot_dict(description="x" * (LISTING_SNAPSHOT_DESCRIPTION_MAX + 1))
        )


def test_listing_bullets_count_matches_ai_output_contract():
    assert LISTING_SNAPSHOT_BULLETS_COUNT == LISTING_BULLETS_COUNT == 5


def test_valid_listing_ai_output_converts_to_listing_snapshot():
    ai_output = ListingAIOutput.model_validate(VALID_LISTING_OUTPUT)
    snapshot = listing_snapshot_from_ai_output(ai_output)
    assert len(snapshot.bullets) == 5
    assert snapshot.bullets == ai_output.bullets
    assert snapshot.backend_keywords == ai_output.keywords


def test_listing_snapshot_accepts_five_bullets():
    snapshot = ListingSnapshot.model_validate(_valid_snapshot_dict())
    assert len(snapshot.bullets) == 5


def test_listing_snapshot_rejects_four_bullets():
    with pytest.raises(ValidationError):
        ListingSnapshot.model_validate(
            _valid_snapshot_dict(bullets=VALID_LISTING_OUTPUT["bullets"][:4])
        )


def test_listing_snapshot_rejects_six_bullets():
    with pytest.raises(ValidationError):
        ListingSnapshot.model_validate(
            _valid_snapshot_dict(
                bullets=VALID_LISTING_OUTPUT["bullets"] + ["Extra bullet point here"]
            )
        )


def test_candidate_snapshot_rejects_bullet_count_mismatch():
    with pytest.raises(ValidationError):
        ListingSnapshot.model_validate(_valid_snapshot_dict(bullets=["one", "two", "three"]))


def test_candidate_snapshot_rejects_bullet_length_overflow():
    bullets = ["x" * (LISTING_SNAPSHOT_BULLET_MAX + 1), "b", "c", "d", "e"]
    with pytest.raises(ValidationError):
        ListingSnapshot.model_validate(_valid_snapshot_dict(bullets=bullets))


def test_candidate_snapshot_rejects_keyword_count_overflow():
    keywords = [f"keyword-{index}" for index in range(LISTING_SNAPSHOT_KEYWORDS_MAX + 1)]
    with pytest.raises(ValidationError):
        ListingSnapshot.model_validate(_valid_snapshot_dict(backend_keywords=keywords))


def test_candidate_snapshot_rejects_keyword_length_overflow():
    keywords = [f"keyword-{index}" for index in range(9)] + ["x" * (LISTING_SNAPSHOT_KEYWORD_MAX + 1)]
    with pytest.raises(ValidationError):
        ListingSnapshot.model_validate(_valid_snapshot_dict(backend_keywords=keywords))


def test_field_decisions_requires_all_four_fields():
    with pytest.raises(ValidationError):
        FieldDecisions.model_validate({"title": "pending"})


def test_field_decisions_rejects_invalid_value():
    with pytest.raises(ValidationError):
        FieldDecisions.model_validate(
            {
                "title": "maybe",
                "bullets": "pending",
                "description": "pending",
                "backend_keywords": "pending",
            }
        )


def test_field_decisions_rejects_extra_field():
    with pytest.raises(ValidationError):
        FieldDecisions.model_validate(
            {
                "title": "pending",
                "bullets": "pending",
                "description": "pending",
                "backend_keywords": "pending",
                "notes": "extra",
            }
        )


def test_listing_snapshot_from_dict_helper():
    snapshot = listing_snapshot_from_dict(_valid_snapshot_dict())
    assert snapshot.title == "Valid Listing Title"


def test_approve_revalidates_field_decisions_from_db(db_session, tenant_bundle):
    from app.models.listing_proposal import ListingProposal
    from app.services.listing_proposal import approve_listing_proposal
    from tests.test_listing_versions import (
        create_generation_request,
        create_proposal_from_generation,
        sample_listing_snapshot,
    )

    tenant = tenant_bundle("listing-revalidate-decisions")
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
        candidate=sample_listing_snapshot(title="Validated Title"),
    )
    db_session.execute(
        ListingProposal.__table__.update()
        .where(ListingProposal.id == proposal.id)
        .values(field_decisions={"title": "accept", "bullets": "accept", "description": "accept"})
    )
    db_session.commit()

    with pytest.raises(ValidationError):
        approve_listing_proposal(
            db_session,
            product_id=tenant["product"].id,
            current_user_id=tenant["user"].id,
            proposal_id=proposal.id,
            expected_revision=proposal.revision,
        )


def test_approve_revalidates_candidate_snapshot_from_db(db_session, tenant_bundle):
    from app.models.listing_proposal import ListingProposal
    from app.services.listing_proposal import approve_listing_proposal
    from tests.test_listing_versions import (
        accept_all_decisions,
        create_generation_request,
        create_proposal_from_generation,
        sample_listing_snapshot,
    )

    tenant = tenant_bundle("listing-revalidate-candidate")
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
        candidate=sample_listing_snapshot(title="Validated Title"),
    )
    db_session.execute(
        ListingProposal.__table__.update()
        .where(ListingProposal.id == proposal.id)
        .values(candidate_snapshot={"title": "only-title"})
    )
    db_session.commit()

    with pytest.raises(ValidationError):
        approve_listing_proposal(
            db_session,
            product_id=tenant["product"].id,
            current_user_id=tenant["user"].id,
            proposal_id=proposal.id,
            expected_revision=proposal.revision,
            decisions=accept_all_decisions(),
        )
