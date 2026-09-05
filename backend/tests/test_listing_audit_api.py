from __future__ import annotations

import uuid

import pytest

from app.analysis.provider import OpenAIListingAuditProvider
from app.analysis.service import ListingAuditProviderResponse
from app.core.config import settings
from app.core.exceptions import AI_PROVIDER_UNAVAILABLE, AppException
from app.models.audit_usage import AuditUsage
from app.models.generation_request import GenerationRequest, GenerationRequestStatus
from app.services.quota_estimation import estimate_reserve_tokens

from .test_listing_audit_baseline import valid_output

PATH = "/api/v1/analysis/listing-audit"


def _payload(*, description: str = "A compact phone stand.") -> dict:
    return {
        "marketplace": "US",
        "language": "en-US",
        "listing": {
            "title": "Compact phone stand",
            "bullets": ["Holds a phone on a desk."],
            "description": description,
        },
        "competitor_listing": None,
        "customer_reviews": [],
    }


@pytest.fixture
def internal_enabled(monkeypatch):
    monkeypatch.setattr(settings, "LISTING_AUDIT_INTERNAL_ENABLED", True)


def test_disabled_route_fails_before_provider_construction(
    client, tenant_bundle, auth_and_idempotency, monkeypatch
) -> None:
    tenant = tenant_bundle("audit-disabled")
    monkeypatch.setattr(settings, "LISTING_AUDIT_INTERNAL_ENABLED", False)

    def fail_constructor(*args, **kwargs):
        raise AssertionError("provider must not be constructed while disabled")

    monkeypatch.setattr("app.api.analysis.OpenAIListingAuditProvider", fail_constructor)
    response = client.post(
        PATH,
        json=_payload(),
        headers=auth_and_idempotency(tenant["user"]),
    )

    assert response.status_code == 404
    assert response.json()["error_code"] == "ANALYSIS_INTERNAL_DISABLED"


def test_unauthenticated_request_is_rejected_before_provider(client, monkeypatch) -> None:
    monkeypatch.setattr(settings, "LISTING_AUDIT_INTERNAL_ENABLED", True)

    def fail_constructor(*args, **kwargs):
        raise AssertionError("provider must not be constructed before authentication")

    monkeypatch.setattr("app.api.analysis.OpenAIListingAuditProvider", fail_constructor)
    response = client.post(
        PATH,
        json=_payload(),
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    assert response.status_code == 401


def test_missing_csrf_is_rejected_before_provider(
    client, tenant_bundle, auth_and_idempotency, monkeypatch
) -> None:
    tenant = tenant_bundle("audit-csrf")
    monkeypatch.setattr(settings, "LISTING_AUDIT_INTERNAL_ENABLED", True)

    def fail_constructor(*args, **kwargs):
        raise AssertionError("provider must not be constructed before CSRF validation")

    monkeypatch.setattr("app.api.analysis.OpenAIListingAuditProvider", fail_constructor)
    headers = auth_and_idempotency(tenant["user"])
    headers.pop("X-CSRF-Token")
    response = client.post(PATH, json=_payload(), headers=headers)

    assert response.status_code == 403
    assert response.json()["error_code"] == "AUTH_CSRF_INVALID"


def test_internal_flag_defaults_off_and_release_examples_keep_it_off() -> None:
    assert type(settings).model_fields["LISTING_AUDIT_INTERNAL_ENABLED"].default is False

    with open(".env.example", encoding="utf-8") as env_file:
        backend_example = env_file.read()
    with open("../.env.rc.example", encoding="utf-8") as env_file:
        rc_example = env_file.read()
    with open("../docker-compose.rc.yml", encoding="utf-8") as compose_file:
        compose = compose_file.read()

    assert "LISTING_AUDIT_INTERNAL_ENABLED=false" in backend_example
    assert "LISTING_AUDIT_INTERNAL_ENABLED=false" in rc_example
    assert "${LISTING_AUDIT_INTERNAL_ENABLED:-false}" in compose


def test_success_and_replay_call_provider_and_charge_once(
    client,
    db_session,
    tenant_bundle,
    auth_and_idempotency,
    internal_enabled,
    monkeypatch,
) -> None:
    tenant = tenant_bundle("audit-replay")
    calls = 0

    async def fake_audit(self, prompt, *, request_id):
        nonlocal calls
        calls += 1
        return ListingAuditProviderResponse(
            output=valid_output(),
            model="synthetic-model-v1",
            input_tokens=120,
            output_tokens=80,
        )

    monkeypatch.setattr(OpenAIListingAuditProvider, "audit", fake_audit)
    key = str(uuid.uuid4())
    headers = auth_and_idempotency(tenant["user"], key)

    first = client.post(PATH, json=_payload(), headers=headers)
    second = client.post(PATH, json=_payload(), headers=headers)

    assert first.status_code == second.status_code == 200
    assert first.json()["data"] == second.json()["data"]
    assert first.json()["data"]["overall_score"] == 45
    assert "tokens_used" not in first.json()["data"]
    assert calls == 1

    record = db_session.query(GenerationRequest).filter_by(idempotency_key=key).one()
    assert record.request_type == "listing_audit"
    assert record.status == GenerationRequestStatus.SUCCEEDED
    assert record.input_tokens == 120
    assert record.output_tokens == 80
    assert record.tokens_used == 200
    db_session.refresh(tenant["user"])
    assert tenant["user"].used_tokens == 200
    assert tenant["user"].reserved_tokens == 0
    usage = db_session.query(AuditUsage).filter_by(user_id=tenant["user"].id).one()
    assert usage.status == "completed"
    assert usage.generation_id == record.generation_id


def test_idempotency_key_reuse_with_different_input_conflicts(
    client,
    tenant_bundle,
    auth_and_idempotency,
    internal_enabled,
    monkeypatch,
) -> None:
    tenant = tenant_bundle("audit-conflict")

    async def fake_audit(self, prompt, *, request_id):
        return ListingAuditProviderResponse(
            output=valid_output(), model="synthetic-model-v1", input_tokens=1, output_tokens=1
        )

    monkeypatch.setattr(OpenAIListingAuditProvider, "audit", fake_audit)
    key = str(uuid.uuid4())
    headers = auth_and_idempotency(tenant["user"], key)
    assert client.post(PATH, json=_payload(), headers=headers).status_code == 200

    conflict = client.post(PATH, json=_payload(description="Changed"), headers=headers)
    assert conflict.status_code == 409
    assert conflict.json()["error_code"] == "IDEMPOTENCY_CONFLICT"


def test_provider_failure_releases_reservation_without_charging(
    client,
    db_session,
    tenant_bundle,
    auth_and_idempotency,
    internal_enabled,
    monkeypatch,
) -> None:
    tenant = tenant_bundle("audit-failure")

    async def fake_audit(self, prompt, *, request_id):
        raise AppException(
            message="AI generation failed",
            code=502,
            detail="The AI service is temporarily unavailable.",
            error_code=AI_PROVIDER_UNAVAILABLE,
        )

    monkeypatch.setattr(OpenAIListingAuditProvider, "audit", fake_audit)
    key = str(uuid.uuid4())
    response = client.post(
        PATH,
        json=_payload(),
        headers=auth_and_idempotency(tenant["user"], key),
    )

    assert response.status_code == 502
    assert response.json()["error_code"] == AI_PROVIDER_UNAVAILABLE
    record = db_session.query(GenerationRequest).filter_by(idempotency_key=key).one()
    assert record.status == GenerationRequestStatus.FAILED
    assert record.tokens_used == 0
    db_session.refresh(tenant["user"])
    assert tenant["user"].used_tokens == 0
    assert tenant["user"].reserved_tokens == 0
    usage = db_session.query(AuditUsage).filter_by(user_id=tenant["user"].id).one()
    assert usage.status == "released"
    assert usage.generation_id is None


def test_listing_audit_quota_reservation_covers_prompt_and_output_budget() -> None:
    reserve = estimate_reserve_tokens("listing_audit", _payload())
    assert reserve > 3000
