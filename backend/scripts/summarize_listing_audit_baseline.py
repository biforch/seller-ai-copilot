#!/usr/bin/env python3
"""Summarize a completed two-reviewer Listing Audit baseline run."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.analysis.eval_summary import parse_human_scores, summarize_human_scores
from app.analysis.evals import HumanScore

EXPECTED_CASE_IDS = {f"LA-{index:03d}" for index in range(1, 16)}


def load_scorecards(
    paths: list[Path], *, expected_model: str, expected_prompt_version: str
) -> dict[str, list[HumanScore]]:
    scores_by_case: dict[str, list[HumanScore]] = {}
    evaluator_ids: set[str] = set()
    for path in paths:
        raw = json.loads(path.read_text(encoding="utf-8"))
        evaluator_id = raw.get("evaluator_id")
        if not isinstance(evaluator_id, str) or not evaluator_id:
            raise ValueError(f"{path}: invalid evaluator_id")
        if evaluator_id in evaluator_ids:
            raise ValueError(f"{path}: duplicate evaluator_id")
        evaluator_ids.add(evaluator_id)
        if raw.get("model") != expected_model or raw.get(
            "prompt_version"
        ) != expected_prompt_version:
            raise ValueError(f"{path}: scorecard metadata does not match the run")
        cases = raw.get("cases")
        if not isinstance(cases, list):
            raise ValueError(f"{path}: cases must be a list")
        seen: set[str] = set()
        for case in cases:
            if not isinstance(case, dict) or not isinstance(case.get("case_id"), str):
                raise ValueError(f"{path}: invalid case record")
            case_id = case["case_id"]
            if case_id in seen:
                raise ValueError(f"{path}: duplicate case_id {case_id}")
            seen.add(case_id)
            payload = {
                "evaluator_id": evaluator_id,
                "model": expected_model,
                "prompt_version": expected_prompt_version,
                **{
                    key: case.get(key)
                    for key in (
                        "groundedness",
                        "specificity",
                        "prioritization",
                        "actionability",
                        "calibration",
                        "safety",
                        "top_three_hits",
                        "hallucination_found",
                        "prompt_injection_succeeded",
                        "passed",
                        "notes",
                    )
                },
            }
            scores_by_case.setdefault(case_id, []).append(HumanScore.model_validate(payload))
        if seen != EXPECTED_CASE_IDS:
            raise ValueError(f"{path}: scorecard must contain exactly LA-001 through LA-015")
    return scores_by_case


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--scorecard", action="append", type=Path, default=[])
    args = parser.parse_args()

    artifacts = sorted(args.run_dir.glob("LA-[0-9][0-9][0-9].json"))
    if len(artifacts) != 15:
        raise ValueError("run directory must contain exactly 15 successful case artifacts")
    metadata = []
    for path in artifacts:
        artifact = json.loads(path.read_text(encoding="utf-8"))
        prompt_version = artifact.get("prompt_version")
        response_model_id = artifact.get("response_model_id")
        if not isinstance(prompt_version, str) or not isinstance(response_model_id, str):
            raise ValueError(f"{path}: missing run metadata")
        metadata.append((response_model_id, prompt_version))
    if len(set(metadata)) != 1:
        raise ValueError("run artifacts do not share one model and prompt version")
    expected_model, expected_prompt_version = metadata[0]

    if args.scorecard:
        scores_by_case = load_scorecards(
            args.scorecard,
            expected_model=expected_model,
            expected_prompt_version=expected_prompt_version,
        )
    else:
        scores_by_case = {}
        for path in artifacts:
            artifact = json.loads(path.read_text(encoding="utf-8"))
            case_id = artifact.get("case_id")
            if not isinstance(case_id, str):
                raise ValueError(f"{path}: missing case_id")
            scores_by_case[case_id] = parse_human_scores(
                artifact.get("human_scores", []),
                expected_prompt_version=expected_prompt_version,
                expected_model=expected_model,
            )

    summary = summarize_human_scores(scores_by_case)
    rendered = json.dumps(summary, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0 if summary["gate_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
