#!/usr/bin/env python3
"""Run or validate the Sprint 0.5 Listing Audit synthetic baseline.

This script never supports model or provider fallbacks and does not accept a
user-supplied base URL. It writes only synthetic eval outputs and non-sensitive
run metadata to the selected directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from openai import APIStatusError, OpenAI

from app.analysis.evals import load_eval_cases
from app.analysis.grounding import validate_evidence_grounding
from app.analysis.prompt import PROMPT_VERSION, render_listing_audit_prompt
from app.analysis.schemas import ListingAuditLLMOutput
from app.analysis.scoring import calculate_overall_score

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES = ROOT / "tests" / "evals" / "listing_audit" / "cases.json"
SCHEMA_VERSION = "listing-audit-schema-v1"
EVAL_DATASET_VERSION = "listing-audit-synthetic-v2"
OPENROUTER_ROUTING_DOCS = "https://openrouter.ai/docs/guides/routing/provider-selection"


def parse_temperature(value: str) -> float | None:
    if value.lower() == "null":
        return None
    temperature = float(value)
    if temperature not in (0.1, 0.2):
        raise argparse.ArgumentTypeError("temperature must be 0.1, 0.2, or null")
    return temperature


def temperature_mode(temperature: float | None) -> str:
    return "model_compatibility_exception" if temperature is None else "fixed"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--provider", choices=("openai", "openrouter"), default="openai")
    parser.add_argument("--model", help="Exact provider model ID; required online")
    parser.add_argument(
        "--temperature",
        type=parse_temperature,
        default=0.2,
        metavar="{0.1,0.2,null}",
        help="Sampling temperature, or null when the exact model does not support it",
    )
    parser.add_argument("--output-dir", type=Path)
    return parser.parse_args()


def validate_cases(path: Path) -> int:
    cases = load_eval_cases(path)
    expected_ids = [f"LA-{index:03d}" for index in range(1, 16)]
    actual_ids = [case.case_id for case in cases]
    if actual_ids != expected_ids:
        raise ValueError(f"expected ordered cases {expected_ids}, got {actual_ids}")
    print(f"validated {len(cases)} synthetic Listing Audit cases")
    return len(cases)


def structured_output_format() -> dict:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "listing_audit_llm_output_v1",
            "strict": True,
            "schema": ListingAuditLLMOutput.model_json_schema(),
        },
    }


def create_provider_client(provider: str) -> OpenAI:
    if provider == "openai":
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "OPENAI_API_KEY is not available to this process; "
                "configure it outside chat and do not pass it as a CLI argument"
            )
        return OpenAI(api_key=api_key, base_url="https://api.openai.com/v1")
    if provider == "openrouter":
        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            raise RuntimeError(
                "OPENROUTER_API_KEY is not available to this process; "
                "configure it outside chat and do not pass it as a CLI argument"
            )
        return OpenAI(api_key=api_key, base_url="https://openrouter.ai/api/v1")
    raise ValueError(f"unsupported provider: {provider}")


def provider_request_options(provider: str) -> dict:
    if provider == "openrouter":
        return {
            "provider": {
                "allow_fallbacks": False,
                "require_parameters": True,
                "data_collection": "deny",
                "zdr": True,
            }
        }
    return {}


def expected_run_metadata(args: argparse.Namespace) -> dict:
    return {
        "provider": args.provider,
        "requested_model_id": args.model,
        "temperature": args.temperature,
        "temperature_mode": temperature_mode(args.temperature),
        "prompt_version": PROMPT_VERSION,
        "schema_version": SCHEMA_VERSION,
        "eval_dataset_version": EVAL_DATASET_VERSION,
        "eval_cases_sha256": hashlib.sha256(args.cases.read_bytes()).hexdigest(),
    }


def validate_existing_artifact(path: Path, case, expected_metadata: dict) -> None:
    try:
        artifact = json.loads(path.read_text(encoding="utf-8"))
        if artifact.get("case_id") != case.case_id:
            raise ValueError("case_id mismatch")
        for key, expected_value in expected_metadata.items():
            if artifact.get(key) != expected_value:
                raise ValueError(
                    f"{key} mismatch: expected {expected_value!r}, got {artifact.get(key)!r}"
                )
        output = ListingAuditLLMOutput.model_validate(artifact.get("output"))
        validate_evidence_grounding(case.input, output)
        expected_score = calculate_overall_score(output.dimension_scores)
        if artifact.get("overall_score") != expected_score:
            raise ValueError("overall_score mismatch")
    except Exception as exc:
        raise RuntimeError(
            f"refusing to overwrite invalid or incompatible resume artifact {path}: {exc}"
        ) from exc


def write_json_atomically(path: Path, payload: dict) -> None:
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def raise_provider_diagnostic(exc: APIStatusError, args: argparse.Namespace, case_id: str) -> None:
    if args.provider == "openrouter" and exc.status_code == 404:
        raise RuntimeError(
            f"{case_id}: OpenRouter found no endpoint for model {args.model!r} that satisfies "
            "all required request and routing constraints. The run remains safely resumable. "
            "Verify model parameter support plus require_parameters=true, allow_fallbacks=false, "
            "zdr=true, and data_collection=deny. No constraint was relaxed. See "
            f"{OPENROUTER_ROUTING_DOCS}"
        ) from exc
    raise RuntimeError(
        f"{case_id}: provider request failed with HTTP {exc.status_code}; "
        "the run remains safely resumable and no secret was logged"
    ) from exc


def run_online(args: argparse.Namespace) -> None:
    if not args.model:
        raise SystemExit("--model is required for online baseline runs")
    if not args.output_dir:
        raise SystemExit("--output-dir is required for online baseline runs")

    cases = load_eval_cases(args.cases)
    client = create_provider_client(args.provider)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    run_started = datetime.now(UTC).isoformat()
    run_metadata = expected_run_metadata(args)

    manifest_path = args.output_dir / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for key, expected_value in run_metadata.items():
            if manifest.get(key) != expected_value:
                raise RuntimeError(
                    f"refusing to resume with incompatible manifest: {key} expected "
                    f"{expected_value!r}, got {manifest.get(key)!r}"
                )

    for case in cases:
        destination = args.output_dir / f"{case.case_id}.json"
        if destination.exists():
            validate_existing_artifact(destination, case, run_metadata)
            print(f"resumed {case.case_id} (existing artifact validated)")
            continue

        prompt = render_listing_audit_prompt(case.input)
        request = {
            "model": args.model,
            "messages": [
                {"role": "system", "content": prompt.system},
                {"role": "user", "content": prompt.user},
            ],
            "response_format": structured_output_format(),
            "store": False,
            "extra_body": provider_request_options(args.provider),
        }
        if args.temperature is not None:
            request["temperature"] = args.temperature
        try:
            response = client.chat.completions.create(**request)
        except APIStatusError as exc:
            raise_provider_diagnostic(exc, args, case.case_id)
        content = response.choices[0].message.content
        if not content:
            raise RuntimeError(f"{case.case_id}: provider returned empty content")
        try:
            output = ListingAuditLLMOutput.model_validate_json(content)
            validate_evidence_grounding(case.input, output)
        except Exception as exc:
            failure = {
                "case_id": case.case_id,
                **run_metadata,
                "response_model_id": response.model,
                "failure_stage": "output_validation",
                "failure_type": type(exc).__name__,
                "response_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                "response_character_count": len(content),
                "response_content_retained": False,
            }
            failure_path = args.output_dir / f"{case.case_id}.failure.json"
            write_json_atomically(failure_path, failure)
            raise RuntimeError(
                f"{case.case_id}: provider output failed schema or grounding validation "
                f"({type(exc).__name__}); response content was not retained, failure metadata "
                f"was written to {failure_path}, and the run remains safely resumable"
            ) from exc
        artifact = {
            "case_id": case.case_id,
            "case_title": case.title,
            "expected": case.expected.model_dump(mode="json"),
            **run_metadata,
            "response_model_id": response.model,
            "overall_score": calculate_overall_score(output.dimension_scores),
            "output": output.model_dump(mode="json"),
            "human_scores": [],
        }
        write_json_atomically(destination, artifact)
        print(f"completed {case.case_id}")

    manifest = {
        "started_at": run_started,
        "completed_at": datetime.now(UTC).isoformat(),
        "case_count": len(cases),
        **run_metadata,
    }
    write_json_atomically(manifest_path, manifest)


def main() -> int:
    args = parse_args()
    validate_cases(args.cases)
    if args.validate_only:
        return 0
    run_online(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
