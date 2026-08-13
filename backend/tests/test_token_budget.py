"""Token budget and quota estimation alignment tests."""

from __future__ import annotations

from app.prompts.token_budget import MAX_OUTPUT_TOKENS, estimate_reserve_tokens
from app.prompts.versions import PROMPT_VERSIONS
from app.services.openai import OpenAIService
from app.services.quota_estimation import estimate_reserve_tokens as service_estimate


def test_max_output_tokens_match_openai_service_defaults():
    assert MAX_OUTPUT_TOKENS["listing"] == 2000
    assert MAX_OUTPUT_TOKENS["analysis"] == 1000
    assert MAX_OUTPUT_TOKENS["keywords"] == 800


def test_prompt_versions_cover_all_request_types():
    for request_type in MAX_OUTPUT_TOKENS:
        assert request_type in PROMPT_VERSIONS


def test_listing_reserve_includes_rendered_prompt_budget():
    short = service_estimate(
        "listing",
        {
            "name": "A",
            "category": "Electronics",
            "market": "USA",
            "platform": "Amazon",
        },
    )
    long_name = "A" * 4000
    long_input = service_estimate(
        "listing",
        {
            "name": long_name,
            "category": "Electronics",
            "market": "USA",
            "platform": "Amazon",
        },
    )
    assert long_input > short


def test_analysis_and_keywords_use_distinct_output_caps():
    analysis = service_estimate(
        "analysis",
        {"title": "T", "reviews": 10, "rating": 4.5, "description": "D"},
    )
    keywords = service_estimate(
        "keywords",
        {"name": "T", "category": "C", "market": "USA"},
    )
    assert analysis > keywords or analysis != keywords
    assert MAX_OUTPUT_TOKENS["analysis"] > MAX_OUTPUT_TOKENS["keywords"]


def test_rendered_estimate_uses_token_budget_module():
    variables = {
        "product_name": "Widget",
        "category": "Home",
        "market": "USA",
        "platform": "Amazon",
        "project_goal": None,
        "target_customer": None,
        "advantages": [],
    }
    direct = estimate_reserve_tokens("listing", variables)
    via_service = service_estimate(
        "listing",
        {
            "name": "Widget",
            "category": "Home",
            "market": "USA",
            "platform": "Amazon",
        },
    )
    assert direct == via_service


def test_openai_service_listing_uses_shared_max_output(monkeypatch):
    captured: dict[str, int] = {}

    async def fake_chat_json(self, _system, _user, _schema, _name, max_tokens=2000, request_id=None):
        captured["max_tokens"] = max_tokens
        return {"tokens_used": 0}

    monkeypatch.setattr(OpenAIService, "_chat_json", fake_chat_json)

    import asyncio

    service = OpenAIService()
    asyncio.run(
        service.generate_listing(
            product_name="X",
            category="Y",
            market="USA",
            platform="Amazon",
        )
    )
    assert captured["max_tokens"] == MAX_OUTPUT_TOKENS["listing"]
