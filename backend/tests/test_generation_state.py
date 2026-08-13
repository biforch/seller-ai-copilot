
import uuid

import pytest

from app.models.generation_request import GenerationRequest, GenerationRequestStatus
from app.prompts.versions import PROMPT_VERSIONS
from app.services.generation_executor import find_stale_processing_requests
from app.services.openai import OpenAIService
from tests.fixtures.ai_outputs import VALID_LISTING_OUTPUT


def test_successful_generation_records_model_prompt_version_and_latency(
    client,
    tenant_bundle,
    auth_and_idempotency,
    valid_listing_payload,
    db_session,
    monkeypatch,
):
    tenant = tenant_bundle("state-meta")

    async def fake_generate_listing(self, **kwargs):
        result = dict(VALID_LISTING_OUTPUT)
        result["tokens_used"] = 42
        return result

    monkeypatch.setattr(OpenAIService, "generate_listing", fake_generate_listing)

    response = client.post(
        "/api/v1/generate/listing",
        headers=auth_and_idempotency(tenant["user"]),
        json=valid_listing_payload(tenant["project"].id),
    )
    assert response.status_code == 200

    record = (
        db_session.query(GenerationRequest)
        .filter(GenerationRequest.user_id == tenant["user"].id)
        .order_by(GenerationRequest.created_at.desc())
        .first()
    )
    assert record is not None
    assert record.status == GenerationRequestStatus.SUCCEEDED
    assert record.prompt_version == PROMPT_VERSIONS["listing"]
    assert record.model
    assert record.latency_ms is not None
    assert record.tokens_used == 42


@pytest.mark.parametrize(
    "request_type,prompt_version",
    [
        ("listing", PROMPT_VERSIONS["listing"]),
        ("analysis", PROMPT_VERSIONS["analysis"]),
        ("keywords", PROMPT_VERSIONS["keywords"]),
    ],
)
def test_prompt_versions_are_stable(request_type, prompt_version):
    assert prompt_version.endswith("-v1")


def test_failed_generation_stores_sanitized_error_code(
    client,
    tenant_bundle,
    auth_and_idempotency,
    valid_listing_payload,
    db_session,
    monkeypatch,
):
    tenant = tenant_bundle("state-failed")

    async def broken_listing(self, **kwargs):
        from app.core.exceptions import ai_response_invalid_exception

        raise ai_response_invalid_exception()

    monkeypatch.setattr(OpenAIService, "generate_listing", broken_listing)

    response = client.post(
        "/api/v1/generate/listing",
        headers=auth_and_idempotency(tenant["user"]),
        json=valid_listing_payload(tenant["project"].id),
    )
    assert response.status_code == 502
    assert response.json()["error_code"] == "AI_RESPONSE_INVALID"
    assert "traceback" not in response.text.lower()

    record = (
        db_session.query(GenerationRequest)
        .filter(GenerationRequest.user_id == tenant["user"].id)
        .order_by(GenerationRequest.created_at.desc())
        .first()
    )
    assert record.status == GenerationRequestStatus.FAILED
    assert record.error_code == "AI_RESPONSE_INVALID"


def test_find_stale_processing_requests(db_session, user_factory):
    user = user_factory("stale-processing@example.com")
    stale = GenerationRequest(
        user_id=user.id,
        request_type="listing",
        idempotency_key=str(uuid.uuid4()),
        request_hash="abc",
        status=GenerationRequestStatus.PROCESSING,
        input={"name": "stale"},
    )
    from datetime import datetime, timedelta

    stale.started_at = datetime.utcnow() - timedelta(minutes=60)
    db_session.add(stale)
    db_session.commit()

    found = find_stale_processing_requests(db_session, older_than_minutes=30)
    assert any(item.id == stale.id for item in found)
