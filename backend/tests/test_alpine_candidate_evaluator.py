"""Tests for Alpine candidate vulnerability policy evaluation."""

from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from scripts.evaluate_alpine_candidate_reports import (  # noqa: E402
    CANDIDATE_REPORTS,
    evaluate_candidate_directory,
    main,
)
from scripts.evaluate_vulnerability_report import evaluate_directory  # noqa: E402


def _report(vulnerabilities: list[dict[str, object]] | None = None) -> dict[str, object]:
    return {
        "SchemaVersion": 2,
        "Metadata": {"OS": {"Family": "alpine", "Name": "3.24.1"}},
        "Results": [
            {
                "Target": "python:3.11-alpine3.24 (alpine 3.24.1)",
                "Class": "os-pkgs",
                "Type": "alpine",
                "Packages": [{"Name": "musl", "Version": "1.2.6-r2"}],
                "Vulnerabilities": vulnerabilities or [],
            }
        ],
    }


def _vuln(cve: str, package: str, severity: str, fixed: object = "") -> dict[str, object]:
    payload: dict[str, object] = {
        "VulnerabilityID": cve,
        "PkgName": package,
        "Severity": severity,
    }
    if fixed != "":
        payload["FixedVersion"] = fixed
    return payload


def _write_candidate_reports(directory: Path, amd64: dict, arm64: dict) -> None:
    mapping = dict(CANDIDATE_REPORTS)
    (directory / mapping["amd64"]).write_text(json.dumps(amd64), encoding="utf-8")
    (directory / mapping["arm64"]).write_text(json.dumps(arm64), encoding="utf-8")


def test_candidate_clean_reports_verify(tmp_path: Path) -> None:
    _write_candidate_reports(tmp_path, _report(), _report())
    evaluation = evaluate_candidate_directory(tmp_path)
    assert evaluation.parse_findings == []
    assert evaluation.blocked == []
    assert evaluation.verdict == "ALPINE_REMOTE_CANDIDATE_VERIFIED"
    assert all(status == "PACKAGE_ABSENT" for arch in evaluation.architectures for status in arch.perl_cve_status.values())


def test_candidate_critical_blocks(tmp_path: Path) -> None:
    _write_candidate_reports(
        tmp_path,
        _report([_vuln("CVE-CRIT-1", "musl", "CRITICAL")]),
        _report(),
    )
    evaluation = evaluate_candidate_directory(tmp_path)
    assert evaluation.verdict == "ALPINE_REMOTE_CANDIDATE_BLOCKED"
    assert evaluation.summary is not None
    assert evaluation.summary.blocked >= 1


def test_candidate_high_with_fix_blocks(tmp_path: Path) -> None:
    _write_candidate_reports(
        tmp_path,
        _report([_vuln("CVE-HIGH-1", "busybox", "HIGH", "1.2.3")]),
        _report(),
    )
    evaluation = evaluate_candidate_directory(tmp_path)
    assert evaluation.verdict == "ALPINE_REMOTE_CANDIDATE_BLOCKED"


def test_candidate_high_without_fix_passes(tmp_path: Path) -> None:
    _write_candidate_reports(
        tmp_path,
        _report([_vuln("CVE-HIGH-2", "busybox", "HIGH")]),
        _report(),
    )
    evaluation = evaluate_candidate_directory(tmp_path)
    assert evaluation.blocked == []
    assert evaluation.verdict == "ALPINE_REMOTE_CANDIDATE_VERIFIED"


def test_candidate_malformed_report_is_infra_blocked(tmp_path: Path) -> None:
    _write_candidate_reports(tmp_path, {"SchemaVersion": 2, "Results": "bad"}, _report())
    evaluation = evaluate_candidate_directory(tmp_path)
    assert evaluation.verdict == "ALPINE_REMOTE_CANDIDATE_INFRA_BLOCKED"


def test_production_evaluator_contract_unchanged(tmp_path: Path) -> None:
    production = {
        "backend": _report(),
        "frontend": _report(),
        "nginx": _report(),
    }
    for label, filename in (
        ("backend", "backend.trivy.json"),
        ("frontend", "frontend.trivy.json"),
        ("nginx", "nginx.trivy.json"),
    ):
        (tmp_path / filename).write_text(json.dumps(production[label]), encoding="utf-8")
    parse_findings, blocked, summary = evaluate_directory(tmp_path)
    assert parse_findings == []
    assert blocked == []
    assert summary is not None
    assert summary.images == 3


def test_candidate_main_writes_summary(tmp_path: Path) -> None:
    _write_candidate_reports(tmp_path, _report(), _report())
    assert main([str(tmp_path)]) == 0
    summary = json.loads((tmp_path / "candidate-policy-summary.json").read_text(encoding="utf-8"))
    assert summary["verdict"] == "ALPINE_REMOTE_CANDIDATE_VERIFIED"
    assert len(summary["architectures"]) == 2
