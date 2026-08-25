#!/usr/bin/env python3
"""Audit a completed Listing Audit baseline and prepare human review records."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from app.analysis.evals import load_eval_cases
from app.analysis.grounding import validate_evidence_grounding
from app.analysis.schemas import ListingAuditLLMOutput
from app.analysis.scoring import calculate_overall_score

RUN_METADATA_KEYS = (
    "provider",
    "requested_model_id",
    "temperature",
    "temperature_mode",
    "prompt_version",
    "schema_version",
    "eval_dataset_version",
    "eval_cases_sha256",
)


def write_json(path: Path, payload: object) -> None:
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--cases", type=Path, required=True)
    args = parser.parse_args()

    manifest = json.loads((args.run_dir / "manifest.json").read_text(encoding="utf-8"))
    cases = load_eval_cases(args.cases)
    actual_digest = hashlib.sha256(args.cases.read_bytes()).hexdigest()
    failure_files = sorted(path.name for path in args.run_dir.glob("*.failure.json"))
    rows = []

    for case in cases:
        path = args.run_dir / f"{case.case_id}.json"
        artifact = json.loads(path.read_text(encoding="utf-8"))
        output = ListingAuditLLMOutput.model_validate(artifact["output"])
        validate_evidence_grounding(case.input, output)
        categories = {issue.category.value for issue in output.issues}
        expected_categories = {category.value for category in case.expected.must_detect_categories}
        used_sources = {
            evidence.source.value for issue in output.issues for evidence in issue.evidence
        }
        expected_sources = set(case.expected.acceptable_evidence_sources)
        rows.append(
            {
                "case_id": case.case_id,
                "title": case.title,
                "overall_score": artifact["overall_score"],
                "issue_count": len(output.issues),
                "priority_action_count": len(output.priority_actions),
                "limitation_count": len(output.limitations),
                "schema_valid": True,
                "grounding_valid": True,
                "deterministic_score_valid": artifact["overall_score"]
                == calculate_overall_score(output.dimension_scores),
                "metadata_valid": all(
                    artifact.get(key) == manifest.get(key) for key in RUN_METADATA_KEYS
                ),
                "expected_categories": sorted(expected_categories),
                "observed_categories": sorted(categories),
                "missing_expected_categories": sorted(expected_categories - categories),
                "additional_grounded_sources": sorted(used_sources - expected_sources),
                "priority_expectations": case.expected.priority_expectations,
                "manual_claim_review_terms": case.expected.must_not_claim,
            }
        )

    structural_gate = (
        manifest.get("case_count") == len(cases) == 15
        and manifest.get("eval_cases_sha256") == actual_digest
        and not failure_files
        and all(
            row["schema_valid"]
            and row["grounding_valid"]
            and row["deterministic_score_valid"]
            and row["metadata_valid"]
            for row in rows
        )
    )
    category_passes = sum(not row["missing_expected_categories"] for row in rows)
    audit = {
        "structural_gate_passed": structural_gate,
        "quality_gate_status": "pending_two_independent_human_reviews",
        "case_count": len(rows),
        "failure_artifact_count": len(failure_files),
        "schema_valid_count": sum(row["schema_valid"] for row in rows),
        "grounding_valid_count": sum(row["grounding_valid"] for row in rows),
        "metadata_valid_count": sum(row["metadata_valid"] for row in rows),
        "deterministic_score_valid_count": sum(
            row["deterministic_score_valid"] for row in rows
        ),
        "expected_category_exact_case_count": category_passes,
        "expected_category_exact_case_rate": round(category_passes / len(rows), 4),
        "score_min": min(row["overall_score"] for row in rows),
        "score_max": max(row["overall_score"] for row in rows),
        "score_mean": round(sum(row["overall_score"] for row in rows) / len(rows), 2),
        "notes": [
            "Additional grounded sources are informational fixture-scope differences, not grounding failures.",
            "Forbidden-claim meaning and priority expectation coverage require human judgment.",
            "This provider-neutral baseline is not a production provider or model approval.",
        ],
        "cases": rows,
    }
    review_packet = {
        "run_metadata": {key: manifest.get(key) for key in RUN_METADATA_KEYS},
        "instructions": {
            "reviewers_required": 2,
            "independent_review": True,
            "score_range": "1-5",
            "dimensions": [
                "groundedness",
                "specificity",
                "prioritization",
                "actionability",
                "calibration",
                "safety",
            ],
            "review_source": "Open each corresponding LA-NNN.json artifact and compare it with cases.json.",
        },
        "cases": [
            {
                "case_id": row["case_id"],
                "title": row["title"],
                "overall_score": row["overall_score"],
                "expected_categories": row["expected_categories"],
                "observed_categories": row["observed_categories"],
                "missing_expected_categories": row["missing_expected_categories"],
                "priority_expectations": row["priority_expectations"],
                "manual_claim_review_terms": row["manual_claim_review_terms"],
                "review_status": "pending_two_independent_reviews",
            }
            for row in rows
        ],
    }
    write_json(args.run_dir / "automated-audit.json", audit)
    write_json(args.run_dir / "human-review-packet.json", review_packet)
    print(json.dumps(audit, ensure_ascii=False, indent=2))
    return 0 if structural_gate else 1


if __name__ == "__main__":
    sys.exit(main())
