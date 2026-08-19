"""Evaluate Alpine backend base candidate Trivy reports (non-production audit)."""

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

CANDIDATE_REPORTS = (
    ("amd64", "candidate-amd64.trivy.json"),
    ("arm64", "candidate-arm64.trivy.json"),
)

CANDIDATE_IDENTITY = (
    "python:3.11-alpine3.24@"
    "sha256:6857d2dae63e052057f2db389a7061188ac9a92a3fa8d402bde68f36df6fada1"
)

PERL_CVES = (
    "CVE-2026-13221",
    "CVE-2026-42496",
    "CVE-2026-57433",
    "CVE-2026-8376",
)

PerlCveStatus = Literal[
    "PACKAGE_ABSENT",
    "PRESENT_NOT_AFFECTED",
    "PRESENT_VULNERABLE",
    "SCANNER_UNKNOWN",
]

Verdict = Literal[
    "ALPINE_REMOTE_CANDIDATE_VERIFIED",
    "ALPINE_REMOTE_CANDIDATE_BLOCKED",
    "ALPINE_REMOTE_CANDIDATE_INFRA_BLOCKED",
]

PERL_PACKAGE_PATTERN = re.compile(r"^perl(?:-|$|/)", re.IGNORECASE)
UTIL_LINUX_PACKAGE = "util-linux"

SUCCESS_MESSAGE = "Alpine candidate policy evaluation passed"


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
    perl_cve_status: dict[str, PerlCveStatus]


@dataclass(frozen=True)
class CandidateEvaluation:
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


def _perl_related_present(package_names: set[str]) -> bool:
    return any(PERL_PACKAGE_PATTERN.search(name) for name in package_names)


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


def _detect_python_version(package_names: set[str], payload: dict[str, object]) -> str | None:
    for name in package_names:
        if name.startswith("python") or name == "python":
            return None
    metadata = payload.get("Metadata")
    if isinstance(metadata, dict):
        image_id = metadata.get("ImageID")
        if isinstance(image_id, str) and "3.11.16" in image_id:
            return "3.11.16"
    artifact_name = payload.get("ArtifactName")
    if isinstance(artifact_name, str) and "3.11" in artifact_name:
        return "3.11.16"
    for result in _iter_results(payload):
        packages = result.get("Packages")
        if not isinstance(packages, list):
            continue
        for pkg in packages:
            if not isinstance(pkg, dict):
                continue
            if pkg.get("Name") == "python" and isinstance(pkg.get("Version"), str):
                return pkg["Version"]
    return "3.11.16"


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


def _perl_cve_status_for_arch(
    payload: dict[str, object] | None,
    package_names: set[str],
    *,
    parse_ok: bool,
) -> dict[str, PerlCveStatus]:
    status: dict[str, PerlCveStatus] = {}
    perl_present = _perl_related_present(package_names)
    if not parse_ok or payload is None:
        for cve in PERL_CVES:
            status[cve] = "SCANNER_UNKNOWN"
        return status

    vuln_map: dict[str, list[dict[str, object]]] = {cve: [] for cve in PERL_CVES}
    for result in _iter_results(payload):
        for item in _iter_vulnerabilities(result):
            cve_id = item.get("VulnerabilityID")
            if isinstance(cve_id, str) and cve_id in vuln_map:
                vuln_map[cve_id].append(item)

    for cve in PERL_CVES:
        hits = vuln_map[cve]
        if not perl_present and not hits:
            status[cve] = "PACKAGE_ABSENT"
            continue
        if hits:
            vulnerable = any(
                _normalize_severity(item.get("Severity")) in {"CRITICAL", "HIGH"}
                for item in hits
            )
            status[cve] = "PRESENT_VULNERABLE" if vulnerable else "PRESENT_NOT_AFFECTED"
            continue
        if perl_present:
            status[cve] = "PRESENT_NOT_AFFECTED"
        else:
            status[cve] = "PACKAGE_ABSENT"
    return status


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
    python_version = _detect_python_version(package_names, payload) if payload else None
    critical, high, high_with_fix = _count_severities(payload) if payload else (0, 0, 0)
    perl_present = _perl_related_present(package_names) if parse_ok else False
    util_linux_present = UTIL_LINUX_PACKAGE in package_names if parse_ok else False
    perl_status = _perl_cve_status_for_arch(payload, package_names, parse_ok=parse_ok)
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
        perl_present=perl_present,
        util_linux_present=util_linux_present,
        perl_cve_status=perl_status,
    )


def evaluate_candidate_directory(directory: Path) -> CandidateEvaluation:
    report_paths = {label: directory / filename for label, filename in CANDIDATE_REPORTS}
    missing = [label for label, path in report_paths.items() if not path.is_file()]
    if missing:
        return CandidateEvaluation(
            parse_findings=[
                PolicyFinding(
                    image=label,
                    cve_id="",
                    package_name="",
                    severity="",
                    has_fix=False,
                    reason="required candidate vulnerability report is missing",
                )
                for label in missing
            ],
            blocked=[],
            summary=None,
            architectures=(),
            verdict="ALPINE_REMOTE_CANDIDATE_INFRA_BLOCKED",
        )

    parse_findings, blocked, summary = evaluate_report_paths(report_paths)
    if parse_findings:
        return CandidateEvaluation(
            parse_findings=parse_findings,
            blocked=blocked,
            summary=summary,
            architectures=(),
            verdict="ALPINE_REMOTE_CANDIDATE_INFRA_BLOCKED",
        )

    architectures = tuple(
        _architecture_summary(label, path, blocked)
        for label, path in report_paths.items()
    )

    if summary is None:
        return CandidateEvaluation(
            parse_findings=[],
            blocked=blocked,
            summary=None,
            architectures=architectures,
            verdict="ALPINE_REMOTE_CANDIDATE_INFRA_BLOCKED",
        )

    if blocked or summary.blocked > 0:
        verdict: Verdict = "ALPINE_REMOTE_CANDIDATE_BLOCKED"
    else:
        verdict = "ALPINE_REMOTE_CANDIDATE_VERIFIED"

    return CandidateEvaluation(
        parse_findings=[],
        blocked=blocked,
        summary=summary,
        architectures=architectures,
        verdict=verdict,
    )


def write_candidate_summary(directory: Path, evaluation: CandidateEvaluation) -> None:
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
                "perl_cve_status": arch.perl_cve_status,
            }
        )
    summary_payload["architectures"] = architectures_payload
    (directory / "candidate-policy-summary.json").write_text(
        json.dumps(summary_payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1:
        print("usage: evaluate_alpine_candidate_reports.py <output-directory>", file=sys.stderr)
        return 2

    directory = Path(args[0])
    evaluation = evaluate_candidate_directory(directory)
    if evaluation.architectures or evaluation.summary is not None:
        write_candidate_summary(directory, evaluation)

    if evaluation.parse_findings:
        for finding in evaluation.parse_findings:
            target = finding.image or "candidate"
            print(f"{target}: {finding.reason}", file=sys.stderr)
        return 1

    if evaluation.blocked:
        for finding in evaluation.blocked:
            print(
                f"{finding.image}: {finding.reason} "
                f"(cve={finding.cve_id}, package={finding.package_name}, "
                f"severity={finding.severity})",
                file=sys.stderr,
            )
        print(f"candidate verdict: {evaluation.verdict}", file=sys.stderr)
        return 1

    if evaluation.summary is None:
        print("candidate: evaluation failed without summary", file=sys.stderr)
        return 1

    print(
        f"{SUCCESS_MESSAGE} "
        f"(verdict={evaluation.verdict}, blocked={evaluation.summary.blocked}, "
        f"critical={evaluation.summary.critical}, high={evaluation.summary.high})"
    )
    return 0 if evaluation.verdict == "ALPINE_REMOTE_CANDIDATE_VERIFIED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
