from app.schemas.ai_output import ListingAIOutput
from app.services.openai import OpenAIService
from tests.fixtures.ai_outputs import (
    VALID_ANALYZE_OUTPUT,
    VALID_KEYWORDS_OUTPUT,
    VALID_LISTING_OUTPUT,
)


def test_listing_fixture_matches_frontend_listing_result_shape():
    payload = {**VALID_LISTING_OUTPUT, "tokens_used": 100, "product_id": "uuid", "score": None}
    required = {"title", "bullets", "description", "keywords", "tokens_used"}
    assert required.issubset(payload.keys())
    assert isinstance(payload["bullets"], list)
    assert isinstance(payload["keywords"], list)


def test_analyze_fixture_matches_frontend_analyze_result_shape():
    payload = {**VALID_ANALYZE_OUTPUT, "tokens_used": 50}
    required = {"strengths", "weaknesses", "opportunities", "tokens_used"}
    assert required.issubset(payload.keys())


def test_keywords_fixture_matches_api_response_shape():
    payload = {**VALID_KEYWORDS_OUTPUT, "tokens_used": 40}
    required = {"keywords", "primary_keyword", "search_intent", "tokens_used"}
    assert required.issubset(payload.keys())
    assert len(payload["keywords"]) == 15


def test_prompt_aligned_listing_fixture_passes_service_validation():
    service = OpenAIService()
    validated = service._validate_ai_payload(
        VALID_LISTING_OUTPUT,
        ListingAIOutput,
        "ListingAIOutput",
        model="test-model",
        request_id="contract-listing",
    )
    assert validated["title"]
    assert len(validated["keywords"]) == 10
