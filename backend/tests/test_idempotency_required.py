import uuid

import pytest

from app.services.openai import OpenAIService
from tests.fixtures.ai_outputs import VALID_LISTING_OUTPUT


def test_missing_idempotency_key_returns_422(client, tenant_bundle, auth_header, valid_listing_payload):
    tenant = tenant_bundle("missing-idem")
    response = client.post(
        "/api/v1/generate/listing",
        headers=auth_header(tenant["user"]),
        json=valid_listing_payload(tenant["project"].id),
    )
    assert response.status_code == 422


def test_invalid_idempotency_key_returns_422(
    client, tenant_bundle, auth_header, valid_listing_payload
):
    tenant = tenant_bundle("invalid-idem")
    response = client.post(
        "/api/v1/generate/listing",
        headers={**auth_header(tenant["user"]), "Idempotency-Key": "not-a-valid-uuid"},
        json=valid_listing_payload(tenant["project"].id),
    )
    assert response.status_code == 422


def test_oversized_idempotency_key_returns_422(
    client, tenant_bundle, auth_header, valid_listing_payload
):
    tenant = tenant_bundle("long-idem")
    response = client.post(
        "/api/v1/generate/listing",
        headers={
            **auth_header(tenant["user"]),
            "Idempotency-Key": "a" * 37,
        },
        json=valid_listing_payload(tenant["project"].id),
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_valid_uuid_idempotency_key_accepted(
    client, tenant_bundle, auth_and_idempotency, valid_listing_payload, monkeypatch
):
    tenant = tenant_bundle("valid-idem")

    async def fake_generate_listing(self, **kwargs):
        result = dict(VALID_LISTING_OUTPUT)
        result["tokens_used"] = 12
        return result

    monkeypatch.setattr(OpenAIService, "generate_listing", fake_generate_listing)

    response = client.post(
        "/api/v1/generate/listing",
        headers=auth_and_idempotency(tenant["user"], str(uuid.uuid4())),
        json=valid_listing_payload(tenant["project"].id),
    )
    assert response.status_code == 200
