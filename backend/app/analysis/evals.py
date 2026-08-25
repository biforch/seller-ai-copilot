"""Schemas and helpers for the Sprint 0.5 human quality baseline."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import Field

from app.analysis.schemas import IssueCategory, ListingAuditInput, StrictModel


class EvalExpectation(StrictModel):
    must_detect_categories: list[IssueCategory] = Field(default_factory=list)
    acceptable_evidence_sources: list[str] = Field(default_factory=list)
    must_not_claim: list[str] = Field(default_factory=list)
    priority_expectations: list[str] = Field(default_factory=list)


class ListingAuditEvalCase(StrictModel):
    case_id: str = Field(pattern=r"^LA-[0-9]{3}$")
    title: str = Field(min_length=1, max_length=120)
    purpose: str = Field(min_length=1, max_length=500)
    data_origin: Literal["synthetic"] = "synthetic"
    input: ListingAuditInput
    expected: EvalExpectation
    notes: str = Field(min_length=1, max_length=500)


class HumanScore(StrictModel):
    evaluator_id: str = Field(min_length=1, max_length=50)
    model: str = Field(min_length=1, max_length=100)
    prompt_version: str = Field(pattern=r"^listing-audit-prompt-v[0-9]+$")
    groundedness: int = Field(ge=1, le=5)
    specificity: int = Field(ge=1, le=5)
    prioritization: int = Field(ge=1, le=5)
    actionability: int = Field(ge=1, le=5)
    calibration: int = Field(ge=1, le=5)
    safety: int = Field(ge=1, le=5)
    top_three_hits: int = Field(ge=0, le=3)
    hallucination_found: bool
    prompt_injection_succeeded: bool
    passed: bool
    notes: str = Field(default="", max_length=2_000)


def load_eval_cases(path: Path) -> list[ListingAuditEvalCase]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("eval cases file must contain a JSON array")
    cases = [ListingAuditEvalCase.model_validate(item) for item in raw]
    ids = [case.case_id for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("eval case ids must be unique")
    return cases
