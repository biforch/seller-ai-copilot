#!/usr/bin/env python3
"""Run or validate the Sprint 0.5 Listing Audit synthetic baseline.

This script never supports model or provider fallbacks and does not accept a
user-supplied base URL. It writes only synthetic eval outputs and non-sensitive
run metadata to the selected directory.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import sys
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
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
RUNS_ROOT = ROOT / "tests" / "evals" / "listing_audit" / "runs"
EXTERNAL_CALL_CONFIRMATION = "B1D-15-SYNTHETIC-CASES"
PROVIDER_TIMEOUT_SECONDS = 120.0
MAX_BASELINE_REQUESTS = 15
MAX_COMPLETION_TOKENS = 8_192


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
    parser.add_argument(
        "--confirm-external-call",
        help=(
            "Required exact confirmation for an online run. This is not a secret; use "
            f"{EXTERNAL_CALL_CONFIRMATION!r} only after provider, model, and spend approval."
        ),
    )
    parser.add_argument("--max-requests", type=int, default=MAX_BASELINE_REQUESTS)
    parser.add_argument(
        "--max-budget-usd",
        type=Decimal,
        help="Required positive OpenRouter cost ceiling for online runs",
    )
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
        return OpenAI(
            api_key=api_key,
            base_url="https://api.openai.com/v1",
            timeout=PROVIDER_TIMEOUT_SECONDS,
            max_retries=0,
        )
    if provider == "openrouter":
        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            raise RuntimeError(
                "OPENROUTER_API_KEY is not available to this process; "
                "configure it outside chat and do not pass it as a CLI argument"
            )
        return OpenAI(
            api_key=api_key,
            base_url="https://openrouter.ai/api/v1",
            timeout=PROVIDER_TIMEOUT_SECONDS,
            max_retries=0,
        )
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


def validate_online_run_contract(args: argparse.Namespace) -> Path:
    if not args.model:
        raise SystemExit("--model is required for online baseline runs")
    if not args.output_dir:
        raise SystemExit("--output-dir is required for online baseline runs")
    if args.confirm_external_call != EXTERNAL_CALL_CONFIRMATION:
        raise SystemExit(
            "online baseline runs require the exact --confirm-external-call value "
            f"{EXTERNAL_CALL_CONFIRMATION!r} after provider, model, and spend approval"
        )
    if len(args.model) > 200 or not args.model.strip() or any(
        character.isspace() or ord(character) < 32 for character in args.model
    ):
        raise SystemExit("--model must be a non-empty exact provider model ID without whitespace")
    if args.max_requests < 1 or args.max_requests > MAX_BASELINE_REQUESTS:
        raise SystemExit(f"--max-requests must be between 1 and {MAX_BASELINE_REQUESTS}")
    if args.max_budget_usd is None or args.max_budget_usd <= 0:
        raise SystemExit("--max-budget-usd must be a positive amount for online runs")
    if args.provider != "openrouter":
        raise SystemExit(
            "online budget enforcement currently supports OpenRouter only because its response "
            "includes provider-reported request cost"
        )

    runs_root = RUNS_ROOT.resolve()
    output_dir = args.output_dir.resolve()
    try:
        relative = output_dir.relative_to(runs_root)
    except ValueError as exc:
        raise SystemExit(f"--output-dir must be a child of {RUNS_ROOT}") from exc
    if relative == Path("."):
        raise SystemExit("--output-dir must name a run directory below the ignored runs root")
    return output_dir


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
    temporary.chmod(0o600)
    temporary.replace(path)


def extract_openrouter_usage(response) -> dict:
    raw_usage = response.model_dump(mode="json").get("usage")
    if not isinstance(raw_usage, dict):
        raise RuntimeError("OpenRouter response omitted required usage accounting")
    try:
        cost = Decimal(str(raw_usage["cost"]))
        prompt_tokens = int(raw_usage["prompt_tokens"])
        completion_tokens = int(raw_usage["completion_tokens"])
        total_tokens = int(raw_usage["total_tokens"])
    except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
        raise RuntimeError("OpenRouter response contained invalid usage accounting") from exc
    if cost < 0 or min(prompt_tokens, completion_tokens, total_tokens) < 0:
        raise RuntimeError("OpenRouter response contained negative usage accounting")
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "cost_usd": str(cost),
    }


@contextmanager
def exclusive_run_directory(output_dir: Path):
    """Reject concurrent writers for the same baseline run directory."""
    output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    output_dir.chmod(0o700)
    lock_path = output_dir / ".run.lock"
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError(
                f"another baseline runner already owns {output_dir}; no request was sent"
            ) from exc
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


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


def validate_resume_accounting(
    output_dir: Path, cases, request_count: int, cumulative_cost: Decimal
) -> None:
    successful_artifacts = [
        output_dir / f"{case.case_id}.json"
        for case in cases
        if (output_dir / f"{case.case_id}.json").exists()
    ]
    known_attempt_count = len(successful_artifacts) + len(
        list(output_dir.glob("*.failure.json"))
    )
    if request_count < known_attempt_count:
        raise RuntimeError(
            "refusing to resume because manifest request accounting is below retained "
            "success and failure evidence"
        )
    successful_cost = Decimal("0")
    for path in successful_artifacts:
        artifact = json.loads(path.read_text(encoding="utf-8"))
        usage = artifact.get("provider_usage")
        if not isinstance(usage, dict) or "cost_usd" not in usage:
            raise RuntimeError(f"refusing to resume {path} without provider cost accounting")
        successful_cost += Decimal(str(usage["cost_usd"]))
    if cumulative_cost < successful_cost:
        raise RuntimeError(
            "refusing to resume because manifest cost is below retained artifact costs"
        )


def _run_online_locked(args: argparse.Namespace, output_dir: Path) -> None:
    cases = load_eval_cases(args.cases)
    client = create_provider_client(args.provider)
    run_started = datetime.now(UTC).isoformat()
    run_metadata = expected_run_metadata(args)
    request_count = 0
    cumulative_cost = Decimal("0")

    manifest_path = output_dir / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for key, expected_value in run_metadata.items():
            if manifest.get(key) != expected_value:
                raise RuntimeError(
                    f"refusing to resume with incompatible manifest: {key} expected "
                    f"{expected_value!r}, got {manifest.get(key)!r}"
                )
        for required_key in (
            "external_request_count",
            "cumulative_cost_usd",
            "max_requests",
            "max_budget_usd",
        ):
            if required_key not in manifest:
                raise RuntimeError(
                    f"refusing to resume legacy manifest without {required_key}; "
                    "use a new run directory"
                )
        if manifest["max_requests"] != args.max_requests or Decimal(
            str(manifest["max_budget_usd"])
        ) != args.max_budget_usd:
            raise RuntimeError("refusing to resume with different request or budget ceilings")
        run_started = manifest.get("started_at", run_started)
        request_count = int(manifest.get("external_request_count", 0))
        cumulative_cost = Decimal(str(manifest.get("cumulative_cost_usd", "0")))
        validate_resume_accounting(output_dir, cases, request_count, cumulative_cost)

    for case in cases:
        destination = output_dir / f"{case.case_id}.json"
        if destination.exists():
            validate_existing_artifact(destination, case, run_metadata)
            artifact = json.loads(destination.read_text(encoding="utf-8"))
            usage = artifact.get("provider_usage")
            if not isinstance(usage, dict) or "cost_usd" not in usage:
                raise RuntimeError(
                    f"refusing to resume {destination} without provider cost accounting"
                )
            print(f"resumed {case.case_id} (existing artifact validated)")
            continue

        if request_count >= args.max_requests:
            raise RuntimeError("authorized external request limit reached")
        if cumulative_cost >= args.max_budget_usd:
            raise RuntimeError("authorized external budget reached")

        prompt = render_listing_audit_prompt(case.input)
        request = {
            "model": args.model,
            "messages": [
                {"role": "system", "content": prompt.system},
                {"role": "user", "content": prompt.user},
            ],
            "response_format": structured_output_format(),
            "store": False,
            "max_completion_tokens": MAX_COMPLETION_TOKENS,
            "extra_body": provider_request_options(args.provider),
        }
        if args.temperature is not None:
            request["temperature"] = args.temperature
        request_count += 1
        write_json_atomically(
            manifest_path,
            {
                "started_at": run_started,
                "completed_at": None,
                "case_count": len(cases),
                "external_request_count": request_count,
                "cumulative_cost_usd": str(cumulative_cost),
                "max_requests": args.max_requests,
                "max_budget_usd": str(args.max_budget_usd),
                **run_metadata,
            },
        )
        try:
            response = client.chat.completions.create(**request)
        except APIStatusError as exc:
            raise_provider_diagnostic(exc, args, case.case_id)
        content = response.choices[0].message.content
        if not content:
            raise RuntimeError(f"{case.case_id}: provider returned empty content")
        usage = extract_openrouter_usage(response)
        cumulative_cost += Decimal(usage["cost_usd"])
        write_json_atomically(
            manifest_path,
            {
                "started_at": run_started,
                "completed_at": None,
                "case_count": len(cases),
                "external_request_count": request_count,
                "cumulative_cost_usd": str(cumulative_cost),
                "max_requests": args.max_requests,
                "max_budget_usd": str(args.max_budget_usd),
                **run_metadata,
            },
        )
        if cumulative_cost > args.max_budget_usd:
            raise RuntimeError(
                f"{case.case_id}: provider-reported cumulative cost exceeded the authorized budget"
            )
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
            failure_path = output_dir / f"{case.case_id}.failure.json"
            if failure_path.exists():
                raise RuntimeError(
                    f"{case.case_id}: refusing to overwrite existing failure evidence "
                    f"{failure_path}; use a new run directory"
                ) from exc
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
            "provider_usage": usage,
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
        "external_request_count": request_count,
        "cumulative_cost_usd": str(cumulative_cost),
        "max_requests": args.max_requests,
        "max_budget_usd": str(args.max_budget_usd),
        **run_metadata,
    }
    write_json_atomically(manifest_path, manifest)


def run_online(args: argparse.Namespace) -> None:
    output_dir = validate_online_run_contract(args)
    with exclusive_run_directory(output_dir):
        _run_online_locked(args, output_dir)


def main() -> int:
    args = parse_args()
    validate_cases(args.cases)
    if args.validate_only:
        return 0
    run_online(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
