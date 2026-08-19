"""Evaluate hardened Alpine backend candidate Trivy reports (non-production audit)."""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from scripts.evaluate_vulnerability_report import (  # noqa: E402
    EvaluationSummary,
    PolicyFinding,
    _has_fixed_version,
    _normalize_severity,
    evaluate_report_paths,
)

HARDENED_REPORTS = (
    ("amd64", "backend-alpine-amd64.trivy.json"),
    ("arm64", "backend-alpine-arm64.trivy.json"),
)

CANDIDATE_IDENTITY = (
    "python:3.11-alpine3.24@"
    "sha256:6857d2dae63e052057f2db389a7061188ac9a92a3fa8d402bde68f36df6fada1"
)

FORBIDDEN_PACKAGE_MARKERS = (
    "wheel",
    "jaraco.context",
    "perl",
    "perl-base",
    "util-linux",
)

PERL_PACKAGE_PATTERN = re.compile(r"^perl(?:-|$|/)", re.IGNORECASE)
UTIL_LINUX_PATTERN = re.compile(r"^util-linux", re.IGNORECASE)

Verdict = Literal[
    "ALPINE_HARDENED_CANDIDATE_VERIFIED",
    "ALPINE_HARDENED_CANDIDATE_BLOCKED",
    "ALPINE_HARDENED_CANDIDATE_INFRA_BLOCKED",
]

SUCCESS_MESSAGE = "Alpine hardened candidate policy evaluation passed"


@dataclass(frozen=True)
class ArchitectureSummary:
    architecture: str
    schema_version: int | None
    os_family: str | None
    os_version: str | None
    python_version: str | None
    package_count: int
    critical: int
    high: int
    high_with_fix: int
    blocked: int
    perl_present: bool
    util_linux_present: bool
    wheel_present: bool
    jaraco_present: bool
    forbidden_hits: tuple[str, ...]


@dataclass(frozen=True)
class HardenedEvaluation:
    parse_findings: list[PolicyFinding]
    blocked: list[PolicyFinding]
    summary: EvaluationSummary | None
    architectures: tuple[ArchitectureSummary, ...]
    verdict: Verdict


def _load_report(path: Path) -> dict[str, object] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _collect_package_names(payload: dict[str, object]) -> set[str]:
    names: set[str] = set()
    results = payload.get("Results")
    if not isinstance(results, list):
        return names
    for result in results:
        if not isinstance(result, dict):
            continue
        packages = result.get("Packages")
        if isinstance(packages, list):
            for pkg in packages:
                if isinstance(pkg, dict):
                    name = pkg.get("Name")
                    if isinstance(name, str) and name.strip():
                        names.add(name.strip())
        vulnerabilities = result.get("Vulnerabilities")
        if isinstance(vulnerabilities, list):
            for item in vulnerabilities:
                if isinstance(item, dict):
                    pkg_name = item.get("PkgName")
                    if isinstance(pkg_name, str) and pkg_name.strip():
                        names.add(pkg_name.strip())
    return names


def _detect_os(payload: dict[str, object]) -> tuple[str | None, str | None]:
    metadata = payload.get("Metadata")
    if not isinstance(metadata, dict):
        return None, None
    os_info = metadata.get("OS")
    if not isinstance(os_info, dict):
        return None, None
    family = os_info.get("Family")
    name = os_info.get("Name")
    family_str = family if isinstance(family, str) else None
    name_str = name if isinstance(name, str) else None
    return family_str, name_str


def _iter_results(payload: dict[str, object]) -> list[dict[str, object]]:
    results = payload.get("Results")
    if not isinstance(results, list):
        return []
    return [item for item in results if isinstance(item, dict)]


def _iter_vulnerabilities(result: dict[str, object]) -> list[dict[str, object]]:
    items = result.get("Vulnerabilities")
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def _detect_python_version(payload: dict[str, object]) -> str | None:
    for result in _iter_results(payload):
        packages = result.get("Packages")
        if not isinstance(packages, list):
            continue
        for pkg in packages:
            if not isinstance(pkg, dict):
                continue
            if pkg.get("Name") == "python" and isinstance(pkg.get("Version"), str):
                return pkg["Version"]
    return None


def _count_severities(payload: dict[str, object]) -> tuple[int, int, int]:
    critical = 0
    high = 0
    high_with_fix = 0
    for result in _iter_results(payload):
        for item in _iter_vulnerabilities(result):
            severity = _normalize_severity(item.get("Severity"))
            if severity == "CRITICAL":
                critical += 1
            elif severity == "HIGH":
                high += 1
                if _has_fixed_version(item.get("FixedVersion")):
                    high_with_fix += 1
    return critical, high, high_with_fix


def _forbidden_package_hits(package_names: set[str]) -> tuple[str, ...]:
    hits: list[str] = []
    for name in sorted(package_names):
        lowered = name.lower()
        if lowered in {"wheel", "jaraco.context", "perl-base", "util-linux"}:
            hits.append(name)
            continue
        if PERL_PACKAGE_PATTERN.search(name):
            hits.append(name)
            continue
        if UTIL_LINUX_PATTERN.search(name):
            hits.append(name)
    return tuple(hits)


def _architecture_summary(
    architecture: str,
    path: Path,
    blocked_for_arch: list[PolicyFinding],
) -> ArchitectureSummary:
    payload = _load_report(path)
    parse_ok = payload is not None and payload.get("Error") is None
    schema_version = payload.get("SchemaVersion") if parse_ok and payload else None
    schema_int = schema_version if isinstance(schema_version, int) else None
    package_names = _collect_package_names(payload) if payload else set()
    os_family, os_version = _detect_os(payload) if payload else (None, None)
    python_version = _detect_python_version(payload) if payload else None
    critical, high, high_with_fix = _count_severities(payload) if payload else (0, 0, 0)
    forbidden_hits = _forbidden_package_hits(package_names) if parse_ok else ()
    return ArchitectureSummary(
        architecture=architecture,
        schema_version=schema_int,
        os_family=os_family,
        os_version=os_version,
        python_version=python_version,
        package_count=len(package_names),
        critical=critical,
        high=high,
        high_with_fix=high_with_fix,
        blocked=len([finding for finding in blocked_for_arch if finding.image == architecture]),
        perl_present=any(PERL_PACKAGE_PATTERN.search(name) for name in package_names),
        util_linux_present=any(UTIL_LINUX_PATTERN.search(name) for name in package_names),
        wheel_present="wheel" in {name.lower() for name in package_names},
        jaraco_present="jaraco.context" in {name.lower() for name in package_names},
        forbidden_hits=forbidden_hits,
    )


def evaluate_hardened_directory(directory: Path) -> HardenedEvaluation:
    report_paths = {label: directory / filename for label, filename in HARDENED_REPORTS}
    missing = [label for label, path in report_paths.items() if not path.is_file()]
    if missing:
        return HardenedEvaluation(
            parse_findings=[
                PolicyFinding(
                    image=label,
                    cve_id="",
                    package_name="",
                    severity="",
                    has_fix=False,
                    reason="required hardened candidate vulnerability report is missing",
                )
                for label in missing
            ],
            blocked=[],
            summary=None,
            architectures=(),
            verdict="ALPINE_HARDENED_CANDIDATE_INFRA_BLOCKED",
        )

    parse_findings, blocked, summary = evaluate_report_paths(report_paths)
    if parse_findings:
        return HardenedEvaluation(
            parse_findings=parse_findings,
            blocked=blocked,
            summary=summary,
            architectures=(),
            verdict="ALPINE_HARDENED_CANDIDATE_INFRA_BLOCKED",
        )

    architectures = tuple(
        _architecture_summary(label, path, blocked)
        for label, path in report_paths.items()
    )

    forbidden_blockers = [
        arch
        for arch in architectures
        if arch.forbidden_hits
    ]

    if summary is None:
        return HardenedEvaluation(
            parse_findings=[],
            blocked=blocked,
            summary=None,
            architectures=architectures,
            verdict="ALPINE_HARDENED_CANDIDATE_INFRA_BLOCKED",
        )

    if blocked or summary.blocked > 0 or forbidden_blockers:
        verdict: Verdict = "ALPINE_HARDENED_CANDIDATE_BLOCKED"
    else:
        verdict = "ALPINE_HARDENED_CANDIDATE_VERIFIED"

    return HardenedEvaluation(
        parse_findings=[],
        blocked=blocked,
        summary=summary,
        architectures=architectures,
        verdict=verdict,
    )


def write_hardened_summary(directory: Path, evaluation: HardenedEvaluation) -> None:
    summary_payload: dict[str, object] = {
        "schema_version": 1,
        "candidate_identity": CANDIDATE_IDENTITY,
        "verdict": evaluation.verdict,
    }
    if evaluation.summary is not None:
        summary_payload["vulnerabilities"] = evaluation.summary.vulnerabilities
        summary_payload["critical"] = evaluation.summary.critical
        summary_payload["high"] = evaluation.summary.high
        summary_payload["blocked"] = evaluation.summary.blocked
    else:
        summary_payload["vulnerabilities"] = 0
        summary_payload["critical"] = 0
        summary_payload["high"] = 0
        summary_payload["blocked"] = 0

    architectures_payload: list[dict[str, object]] = []
    for arch in evaluation.architectures:
        architectures_payload.append(
            {
                "architecture": arch.architecture,
                "schema_version": arch.schema_version,
                "os_family": arch.os_family,
                "os_version": arch.os_version,
                "python_version": arch.python_version,
                "package_count": arch.package_count,
                "critical": arch.critical,
                "high": arch.high,
                "high_with_fix": arch.high_with_fix,
                "blocked": arch.blocked,
                "perl_present": arch.perl_present,
                "util_linux_present": arch.util_linux_present,
                "wheel_present": arch.wheel_present,
                "jaraco_present": arch.jaraco_present,
                "forbidden_hits": list(arch.forbidden_hits),
            }
        )
    summary_payload["architectures"] = architectures_payload

    output_path = directory / "backend-alpine-hardened-summary.json"
    output_path.write_text(json.dumps(summary_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    if len(sys.argv) != 2:
        print("USAGE_INVALID", file=sys.stderr)
        return 1

    directory = Path(sys.argv[1])
    evaluation = evaluate_hardened_directory(directory)
    write_hardened_summary(directory, evaluation)

    if evaluation.verdict != "ALPINE_HARDENED_CANDIDATE_VERIFIED":
        print(evaluation.verdict, file=sys.stderr)
        return 1

    print(SUCCESS_MESSAGE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
