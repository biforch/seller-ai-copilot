import pytest

from app.core.exceptions import AI_RESPONSE_INVALID
from app.models.generation import Generation
from app.schemas.ai_output import AnalyzeAIOutput, KeywordsAIOutput, ListingAIOutput
from app.services.openai import OpenAIService
from tests.fixtures.ai_outputs import (
    VALID_ANALYZE_OUTPUT,
    VALID_KEYWORDS_OUTPUT,
    VALID_LISTING_OUTPUT,
)


def test_listing_schema_accepts_valid_fixture():
    parsed = ListingAIOutput.model_validate(VALID_LISTING_OUTPUT)
    assert len(parsed.bullets) == 5
    assert len(parsed.keywords) == 10


@pytest.mark.parametrize(
    "payload,match",
    [
        ({}, "title"),
        (VALID_LISTING_OUTPUT | {"title": ""}, "title"),
        (VALID_LISTING_OUTPUT | {"title": "x" * 231}, "title"),
        (VALID_LISTING_OUTPUT | {"bullets": VALID_LISTING_OUTPUT["bullets"][:3]}, "bullets"),
        (VALID_LISTING_OUTPUT | {"keywords": []}, "keywords"),
        (VALID_LISTING_OUTPUT | {"unexpected": "field"}, "extra"),
    ],
)
def test_listing_schema_rejects_invalid_payload(payload, match):
    with pytest.raises(Exception) as exc:
        ListingAIOutput.model_validate(payload)
    assert match in str(exc.value).lower()


def test_openai_service_maps_validation_errors_to_502():
    service = OpenAIService()
    with pytest.raises(Exception) as exc:
        service._validate_ai_payload(
            {"title": "only title"},
            ListingAIOutput,
            "ListingAIOutput",
            model="test-model",
            request_id="req-123",
        )
    error = exc.value
    assert error.code == 502
    assert error.error_code == AI_RESPONSE_INVALID
    assert "only title" not in str(error.message)


def test_user_input_validation_returns_422_not_ai_error(
    client, tenant_bundle, auth_and_idempotency, valid_listing_payload
):
    tenant = tenant_bundle("input-422")
    response = client.post(
        "/api/v1/generate/listing",
        headers=auth_and_idempotency(tenant["user"]),
        json=valid_listing_payload(tenant["project"].id, name="   "),
    )
    assert response.status_code == 422
    body = response.json()
    assert body["message"] == "Validation Error"
    assert body.get("error_code") != AI_RESPONSE_INVALID


@pytest.mark.asyncio
async def test_invalid_llm_json_returns_502_and_skips_generation(
    client,
    tenant_bundle,
    auth_and_idempotency,
    valid_listing_payload,
    db_session,
    monkeypatch,
):
    owner = tenant_bundle("ai-invalid-json")

    async def broken_listing(self, **kwargs):
        from app.core.exceptions import ai_response_invalid_exception

        raise ai_response_invalid_exception()

    monkeypatch.setattr(OpenAIService, "generate_listing", broken_listing)

    before = db_session.query(Generation).count()
    response = client.post(
        "/api/v1/generate/listing",
        headers=auth_and_idempotency(owner["user"]),
        json=valid_listing_payload(owner["project"].id),
    )
    assert response.status_code == 502
    body = response.json()
    assert body["code"] == 502
    assert body["error_code"] == AI_RESPONSE_INVALID
    assert body.get("detail") in (None, "")
    assert db_session.query(Generation).count() == before


@pytest.mark.asyncio
async def test_invalid_llm_field_shape_returns_502(
    client,
    tenant_bundle,
    auth_and_idempotency,
    valid_listing_payload,
    db_session,
    monkeypatch,
):
    owner = tenant_bundle("ai-invalid-fields")

    async def broken_listing(self, **kwargs):
        service = OpenAIService()
        return service._validate_ai_payload(
            VALID_LISTING_OUTPUT | {"bullets": ["one"]},
            ListingAIOutput,
            "ListingAIOutput",
            model="test-model",
            request_id="req-field-error",
        )

    monkeypatch.setattr(OpenAIService, "generate_listing", broken_listing)

    before = db_session.query(Generation).count()
    response = client.post(
        "/api/v1/generate/listing",
        headers=auth_and_idempotency(owner["user"]),
        json=valid_listing_payload(owner["project"].id),
    )
    assert response.status_code == 502
    assert response.json()["error_code"] == AI_RESPONSE_INVALID
    assert db_session.query(Generation).count() == before


@pytest.mark.asyncio
async def test_valid_mocked_listing_saves_generation(
    client,
    tenant_bundle,
    auth_and_idempotency,
    valid_listing_payload,
    db_session,
    monkeypatch,
):
    owner = tenant_bundle("ai-valid")

    async def fake_generate_listing(self, **kwargs):
        result = dict(VALID_LISTING_OUTPUT)
        result["tokens_used"] = 120
        return result

    monkeypatch.setattr(OpenAIService, "generate_listing", fake_generate_listing)

    before = db_session.query(Generation).count()
    response = client.post(
        "/api/v1/generate/listing",
        headers=auth_and_idempotency(owner["user"]),
        json=valid_listing_payload(owner["project"].id),
    )
    assert response.status_code == 200
    assert db_session.query(Generation).count() == before + 1
    assert "score" in response.json()["data"]


def test_analyze_and_keywords_fixtures_match_schema():
    AnalyzeAIOutput.model_validate(VALID_ANALYZE_OUTPUT)
    KeywordsAIOutput.model_validate(VALID_KEYWORDS_OUTPUT)
