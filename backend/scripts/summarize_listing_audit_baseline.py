#!/usr/bin/env python3
"""Summarize a completed two-reviewer Listing Audit baseline run."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.analysis.eval_summary import parse_human_scores, summarize_human_scores


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    scores_by_case = {}
    for path in sorted(args.run_dir.glob("LA-*.json")):
        artifact = json.loads(path.read_text(encoding="utf-8"))
        case_id = artifact.get("case_id")
        if not isinstance(case_id, str):
            raise ValueError(f"{path}: missing case_id")
        prompt_version = artifact.get("prompt_version")
        response_model_id = artifact.get("response_model_id")
        if not isinstance(prompt_version, str) or not isinstance(response_model_id, str):
            raise ValueError(f"{path}: missing run metadata")
        scores_by_case[case_id] = parse_human_scores(
            artifact.get("human_scores", []),
            expected_prompt_version=prompt_version,
            expected_model=response_model_id,
        )

    summary = summarize_human_scores(scores_by_case)
    rendered = json.dumps(summary, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0 if summary["gate_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
