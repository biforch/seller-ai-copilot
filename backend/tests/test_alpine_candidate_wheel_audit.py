"""Tests for Alpine candidate wheel audit helpers and target dependency validation."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from scripts.alpine_wheel_audit_common import (  # noqa: E402
    atomic_write_json,
    write_output_probe,
)
from scripts.validate_target_site_packages import validate_target_site_packages  # noqa: E402


def _write_dist_info(target: Path, name: str, version: str, requires: list[str]) -> None:
    dist_dir = target / f"{name.replace('-', '_')}-{version}.dist-info"
    dist_dir.mkdir(parents=True, exist_ok=True)
    metadata = ["Metadata-Version: 2.1", f"Name: {name}", f"Version: {version}"]
    for req in requires:
        metadata.append(f"Requires-Dist: {req}")
    (dist_dir / "METADATA").write_text("\n".join(metadata) + "\n", encoding="utf-8")
    (dist_dir / "WHEEL").write_text("Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: py3-none-any\n", encoding="utf-8")


def test_atomic_write_json_roundtrip(tmp_path: Path) -> None:
    payload = {"schema_version": 1, "status": "failed", "reason_code": "TEST"}
    target = tmp_path / "wheel-amd64.json"
    atomic_write_json(target, payload)
    loaded = json.loads(target.read_text(encoding="utf-8"))
    assert loaded == payload


def test_write_output_probe(tmp_path: Path) -> None:
    write_output_probe(tmp_path)
    assert not (tmp_path / ".write-probe").exists()


def test_target_dependency_validator_detects_missing_dependency(tmp_path: Path) -> None:
    target = tmp_path / "site-packages"
    target.mkdir()
    _write_dist_info(target, "alpha", "1.0.0", ["beta>=1.0"])
    status, issues = validate_target_site_packages(target)
    assert status == "failed"
    assert any(issue.startswith("missing:beta") for issue in issues)


def test_target_dependency_validator_passes_when_graph_complete(tmp_path: Path) -> None:
    target = tmp_path / "site-packages"
    target.mkdir()
    _write_dist_info(target, "beta", "1.0.0", [])
    _write_dist_info(target, "alpha", "1.0.0", ["beta>=1.0"])
    status, issues = validate_target_site_packages(target)
    assert status == "ok"
    assert issues == []


def test_target_dependency_validator_fails_when_dependency_removed(tmp_path: Path) -> None:
    target = tmp_path / "site-packages"
    target.mkdir()
    _write_dist_info(target, "beta", "1.0.0", [])
    _write_dist_info(target, "alpha", "1.0.0", ["beta>=1.0"])
    assert validate_target_site_packages(target)[0] == "ok"
    assert (target / "beta-1.0.0.dist-info").exists()
    shutil.rmtree(target / "beta-1.0.0.dist-info")
    status, issues = validate_target_site_packages(target)
    assert status == "failed"
    assert any(issue.startswith("missing:beta") for issue in issues)
