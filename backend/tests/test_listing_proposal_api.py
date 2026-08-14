"""REST API and generation integration tests for listing proposals."""

from __future__ import annotations

import json
import threading
import uuid

import pytest
from sqlalchemy.orm import sessionmaker

from app.core.exceptions import (
    LISTING_DECISIONS_INCOMPLETE,
    LISTING_NO_BASE_PARTIAL_ACCEPT_FORBIDDEN,
    LISTING_PROPOSAL_NOT_REVIEWING,
    LISTING_PROPOSAL_REVISION_CONFLICT,
    LISTING_PROPOSAL_STALE,
)
from app.main import app
from app.models.generation import Generation
from app.models.generation_request import GenerationRequest, GenerationRequestStatus
from app.models.listing_proposal import ListingProposal, ListingProposalStatus
from app.models.listing_version import ListingVersion
from app.models.product import Product
from app.schemas.ai_output import ListingAIOutput
from app.schemas.listing import FieldDecisions, listing_snapshot_from_ai_output
from app.services.listing_proposal import create_proposal_from_generation
from app.services.listing_version import import_listing_version
from app.services.openai import OpenAIService
from tests.fixtures.ai_outputs import (
    VALID_ANALYZE_OUTPUT,
    VALID_KEYWORDS_OUTPUT,
    VALID_LISTING_OUTPUT,
)
from tests.test_listing_versions import (
    accept_all_decisions,
    create_generation_request,
    sample_listing_snapshot,
)


def _detail_url(product_id, proposal_id) -> str:
    return f"/api/v1/products/{product_id}/listing/proposals/{proposal_id}"


def _decisions_url(product_id, proposal_id) -> str:
    return f"/api/v1/products/{product_id}/listing/proposals/{proposal_id}/decisions"


def _approve_url(product_id, proposal_id) -> str:
    return f"/api/v1/products/{product_id}/listing/proposals/{proposal_id}/approve"


def _reject_url(product_id, proposal_id) -> str:
    return f"/api/v1/products/{product_id}/listing/proposals/{proposal_id}/reject"


def _assert_no_internal_fields(payload: dict) -> None:
    serialized = json.dumps(payload)
    for forbidden in (
        "request_hash",
        "operation_idempotency_key",
        "idempotency_key",
        "traceback",
    ):
        assert forbidden not in serialized


def _mock_listing_generation(monkeypatch, *, tokens_used: int = 120):
    async def fake_generate_listing(self, **kwargs):
        result = dict(VALID_LISTING_OUTPUT)
        result["tokens_used"] = tokens_used
        return result

    monkeypatch.setattr(OpenAIService, "generate_listing", fake_generate_listing)


def _generate_listing(
    client,
    tenant,
    auth_and_idempotency,
    valid_listing_payload,
    key=None,
    *,
    isolated_client_ip=None,
    **payload_overrides,
):
    headers = auth_and_idempotency(tenant["user"], key)
    if isolated_client_ip is not None:
        headers.update(isolated_client_ip(f"prop-gen-{uuid.uuid4().hex[:8]}"))
    return client.post(
        "/api/v1/generate/listing",
        headers=headers,
        json=valid_listing_payload(tenant["project"].id, **payload_overrides),
    )


def _proposal_count_for_user(db_session, user_id) -> int:
    return (
        db_session.query(ListingProposal)
        .join(Product, ListingProposal.product_id == Product.id)
        .filter(Product.user_id == user_id)
        .count()
    )


def _expected_candidate_snapshot() -> dict:
    snapshot = listing_snapshot_from_ai_output(ListingAIOutput.model_validate(VALID_LISTING_OUTPUT))
    return snapshot.canonical_dict()


def _create_proposal_via_service(db_session, tenant):
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
    return proposal, generation_request


def _pending_decisions_body(revision: int, **overrides) -> dict:
    decisions = {
        "title": "pending",
        "bullets": "pending",
        "description": "pending",
        "backend_keywords": "pending",
    }
    decisions.update(overrides)
    return {"expected_revision": revision, "decisions": decisions}


# --- A. Generation hooks ---


@pytest.mark.asyncio
async def test_listing_generate_success_creates_reviewing_proposal(
    client, tenant_bundle, auth_and_idempotency, valid_listing_payload, db_session, monkeypatch, isolated_client_ip
):
    tenant = tenant_bundle("prop-gen-create")
    _mock_listing_generation(monkeypatch)
    before = _proposal_count_for_user(db_session, tenant["user"].id)
    response = _generate_listing(
        client, tenant, auth_and_idempotency, valid_listing_payload, isolated_client_ip=isolated_client_ip
    )
    assert response.status_code == 200
    assert _proposal_count_for_user(db_session, tenant["user"].id) == before + 1
    proposal = (
        db_session.query(ListingProposal)
        .join(Product, ListingProposal.product_id == Product.id)
        .filter(Product.user_id == tenant["user"].id)
        .one()
    )
    assert proposal.status == ListingProposalStatus.REVIEWING


@pytest.mark.asyncio
async def test_listing_generate_candidate_snapshot_matches_ai_output(
    client, tenant_bundle, auth_and_idempotency, valid_listing_payload, db_session, monkeypatch, isolated_client_ip
):
    tenant = tenant_bundle("prop-gen-candidate")
    _mock_listing_generation(monkeypatch)
    _generate_listing(
        client, tenant, auth_and_idempotency, valid_listing_payload, isolated_client_ip=isolated_client_ip
    )
    proposal = (
        db_session.query(ListingProposal)
        .join(Product, ListingProposal.product_id == Product.id)
        .filter(Product.user_id == tenant["user"].id)
        .one()
    )
    assert proposal.candidate_snapshot == _expected_candidate_snapshot()


@pytest.mark.asyncio
async def test_listing_generate_without_current_sets_null_base(
    client, tenant_bundle, auth_and_idempotency, valid_listing_payload, db_session, monkeypatch, isolated_client_ip
):
    tenant = tenant_bundle("prop-gen-no-base")
    _mock_listing_generation(monkeypatch)
    _generate_listing(
        client, tenant, auth_and_idempotency, valid_listing_payload, isolated_client_ip=isolated_client_ip
    )
    proposal = (
        db_session.query(ListingProposal)
        .join(Product, ListingProposal.product_id == Product.id)
        .filter(Product.user_id == tenant["user"].id)
        .one()
    )
    assert proposal.base_version_id is None


@pytest.mark.asyncio
async def test_listing_generate_with_current_sets_base_version_id(
    client, tenant_bundle, auth_and_idempotency, valid_listing_payload, db_session, monkeypatch, isolated_client_ip
):
    tenant = tenant_bundle("prop-gen-with-base")
    imported = import_listing_version(
        db_session,
        product_id=tenant["product"].id,
        current_user_id=tenant["user"].id,
        snapshot=sample_listing_snapshot(),
        idempotency_key=str(uuid.uuid4()),
        request_hash=str(uuid.uuid4()),
    )
    _mock_listing_generation(monkeypatch)
    _generate_listing(
        client,
        tenant,
        auth_and_idempotency,
        valid_listing_payload,
        isolated_client_ip=isolated_client_ip,
        product_id=str(tenant["product"].id),
    )
    proposal = (
        db_session.query(ListingProposal)
        .filter(ListingProposal.product_id == tenant["product"].id)
        .one()
    )
    assert proposal.base_version_id == imported.version.id


@pytest.mark.asyncio
async def test_listing_generate_does_not_create_version(
    client, tenant_bundle, auth_and_idempotency, valid_listing_payload, db_session, monkeypatch, isolated_client_ip
):
    tenant = tenant_bundle("prop-gen-no-version")
    _mock_listing_generation(monkeypatch)
    before = (
        db_session.query(ListingVersion)
        .join(Product, ListingVersion.product_id == Product.id)
        .filter(Product.user_id == tenant["user"].id)
        .count()
    )
    _generate_listing(
        client, tenant, auth_and_idempotency, valid_listing_payload, isolated_client_ip=isolated_client_ip
    )
    after = (
        db_session.query(ListingVersion)
        .join(Product, ListingVersion.product_id == Product.id)
        .filter(Product.user_id == tenant["user"].id)
        .count()
    )
    assert after == before


@pytest.mark.asyncio
async def test_listing_generate_does_not_update_current(
    client, tenant_bundle, auth_and_idempotency, valid_listing_payload, db_session, monkeypatch, isolated_client_ip
):
    tenant = tenant_bundle("prop-gen-no-current")
    imported = import_listing_version(
        db_session,
        product_id=tenant["product"].id,
        current_user_id=tenant["user"].id,
        snapshot=sample_listing_snapshot(),
        idempotency_key=str(uuid.uuid4()),
        request_hash=str(uuid.uuid4()),
    )
    _mock_listing_generation(monkeypatch)
    _generate_listing(
        client,
        tenant,
        auth_and_idempotency,
        valid_listing_payload,
        isolated_client_ip=isolated_client_ip,
        product_id=str(tenant["product"].id),
    )
    db_session.refresh(tenant["product"])
    assert tenant["product"].current_listing_version_id == imported.version.id


@pytest.mark.asyncio
async def test_listing_generate_response_includes_proposal_summary(
    client, tenant_bundle, auth_and_idempotency, valid_listing_payload, monkeypatch, isolated_client_ip
):
    tenant = tenant_bundle("prop-gen-summary")
    _mock_listing_generation(monkeypatch)
    response = _generate_listing(
        client, tenant, auth_and_idempotency, valid_listing_payload, isolated_client_ip=isolated_client_ip
    )
    assert response.status_code == 200
    proposal = response.json()["data"]["proposal"]
    assert proposal["status"] == "reviewing"
    assert proposal["revision"] == 1
    assert "id" in proposal


@pytest.mark.asyncio
async def test_listing_generate_persists_proposal_summary_in_response_payload(
    client, tenant_bundle, auth_and_idempotency, valid_listing_payload, db_session, monkeypatch, isolated_client_ip
):
    tenant = tenant_bundle("prop-gen-persist")
    _mock_listing_generation(monkeypatch)
    key = str(uuid.uuid4())
    response = _generate_listing(
        client,
        tenant,
        auth_and_idempotency,
        valid_listing_payload,
        key,
        isolated_client_ip=isolated_client_ip,
    )
    assert response.status_code == 200
    api_proposal = response.json()["data"]["proposal"]
    record = (
        db_session.query(GenerationRequest)
        .filter(GenerationRequest.idempotency_key == key)
        .one()
    )
    assert record.response_payload["proposal"]["id"] == api_proposal["id"]


@pytest.mark.asyncio
async def test_listing_generate_idempotent_replay_returns_same_proposal_id(
    client, tenant_bundle, auth_and_idempotency, valid_listing_payload, db_session, monkeypatch, isolated_client_ip
):
    tenant = tenant_bundle("prop-gen-replay")
    _mock_listing_generation(monkeypatch)
    key = str(uuid.uuid4())
    ip = isolated_client_ip(f"prop-replay-{uuid.uuid4().hex[:8]}")
    first = _generate_listing(
        client, tenant, auth_and_idempotency, valid_listing_payload, key, isolated_client_ip=lambda _: ip
    )
    second = _generate_listing(
        client, tenant, auth_and_idempotency, valid_listing_payload, key, isolated_client_ip=lambda _: ip
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["data"]["proposal"]["id"] == second.json()["data"]["proposal"]["id"]
    assert _proposal_count_for_user(db_session, tenant["user"].id) == 1


@pytest.mark.asyncio
async def test_listing_generate_concurrent_same_key_single_proposal(
    engine, monkeypatch, valid_listing_payload
):
    from tests.test_fault_injection import _listing_fixture

    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    user, project, body, key, request_hash, _canonical = _listing_fixture(session_factory)
    llm_calls = {"count": 0}

    async def counting_listing(self, **kwargs):
        llm_calls["count"] += 1
        result = dict(VALID_LISTING_OUTPUT)
        result["tokens_used"] = 120
        return result

    monkeypatch.setattr(OpenAIService, "generate_listing", counting_listing)

    from app.services.generation_executor import GenerationExecutor
    from app.services.idempotency import canonical_request_hash

    request_hash = canonical_request_hash(
        {
            "project_id": str(project.id),
            "product_id": None,
            "name": body.name,
            "category": body.category,
            "market": body.market,
            "platform": body.platform,
            "target_customer": None,
            "advantages": None,
        }
    )
    begin_barrier = threading.Barrier(2)
    thread_errors: list[BaseException] = []
    original_begin = GenerationExecutor.begin_execution

    def begin_at_barrier(self, **kwargs):
        begin_barrier.wait(timeout=5)
        return original_begin(self, **kwargs)

    monkeypatch.setattr(GenerationExecutor, "begin_execution", begin_at_barrier)

    def worker():
        db = session_factory()
        try:
            import asyncio

            from app.core.exceptions import GENERATION_IN_PROGRESS, AppException

            executor = GenerationExecutor(db)
            try:
                asyncio.run(
                    executor.execute_listing(
                        user_id=str(user.id),
                        body=body,
                        idempotency_key=key,
                        request_hash=request_hash,
                    )
                )
            except AppException as exc:
                if exc.error_code != GENERATION_IN_PROGRESS:
                    raise
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
        assert llm_calls["count"] == 1
        assert (
            verify.query(ListingProposal)
            .join(Product, ListingProposal.product_id == Product.id)
            .filter(Product.user_id == user.id)
            .count()
            == 1
        )
    finally:
        verify.close()


@pytest.mark.asyncio
async def test_analyze_generate_does_not_create_proposal(
    client, tenant_bundle, auth_and_idempotency, db_session, monkeypatch, isolated_client_ip
):
    tenant = tenant_bundle("prop-analyze-none")

    async def fake_analyze(self, **kwargs):
        return {**VALID_ANALYZE_OUTPUT, "tokens_used": 50}

    monkeypatch.setattr(OpenAIService, "analyze_listing", fake_analyze)
    before = _proposal_count_for_user(db_session, tenant["user"].id)
    response = client.post(
        "/api/v1/generate/analyze",
        headers={
            **auth_and_idempotency(tenant["user"]),
            **isolated_client_ip(f"prop-analyze-{uuid.uuid4().hex[:8]}"),
        },
        json={
            "project_id": str(tenant["project"].id),
            "title": "Test",
            "reviews": 100,
            "rating": 4.5,
            "description": "Desc",
        },
    )
    assert response.status_code == 200
    assert _proposal_count_for_user(db_session, tenant["user"].id) == before
    assert "proposal" not in response.json()["data"]


@pytest.mark.asyncio
async def test_analyze_finalize_preserves_generation_request_product_id(
    client, tenant_bundle, auth_and_idempotency, db_session, monkeypatch, isolated_client_ip
):
    tenant = tenant_bundle("prop-analyze-request-link")

    async def fake_analyze(self, **kwargs):
        return {**VALID_ANALYZE_OUTPUT, "tokens_used": 50}

    monkeypatch.setattr(OpenAIService, "analyze_listing", fake_analyze)
    key = str(uuid.uuid4())
    response = client.post(
        "/api/v1/generate/analyze",
        headers={
            **auth_and_idempotency(tenant["user"], key),
            **isolated_client_ip(f"prop-analyze-req-{uuid.uuid4().hex[:8]}"),
        },
        json={
            "project_id": str(tenant["project"].id),
            "title": "Test",
            "reviews": 100,
            "rating": 4.5,
            "description": "Desc",
        },
    )
    assert response.status_code == 200
    assert "proposal" not in response.json()["data"]
    record = (
        db_session.query(GenerationRequest)
        .filter(GenerationRequest.idempotency_key == key)
        .one()
    )
    generation = db_session.query(Generation).filter(Generation.id == record.generation_id).one()
    assert record.status == GenerationRequestStatus.SUCCEEDED
    assert record.product_id == generation.product_id
    assert record.generation_id == generation.id
    assert _proposal_count_for_user(db_session, tenant["user"].id) == 0


@pytest.mark.asyncio
async def test_keywords_finalize_preserves_generation_request_product_id(
    client, tenant_bundle, auth_and_idempotency, valid_listing_payload, db_session, monkeypatch, isolated_client_ip
):
    tenant = tenant_bundle("prop-keywords-request-link")

    async def fake_keywords(self, **kwargs):
        return {**VALID_KEYWORDS_OUTPUT, "tokens_used": 50}

    monkeypatch.setattr(OpenAIService, "generate_keywords", fake_keywords)
    key = str(uuid.uuid4())
    response = client.post(
        "/api/v1/generate/keywords",
        headers={
            **auth_and_idempotency(tenant["user"], key),
            **isolated_client_ip(f"prop-keywords-req-{uuid.uuid4().hex[:8]}"),
        },
        json=valid_listing_payload(tenant["project"].id),
    )
    assert response.status_code == 200
    assert "proposal" not in response.json()["data"]
    record = (
        db_session.query(GenerationRequest)
        .filter(GenerationRequest.idempotency_key == key)
        .one()
    )
    generation = db_session.query(Generation).filter(Generation.id == record.generation_id).one()
    assert record.status == GenerationRequestStatus.SUCCEEDED
    assert record.product_id is not None
    assert record.product_id == generation.product_id
    assert record.generation_id == generation.id
    product = db_session.query(Product).filter(Product.id == record.product_id).one()
    assert product.user_id == tenant["user"].id
    assert _proposal_count_for_user(db_session, tenant["user"].id) == 0


@pytest.mark.asyncio
async def test_keywords_generate_does_not_create_proposal(
    client, tenant_bundle, auth_and_idempotency, valid_listing_payload, db_session, monkeypatch, isolated_client_ip
):
    tenant = tenant_bundle("prop-keywords-none")

    async def fake_keywords(self, **kwargs):
        return {**VALID_KEYWORDS_OUTPUT, "tokens_used": 50}

    monkeypatch.setattr(OpenAIService, "generate_keywords", fake_keywords)
    before = _proposal_count_for_user(db_session, tenant["user"].id)
    response = client.post(
        "/api/v1/generate/keywords",
        headers={
            **auth_and_idempotency(tenant["user"]),
            **isolated_client_ip(f"prop-keywords-{uuid.uuid4().hex[:8]}"),
        },
        json=valid_listing_payload(tenant["project"].id),
    )
    assert response.status_code == 200
    assert _proposal_count_for_user(db_session, tenant["user"].id) == before
    assert "proposal" not in response.json()["data"]


def test_non_listing_output_not_used_for_proposal_helper():
    snapshot = sample_listing_snapshot()
    assert snapshot.canonical_dict()["backend_keywords"]


@pytest.mark.asyncio
async def test_listing_generate_links_proposal_to_generation_request(
    client, tenant_bundle, auth_and_idempotency, valid_listing_payload, db_session, monkeypatch, isolated_client_ip
):
    tenant = tenant_bundle("prop-gen-link")
    _mock_listing_generation(monkeypatch)
    key = str(uuid.uuid4())
    response = _generate_listing(
        client,
        tenant,
        auth_and_idempotency,
        valid_listing_payload,
        key,
        isolated_client_ip=isolated_client_ip,
    )
    assert response.status_code == 200
    request = (
        db_session.query(GenerationRequest)
        .filter(GenerationRequest.idempotency_key == key)
        .one()
    )
    proposal = (
        db_session.query(ListingProposal)
        .filter(ListingProposal.generation_request_id == request.id)
        .one()
    )
    assert proposal.generation_request_id == request.id
    assert request.status == GenerationRequestStatus.SUCCEEDED


# --- C. Proposal detail ---


def test_get_proposal_detail_with_diff(client, tenant_bundle, auth_header, db_session):
    tenant = tenant_bundle("prop-detail")
    proposal, _ = _create_proposal_via_service(db_session, tenant)
    response = client.get(
        _detail_url(tenant["product"].id, proposal.id),
        headers=auth_header(tenant["user"]),
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["proposal"]["id"] == str(proposal.id)
    assert data["diff"]["title"]["changed"] is True
    _assert_no_internal_fields(data)


def test_get_proposal_detail_without_base(client, tenant_bundle, auth_header, db_session):
    tenant = tenant_bundle("prop-detail-no-base")
    proposal, _ = _create_proposal_via_service(db_session, tenant)
    response = client.get(
        _detail_url(tenant["product"].id, proposal.id),
        headers=auth_header(tenant["user"]),
    )
    data = response.json()["data"]
    assert data["base_version"] is None
    assert data["diff"]["title"]["base"] is None


def test_get_proposal_detail_with_base_shows_changed_fields(
    client, tenant_bundle, auth_header, db_session
):
    tenant = tenant_bundle("prop-detail-base")
    imported = import_listing_version(
        db_session,
        product_id=tenant["product"].id,
        current_user_id=tenant["user"].id,
        snapshot=sample_listing_snapshot(title="Base Title"),
        idempotency_key=str(uuid.uuid4()),
        request_hash=str(uuid.uuid4()),
    )
    proposal, _ = _create_proposal_via_service(db_session, tenant)
    db_session.query(ListingProposal).filter(ListingProposal.id == proposal.id).update(
        {"base_version_id": imported.version.id}
    )
    db_session.commit()
    response = client.get(
        _detail_url(tenant["product"].id, proposal.id),
        headers=auth_header(tenant["user"]),
    )
    diff = response.json()["data"]["diff"]
    assert diff["title"]["base"] == "Base Title"
    assert diff["title"]["changed"] is True


def test_get_proposal_detail_after_approve_includes_approved_version(
    client, tenant_bundle, auth_header, db_session
):
    tenant = tenant_bundle("prop-detail-approved")
    proposal, _ = _create_proposal_via_service(db_session, tenant)
    approve = client.post(
        _approve_url(tenant["product"].id, proposal.id),
        headers=auth_header(tenant["user"]),
        json={"expected_revision": proposal.revision, "decisions": accept_all_decisions().model_dump()},
    )
    assert approve.status_code == 200
    response = client.get(
        _detail_url(tenant["product"].id, proposal.id),
        headers=auth_header(tenant["user"]),
    )
    data = response.json()["data"]
    assert data["approved_version"] is not None
    assert data["proposal"]["status"] == "approved"


def test_get_proposal_detail_corrupt_candidate_returns_404(
    client, tenant_bundle, auth_header, db_session
):
    tenant = tenant_bundle("prop-detail-corrupt")
    proposal, _ = _create_proposal_via_service(db_session, tenant)
    db_session.query(ListingProposal).filter(ListingProposal.id == proposal.id).update(
        {"candidate_snapshot": {"title": "only title"}}
    )
    db_session.commit()
    response = client.get(
        _detail_url(tenant["product"].id, proposal.id),
        headers=auth_header(tenant["user"]),
    )
    assert response.status_code == 404


def test_get_proposal_detail_cross_tenant_returns_404(client, tenant_bundle, auth_header, db_session):
    owner = tenant_bundle("prop-detail-owner")
    other = tenant_bundle("prop-detail-other")
    proposal, _ = _create_proposal_via_service(db_session, owner)
    response = client.get(
        _detail_url(owner["product"].id, proposal.id),
        headers=auth_header(other["user"]),
    )
    assert response.status_code == 404


def test_get_proposal_detail_cross_product_returns_404(client, tenant_bundle, auth_header, db_session):
    tenant_a = tenant_bundle("prop-detail-a")
    tenant_b = tenant_bundle("prop-detail-b")
    proposal, _ = _create_proposal_via_service(db_session, tenant_a)
    response = client.get(
        _detail_url(tenant_b["product"].id, proposal.id),
        headers=auth_header(tenant_a["user"]),
    )
    assert response.status_code == 404


# --- D. PATCH decisions ---


def test_patch_proposal_decisions_updates_fields(client, tenant_bundle, auth_header, db_session):
    tenant = tenant_bundle("prop-patch")
    proposal, _ = _create_proposal_via_service(db_session, tenant)
    body = _pending_decisions_body(proposal.revision, title="accept", bullets="reject")
    response = client.patch(
        _decisions_url(tenant["product"].id, proposal.id),
        headers=auth_header(tenant["user"]),
        json=body,
    )
    assert response.status_code == 200
    updated = response.json()["data"]["proposal"]
    assert updated["field_decisions"]["title"] == "accept"
    assert updated["field_decisions"]["bullets"] == "reject"


def test_patch_proposal_decisions_increments_revision(client, tenant_bundle, auth_header, db_session):
    tenant = tenant_bundle("prop-patch-rev")
    proposal, _ = _create_proposal_via_service(db_session, tenant)
    initial_revision = proposal.revision
    response = client.patch(
        _decisions_url(tenant["product"].id, proposal.id),
        headers=auth_header(tenant["user"]),
        json=_pending_decisions_body(initial_revision, title="accept"),
    )
    assert response.json()["data"]["proposal"]["revision"] == initial_revision + 1


def test_patch_proposal_decisions_stale_revision_returns_409(
    client, tenant_bundle, auth_header, db_session
):
    tenant = tenant_bundle("prop-patch-stale")
    proposal, _ = _create_proposal_via_service(db_session, tenant)
    response = client.patch(
        _decisions_url(tenant["product"].id, proposal.id),
        headers=auth_header(tenant["user"]),
        json=_pending_decisions_body(proposal.revision + 1, title="accept"),
    )
    assert response.status_code == 409
    assert response.json()["error_code"] == LISTING_PROPOSAL_REVISION_CONFLICT


def test_patch_proposal_decisions_invalid_body_returns_422(
    client, tenant_bundle, auth_header, db_session
):
    tenant = tenant_bundle("prop-patch-422")
    proposal, _ = _create_proposal_via_service(db_session, tenant)
    response = client.patch(
        _decisions_url(tenant["product"].id, proposal.id),
        headers=auth_header(tenant["user"]),
        json={"expected_revision": 1, "decisions": {"title": "accept"}},
    )
    assert response.status_code == 422


def test_patch_proposal_decisions_extra_field_returns_422(
    client, tenant_bundle, auth_header, db_session
):
    tenant = tenant_bundle("prop-patch-extra")
    proposal, _ = _create_proposal_via_service(db_session, tenant)
    body = _pending_decisions_body(proposal.revision)
    body["extra"] = "nope"
    response = client.patch(
        _decisions_url(tenant["product"].id, proposal.id),
        headers=auth_header(tenant["user"]),
        json=body,
    )
    assert response.status_code == 422


def test_patch_proposal_decisions_non_reviewing_returns_409(
    client, tenant_bundle, auth_header, db_session
):
    tenant = tenant_bundle("prop-patch-not-reviewing")
    proposal, _ = _create_proposal_via_service(db_session, tenant)
    client.post(
        _reject_url(tenant["product"].id, proposal.id),
        headers=auth_header(tenant["user"]),
        json={"expected_revision": proposal.revision},
    )
    response = client.patch(
        _decisions_url(tenant["product"].id, proposal.id),
        headers=auth_header(tenant["user"]),
        json=_pending_decisions_body(proposal.revision + 1, title="accept"),
    )
    assert response.status_code == 409
    assert response.json()["error_code"] == LISTING_PROPOSAL_NOT_REVIEWING


def test_patch_proposal_decisions_cross_tenant_returns_404(
    client, tenant_bundle, auth_header, db_session
):
    owner = tenant_bundle("prop-patch-owner")
    other = tenant_bundle("prop-patch-other")
    proposal, _ = _create_proposal_via_service(db_session, owner)
    response = client.patch(
        _decisions_url(owner["product"].id, proposal.id),
        headers=auth_header(other["user"]),
        json=_pending_decisions_body(proposal.revision, title="accept"),
    )
    assert response.status_code == 404


# --- E. Approve ---


def test_approve_without_base_all_accept_creates_v1_current(
    client, tenant_bundle, auth_header, db_session
):
    tenant = tenant_bundle("prop-approve-no-base")
    proposal, _ = _create_proposal_via_service(db_session, tenant)
    response = client.post(
        _approve_url(tenant["product"].id, proposal.id),
        headers=auth_header(tenant["user"]),
        json={"expected_revision": proposal.revision, "decisions": accept_all_decisions().model_dump()},
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["approved_version"]["version_number"] == 1
    assert data["approved_version"]["is_current"] is True
    assert data["replay"] is False


def test_approve_without_base_partial_accept_returns_409(
    client, tenant_bundle, auth_header, db_session
):
    tenant = tenant_bundle("prop-approve-partial")
    proposal, _ = _create_proposal_via_service(db_session, tenant)
    decisions = accept_all_decisions().model_dump()
    decisions["title"] = "reject"
    response = client.post(
        _approve_url(tenant["product"].id, proposal.id),
        headers=auth_header(tenant["user"]),
        json={"expected_revision": proposal.revision, "decisions": decisions},
    )
    assert response.status_code == 409
    assert response.json()["error_code"] == LISTING_NO_BASE_PARTIAL_ACCEPT_FORBIDDEN


def test_approve_with_pending_decisions_returns_409(client, tenant_bundle, auth_header, db_session):
    tenant = tenant_bundle("prop-approve-pending")
    proposal, _ = _create_proposal_via_service(db_session, tenant)
    response = client.post(
        _approve_url(tenant["product"].id, proposal.id),
        headers=auth_header(tenant["user"]),
        json={"expected_revision": proposal.revision},
    )
    assert response.status_code == 409
    assert response.json()["error_code"] == LISTING_DECISIONS_INCOMPLETE


def test_approve_all_reject_returns_409(client, tenant_bundle, auth_header, db_session):
    tenant = tenant_bundle("prop-approve-all-reject")
    proposal, _ = _create_proposal_via_service(db_session, tenant)
    response = client.post(
        _approve_url(tenant["product"].id, proposal.id),
        headers=auth_header(tenant["user"]),
        json={
            "expected_revision": proposal.revision,
            "decisions": FieldDecisions(
                title="reject",
                bullets="reject",
                description="reject",
                backend_keywords="reject",
            ).model_dump(),
        },
    )
    assert response.status_code == 409


def test_approve_with_base_partial_decisions_computes_final_snapshot(
    client, tenant_bundle, auth_header, db_session
):
    tenant = tenant_bundle("prop-approve-partial-base")
    imported = import_listing_version(
        db_session,
        product_id=tenant["product"].id,
        current_user_id=tenant["user"].id,
        snapshot=sample_listing_snapshot(title="Base Title"),
        idempotency_key=str(uuid.uuid4()),
        request_hash=str(uuid.uuid4()),
    )
    proposal, _ = _create_proposal_via_service(db_session, tenant)
    db_session.query(ListingProposal).filter(ListingProposal.id == proposal.id).update(
        {"base_version_id": imported.version.id}
    )
    db_session.commit()
    db_session.refresh(proposal)
    response = client.post(
        _approve_url(tenant["product"].id, proposal.id),
        headers=auth_header(tenant["user"]),
        json={
            "expected_revision": proposal.revision,
            "decisions": FieldDecisions(
                title="accept",
                bullets="reject",
                description="accept",
                backend_keywords="accept",
            ).model_dump(),
        },
    )
    assert response.status_code == 200
    version = response.json()["data"]["approved_version"]
    assert version["title"] != "Base Title"
    assert version["bullets"] == imported.version.bullets


def test_approve_stale_base_returns_409(client, tenant_bundle, auth_header, db_session):
    tenant = tenant_bundle("prop-approve-stale")
    first = import_listing_version(
        db_session,
        product_id=tenant["product"].id,
        current_user_id=tenant["user"].id,
        snapshot=sample_listing_snapshot(title="V1"),
        idempotency_key=str(uuid.uuid4()),
        request_hash=str(uuid.uuid4()),
    )
    proposal, _ = _create_proposal_via_service(db_session, tenant)
    db_session.query(ListingProposal).filter(ListingProposal.id == proposal.id).update(
        {"base_version_id": first.version.id}
    )
    import_listing_version(
        db_session,
        product_id=tenant["product"].id,
        current_user_id=tenant["user"].id,
        snapshot=sample_listing_snapshot(title="V2"),
        idempotency_key=str(uuid.uuid4()),
        request_hash=str(uuid.uuid4()),
    )
    db_session.commit()
    db_session.refresh(proposal)
    response = client.post(
        _approve_url(tenant["product"].id, proposal.id),
        headers=auth_header(tenant["user"]),
        json={"expected_revision": proposal.revision, "decisions": accept_all_decisions().model_dump()},
    )
    assert response.status_code == 409
    assert response.json()["error_code"] == LISTING_PROPOSAL_STALE


def test_approve_replay_returns_same_version(client, tenant_bundle, auth_header, db_session):
    tenant = tenant_bundle("prop-approve-replay")
    proposal, _ = _create_proposal_via_service(db_session, tenant)
    body = {"expected_revision": proposal.revision, "decisions": accept_all_decisions().model_dump()}
    first = client.post(
        _approve_url(tenant["product"].id, proposal.id),
        headers=auth_header(tenant["user"]),
        json=body,
    )
    second = client.post(
        _approve_url(tenant["product"].id, proposal.id),
        headers=auth_header(tenant["user"]),
        json={"expected_revision": first.json()["data"]["proposal"]["revision"]},
    )
    assert second.json()["data"]["replay"] is True
    assert (
        first.json()["data"]["approved_version"]["id"]
        == second.json()["data"]["approved_version"]["id"]
    )


def test_approve_replay_does_not_increment_version_number(
    client, tenant_bundle, auth_header, db_session
):
    tenant = tenant_bundle("prop-approve-no-dup-version")
    proposal, _ = _create_proposal_via_service(db_session, tenant)
    body = {"expected_revision": proposal.revision, "decisions": accept_all_decisions().model_dump()}
    client.post(_approve_url(tenant["product"].id, proposal.id), headers=auth_header(tenant["user"]), json=body)
    client.post(
        _approve_url(tenant["product"].id, proposal.id),
        headers=auth_header(tenant["user"]),
        json={"expected_revision": 2},
    )
    assert db_session.query(ListingVersion).filter(ListingVersion.product_id == tenant["product"].id).count() == 1


def test_approve_supersedes_other_reviewing_proposals(client, tenant_bundle, auth_header, db_session):
    tenant = tenant_bundle("prop-approve-supersede")
    first_proposal, _ = _create_proposal_via_service(db_session, tenant)
    second_request = create_generation_request(
        db_session,
        user_id=tenant["user"].id,
        product_id=tenant["product"].id,
        project_id=tenant["project"].id,
    )
    second_proposal = create_proposal_from_generation(
        db_session,
        product_id=tenant["product"].id,
        current_user_id=tenant["user"].id,
        generation_request_id=second_request.id,
        candidate=sample_listing_snapshot(title="Second"),
    )
    client.post(
        _approve_url(tenant["product"].id, first_proposal.id),
        headers=auth_header(tenant["user"]),
        json={
            "expected_revision": first_proposal.revision,
            "decisions": accept_all_decisions().model_dump(),
        },
    )
    db_session.refresh(second_proposal)
    assert second_proposal.status == ListingProposalStatus.SUPERSEDED


def test_approve_cross_tenant_returns_404(client, tenant_bundle, auth_header, db_session):
    owner = tenant_bundle("prop-approve-owner")
    other = tenant_bundle("prop-approve-other")
    proposal, _ = _create_proposal_via_service(db_session, owner)
    response = client.post(
        _approve_url(owner["product"].id, proposal.id),
        headers=auth_header(other["user"]),
        json={"expected_revision": proposal.revision, "decisions": accept_all_decisions().model_dump()},
    )
    assert response.status_code == 404


def test_approve_response_does_not_leak_internal_fields(
    client, tenant_bundle, auth_header, db_session
):
    tenant = tenant_bundle("prop-approve-no-leak")
    proposal, _ = _create_proposal_via_service(db_session, tenant)
    response = client.post(
        _approve_url(tenant["product"].id, proposal.id),
        headers=auth_header(tenant["user"]),
        json={"expected_revision": proposal.revision, "decisions": accept_all_decisions().model_dump()},
    )
    _assert_no_internal_fields(response.json()["data"])


# --- F. Reject ---


def test_reject_reviewing_proposal(client, tenant_bundle, auth_header, db_session):
    tenant = tenant_bundle("prop-reject")
    proposal, _ = _create_proposal_via_service(db_session, tenant)
    response = client.post(
        _reject_url(tenant["product"].id, proposal.id),
        headers=auth_header(tenant["user"]),
        json={"expected_revision": proposal.revision},
    )
    assert response.status_code == 200
    assert response.json()["data"]["proposal"]["status"] == "rejected"
    assert response.json()["data"]["replay"] is False


def test_reject_does_not_create_version_or_change_current(
    client, tenant_bundle, auth_header, db_session
):
    tenant = tenant_bundle("prop-reject-no-version")
    imported = import_listing_version(
        db_session,
        product_id=tenant["product"].id,
        current_user_id=tenant["user"].id,
        snapshot=sample_listing_snapshot(),
        idempotency_key=str(uuid.uuid4()),
        request_hash=str(uuid.uuid4()),
    )
    proposal, _ = _create_proposal_via_service(db_session, tenant)
    client.post(
        _reject_url(tenant["product"].id, proposal.id),
        headers=auth_header(tenant["user"]),
        json={"expected_revision": proposal.revision},
    )
    db_session.refresh(tenant["product"])
    assert tenant["product"].current_listing_version_id == imported.version.id
    assert (
        db_session.query(ListingVersion)
        .filter(ListingVersion.product_id == tenant["product"].id)
        .count()
        == 1
    )


def test_reject_replay_returns_true(client, tenant_bundle, auth_header, db_session):
    tenant = tenant_bundle("prop-reject-replay")
    proposal, _ = _create_proposal_via_service(db_session, tenant)
    client.post(
        _reject_url(tenant["product"].id, proposal.id),
        headers=auth_header(tenant["user"]),
        json={"expected_revision": proposal.revision},
    )
    replay = client.post(
        _reject_url(tenant["product"].id, proposal.id),
        headers=auth_header(tenant["user"]),
        json={"expected_revision": 1},
    )
    assert replay.json()["data"]["replay"] is True


def test_reject_approved_returns_409(client, tenant_bundle, auth_header, db_session):
    tenant = tenant_bundle("prop-reject-approved")
    proposal, _ = _create_proposal_via_service(db_session, tenant)
    client.post(
        _approve_url(tenant["product"].id, proposal.id),
        headers=auth_header(tenant["user"]),
        json={"expected_revision": proposal.revision, "decisions": accept_all_decisions().model_dump()},
    )
    response = client.post(
        _reject_url(tenant["product"].id, proposal.id),
        headers=auth_header(tenant["user"]),
        json={"expected_revision": 2},
    )
    assert response.status_code == 409
    assert response.json()["error_code"] == LISTING_PROPOSAL_NOT_REVIEWING


def test_reject_stale_revision_returns_409(client, tenant_bundle, auth_header, db_session):
    tenant = tenant_bundle("prop-reject-stale")
    proposal, _ = _create_proposal_via_service(db_session, tenant)
    response = client.post(
        _reject_url(tenant["product"].id, proposal.id),
        headers=auth_header(tenant["user"]),
        json={"expected_revision": proposal.revision + 1},
    )
    assert response.status_code == 409
    assert response.json()["error_code"] == LISTING_PROPOSAL_REVISION_CONFLICT


def test_reject_cross_tenant_returns_404(client, tenant_bundle, auth_header, db_session):
    owner = tenant_bundle("prop-reject-owner")
    other = tenant_bundle("prop-reject-other")
    proposal, _ = _create_proposal_via_service(db_session, owner)
    response = client.post(
        _reject_url(owner["product"].id, proposal.id),
        headers=auth_header(other["user"]),
        json={"expected_revision": proposal.revision},
    )
    assert response.status_code == 404


# --- H. Phase 3.1 marketplace + API boundaries ---


def test_approve_uses_locked_product_platform(client, tenant_bundle, auth_header, db_session):
    tenant = tenant_bundle("prop-approve-platform")
    tenant["product"].platform = "Walmart"
    db_session.add(tenant["product"])
    db_session.commit()
    proposal, _ = _create_proposal_via_service(db_session, tenant)
    response = client.post(
        _approve_url(tenant["product"].id, proposal.id),
        headers=auth_header(tenant["user"]),
        json={"expected_revision": proposal.revision, "decisions": accept_all_decisions().model_dump()},
    )
    assert response.status_code == 200
    assert response.json()["data"]["approved_version"]["marketplace"] == "Walmart"


def test_proposal_detail_unauthenticated_returns_403(client, tenant_bundle, db_session):
    tenant = tenant_bundle("prop-api-unauth-detail")
    proposal, _ = _create_proposal_via_service(db_session, tenant)
    response = client.get(_detail_url(tenant["product"].id, proposal.id))
    assert response.status_code == 403


def test_proposal_decisions_unauthenticated_returns_403(client, tenant_bundle, db_session):
    tenant = tenant_bundle("prop-api-unauth-patch")
    proposal, _ = _create_proposal_via_service(db_session, tenant)
    response = client.patch(
        _decisions_url(tenant["product"].id, proposal.id),
        json=_pending_decisions_body(proposal.revision, title="accept"),
    )
    assert response.status_code == 403


def test_proposal_approve_unauthenticated_returns_403(client, tenant_bundle, db_session):
    tenant = tenant_bundle("prop-api-unauth-approve")
    proposal, _ = _create_proposal_via_service(db_session, tenant)
    response = client.post(
        _approve_url(tenant["product"].id, proposal.id),
        json={"expected_revision": proposal.revision, "decisions": accept_all_decisions().model_dump()},
    )
    assert response.status_code == 403


def test_proposal_reject_unauthenticated_returns_403(client, tenant_bundle, db_session):
    tenant = tenant_bundle("prop-api-unauth-reject")
    proposal, _ = _create_proposal_via_service(db_session, tenant)
    response = client.post(
        _reject_url(tenant["product"].id, proposal.id),
        json={"expected_revision": proposal.revision},
    )
    assert response.status_code == 403


def test_proposal_detail_missing_id_returns_404(client, tenant_bundle, auth_header):
    tenant = tenant_bundle("prop-api-missing")
    missing_id = uuid.uuid4()
    response = client.get(
        _detail_url(tenant["product"].id, missing_id),
        headers=auth_header(tenant["user"]),
    )
    assert response.status_code == 404


def test_proposal_approve_extra_field_returns_422(client, tenant_bundle, auth_header, db_session):
    tenant = tenant_bundle("prop-api-approve-extra")
    proposal, _ = _create_proposal_via_service(db_session, tenant)
    body = {
        "expected_revision": proposal.revision,
        "decisions": accept_all_decisions().model_dump(),
        "extra": "forbidden",
    }
    response = client.post(
        _approve_url(tenant["product"].id, proposal.id),
        headers=auth_header(tenant["user"]),
        json=body,
    )
    assert response.status_code == 422


def test_proposal_reject_extra_field_returns_422(client, tenant_bundle, auth_header, db_session):
    tenant = tenant_bundle("prop-api-reject-extra")
    proposal, _ = _create_proposal_via_service(db_session, tenant)
    response = client.post(
        _reject_url(tenant["product"].id, proposal.id),
        headers=auth_header(tenant["user"]),
        json={"expected_revision": proposal.revision, "unexpected": True},
    )
    assert response.status_code == 422


def test_proposal_detail_corrupt_candidate_error_does_not_leak_internals(
    client, tenant_bundle, auth_header, db_session
):
    tenant = tenant_bundle("prop-api-corrupt-leak")
    proposal, _ = _create_proposal_via_service(db_session, tenant)
    db_session.query(ListingProposal).filter(ListingProposal.id == proposal.id).update(
        {"candidate_snapshot": {"title": "only title", "sql": "select * from users"}}
    )
    db_session.commit()
    response = client.get(
        _detail_url(tenant["product"].id, proposal.id),
        headers=auth_header(tenant["user"]),
    )
    assert response.status_code == 404
    serialized = json.dumps(response.json()).lower()
    assert "traceback" not in serialized
    assert "select " not in serialized
    assert "only title" not in serialized


# --- G. OpenAPI ---


def test_openapi_includes_proposal_detail_path():
    paths = app.openapi()["paths"]
    assert "/api/v1/products/{product_id}/listing/proposals/{proposal_id}" in paths


def test_openapi_includes_proposal_mutation_paths():
    paths = app.openapi()["paths"]
    assert "/api/v1/products/{product_id}/listing/proposals/{proposal_id}/decisions" in paths
    assert "/api/v1/products/{product_id}/listing/proposals/{proposal_id}/approve" in paths
    assert "/api/v1/products/{product_id}/listing/proposals/{proposal_id}/reject" in paths


def test_openapi_proposal_responses_have_typed_schemas():
    schema = app.openapi()["components"]["schemas"]
    assert "ListingProposalDetailResponse" in schema
    assert "ApproveProposalResponse" in schema
    assert "RejectProposalResponse" in schema


def test_openapi_proposal_paths_declare_error_responses():
    paths = app.openapi()["paths"]
    detail = paths["/api/v1/products/{product_id}/listing/proposals/{proposal_id}"]["get"]
    assert "404" in detail["responses"]
    approve = paths["/api/v1/products/{product_id}/listing/proposals/{proposal_id}/approve"]["post"]
    assert "409" in approve["responses"]
    assert "422" in approve["responses"]
