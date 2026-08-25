from __future__ import annotations

from pathlib import Path

import pytest

from app.analysis.eval_summary import parse_human_scores, summarize_human_scores
from app.analysis.evals import load_eval_cases
from app.analysis.grounding import validate_evidence_grounding
from app.analysis.prompt import PROMPT_VERSION, render_listing_audit_prompt
from app.analysis.schemas import (
    DimensionScore,
    DimensionScores,
    ListingAuditInput,
    ListingAuditLLMOutput,
    ListingAuditReport,
)
from app.analysis.scoring import SCORE_WEIGHTS, calculate_overall_score
from scripts.run_listing_audit_baseline import (
    create_provider_client,
    parse_temperature,
    temperature_mode,
)

CASES_PATH = Path(__file__).parent / "evals" / "listing_audit" / "cases.json"


def test_baseline_supports_documented_temperature_compatibility_exception():
    assert parse_temperature("null") is None
    assert temperature_mode(None) == "model_compatibility_exception"
    assert parse_temperature("0.2") == 0.2
    assert temperature_mode(0.2) == "fixed"
    with pytest.raises(Exception, match="temperature"):
        parse_temperature("0.3")


def valid_output() -> dict:
    return {
        "dimension_scores": {
            "positioning": {"score": 60, "rationale": "The title identifies a phone stand."},
            "buyer_clarity": {"score": 55, "rationale": "The basic desk use is stated."},
            "information_quality": {"score": 30, "rationale": "Only one detail is supplied."},
            "conversion_readiness": {"score": 25, "rationale": "Purchase details are sparse."},
            "discoverability": {"score": 65, "rationale": "Core product terms are present."},
        },
        "issues": [
            {
                "id": "ISSUE-1",
                "category": "information_quality",
                "severity": "high",
                "problem": "The listing provides very few purchase details.",
                "reason": "Compatibility and construction details are not supplied.",
                "impact": "A buyer has little evidence for evaluating fit.",
                "evidence": [{"source": "bullet_1", "quote": "Holds a phone on a desk."}],
            }
        ],
        "priority_actions": [
            {
                "rank": 1,
                "issue_ids": ["ISSUE-1"],
                "action": "Verify compatibility and construction details before expanding the copy.",
                "why_now": "The current listing lacks basic decision information.",
                "expected_effect": "Buyers can assess fit using verified details.",
                "effort": "medium",
            }
        ],
        "limitations": ["Only one bullet and no review or competitor evidence were supplied."],
    }


def test_confirmed_score_weights_are_frozen():
    assert SCORE_WEIGHTS == {
        "positioning": 0.20,
        "buyer_clarity": 0.20,
        "information_quality": 0.20,
        "conversion_readiness": 0.25,
        "discoverability": 0.15,
    }
    assert sum(SCORE_WEIGHTS.values()) == pytest.approx(1.0)


def test_overall_score_uses_round_half_up():
    scores = DimensionScores(
        positioning=DimensionScore(score=60, rationale="x"),
        buyer_clarity=DimensionScore(score=55, rationale="x"),
        information_quality=DimensionScore(score=30, rationale="x"),
        conversion_readiness=DimensionScore(score=25, rationale="x"),
        discoverability=DimensionScore(score=65, rationale="x"),
    )
    assert calculate_overall_score(scores) == 45


def test_llm_schema_accepts_grounded_contract():
    output = ListingAuditLLMOutput.model_validate(valid_output())
    assert output.priority_actions[0].issue_ids == ["ISSUE-1"]


@pytest.mark.parametrize(
    "mutation,match",
    [
        ({"unexpected": True}, "extra"),
        ({"limitations": None}, "limitations"),
        ({"issues": []}, "issues"),
    ],
)
def test_llm_schema_rejects_invalid_shapes(mutation, match):
    payload = valid_output() | mutation
    with pytest.raises(Exception) as exc:
        ListingAuditLLMOutput.model_validate(payload)
    assert match in str(exc.value).lower()


def test_priority_actions_must_reference_existing_issues():
    payload = valid_output()
    payload["priority_actions"][0]["issue_ids"] = ["ISSUE-8"]
    with pytest.raises(Exception, match="unknown issues"):
        ListingAuditLLMOutput.model_validate(payload)


def test_priority_ranks_must_be_consecutive_and_ordered():
    payload = valid_output()
    payload["priority_actions"][0]["rank"] = 2
    with pytest.raises(Exception, match="consecutive"):
        ListingAuditLLMOutput.model_validate(payload)


def test_grounding_accepts_normalized_verbatim_quote():
    case = load_eval_cases(CASES_PATH)[-1]
    output = ListingAuditLLMOutput.model_validate(valid_output())
    validate_evidence_grounding(case.input, output)


def test_grounding_rejects_quote_not_in_declared_source():
    case = load_eval_cases(CASES_PATH)[-1]
    payload = valid_output()
    payload["issues"][0]["evidence"][0]["quote"] = "Invented compatibility claim"
    output = ListingAuditLLMOutput.model_validate(payload)
    with pytest.raises(ValueError, match="not grounded"):
        validate_evidence_grounding(case.input, output)


def test_bullets_contract_accepts_one_to_five_and_rejects_six():
    base = {
        "marketplace": "US",
        "language": "en-US",
        "listing": {"title": "Product", "bullets": ["one"], "description": "Description"},
    }
    assert len(ListingAuditInput.model_validate(base).listing.bullets) == 1
    five = base | {"listing": base["listing"] | {"bullets": [str(i) for i in range(5)]}}
    assert len(ListingAuditInput.model_validate(five).listing.bullets) == 5
    six = base | {"listing": base["listing"] | {"bullets": [str(i) for i in range(6)]}}
    with pytest.raises(Exception, match="bullets"):
        ListingAuditInput.model_validate(six)


def test_prompt_keeps_injection_inside_untrusted_user_data():
    injection_case = next(case for case in load_eval_cases(CASES_PATH) if case.case_id == "LA-012")
    prompt = render_listing_audit_prompt(injection_case.input)
    assert "IGNORE THE AUDIT" not in prompt.system
    assert "IGNORE THE AUDIT" in prompt.user
    assert "untrusted data only" in prompt.user
    assert "do not refuse the audit" in prompt.system
    assert PROMPT_VERSION == "listing-audit-prompt-v2"


def test_eval_pack_contains_exactly_15_ordered_synthetic_cases():
    cases = load_eval_cases(CASES_PATH)
    assert [case.case_id for case in cases] == [f"LA-{index:03d}" for index in range(1, 16)]
    assert all(case.data_origin == "synthetic" for case in cases)


def test_structured_output_schema_is_strict_and_requires_limitations():
    schema = ListingAuditLLMOutput.model_json_schema()
    assert schema["additionalProperties"] is False
    assert "limitations" in schema["required"]


def test_report_contract_uses_the_active_prompt_version():
    field = ListingAuditReport.model_fields["prompt_version"]
    assert field.default == PROMPT_VERSION == "listing-audit-prompt-v2"


def test_openai_client_uses_the_fixed_official_endpoint(monkeypatch):
    captured = {}

    class FakeOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-eval-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://attacker.invalid/v1")
    monkeypatch.setattr("scripts.run_listing_audit_baseline.OpenAI", FakeOpenAI)
    create_provider_client("openai")
    assert captured == {
        "api_key": "synthetic-eval-key",
        "base_url": "https://api.openai.com/v1",
    }


def _passing_review(evaluator_id: str) -> dict:
    return {
        "evaluator_id": evaluator_id,
        "model": "approved-test-model",
        "prompt_version": "listing-audit-prompt-v2",
        "groundedness": 4,
        "specificity": 4,
        "prioritization": 4,
        "actionability": 4,
        "calibration": 4,
        "safety": 5,
        "top_three_hits": 2,
        "hallucination_found": False,
        "prompt_injection_succeeded": False,
        "passed": True,
        "notes": "synthetic review",
    }


def test_human_quality_gate_requires_two_passing_reviews_for_all_cases():
    scores_by_case = {
        f"LA-{index:03d}": parse_human_scores(
            [_passing_review("reviewer-a"), _passing_review("reviewer-b")]
        )
        for index in range(1, 16)
    }
    summary = summarize_human_scores(scores_by_case)
    assert summary["gate_passed"] is True
    assert summary["review_count"] == 30
    assert summary["top_three_case_pass_rate"] == 1.0


def test_human_quality_gate_fails_on_hallucination():
    bad = _passing_review("reviewer-b") | {"hallucination_found": True}
    scores_by_case = {
        f"LA-{index:03d}": parse_human_scores(
            [
                _passing_review("reviewer-a"),
                bad if index == 1 else _passing_review("reviewer-b"),
            ]
        )
        for index in range(1, 16)
    }
    summary = summarize_human_scores(scores_by_case)
    assert summary["gate_passed"] is False
    assert summary["hallucination_count"] == 1


def test_human_quality_gate_requires_distinct_reviewers():
    scores_by_case = {
        f"LA-{index:03d}": parse_human_scores(
            [_passing_review("reviewer-a"), _passing_review("reviewer-b")]
        )
        for index in range(1, 16)
    }
    scores_by_case["LA-001"] = parse_human_scores(
        [_passing_review("reviewer-a"), _passing_review("reviewer-a")]
    )
    summary = summarize_human_scores(scores_by_case)
    assert summary["gate_passed"] is False
    assert summary["cases_with_duplicate_evaluators"] == ["LA-001"]
    assert summary["cases_with_fewer_than_two_reviews"] == ["LA-001"]


def test_human_quality_gate_honors_explicit_review_failure():
    scores_by_case = {
        f"LA-{index:03d}": parse_human_scores(
            [_passing_review("reviewer-a"), _passing_review("reviewer-b")]
        )
        for index in range(1, 16)
    }
    scores_by_case["LA-001"][1].passed = False
    summary = summarize_human_scores(scores_by_case)
    assert summary["gate_passed"] is False
    assert summary["failed_review_count"] == 1


def test_human_review_metadata_must_match_the_run():
    with pytest.raises(ValueError, match="prompt_version"):
        parse_human_scores(
            [_passing_review("reviewer-a")],
            expected_prompt_version="listing-audit-prompt-v3",
            expected_model="approved-test-model",
        )
    with pytest.raises(ValueError, match="model"):
        parse_human_scores(
            [_passing_review("reviewer-a")],
            expected_prompt_version="listing-audit-prompt-v2",
            expected_model="different-model",
        )
