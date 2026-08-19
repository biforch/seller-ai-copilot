"""Tests for Alpine candidate wheel manifest validation."""

from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from scripts.validate_alpine_candidate_wheel_manifest import (  # noqa: E402
    validate_wheel_manifests,
)

REQ_SHA = "b" * 64


def _native_wheel(package: str, tag: str) -> dict[str, object]:
    return {
        "package": package,
        "version": "1.0.0",
        "wheel_tag": tag,
        "sha256": "a" * 64,
        "binary": True,
        "source": False,
    }


def _amd64_manifest() -> dict[str, object]:
    natives = [
        ("cryptography", "cp311-abi3-musllinux_1_2_x86_64"),
        ("psycopg2-binary", "cp311-cp311-musllinux_1_2_x86_64"),
        ("bcrypt", "cp37-abi3-musllinux_1_2_x86_64"),
        ("pydantic-core", "cp311-cp311-musllinux_1_1_x86_64"),
        ("cffi", "cp311-cp311-musllinux_1_2_x86_64"),
        ("uvloop", "cp311-cp311-musllinux_1_2_x86_64"),
        ("httptools", "cp311-cp311-musllinux_1_2_x86_64"),
        ("watchfiles", "cp311-cp311-musllinux_1_1_x86_64"),
    ]
    wheels = [_native_wheel(pkg, tag) for pkg, tag in natives]
    return {
        "schema_version": 1,
        "architecture": "amd64",
        "platform": "linux/amd64",
        "python_version": "3.11",
        "musl": True,
        "requirements_sha256": REQ_SHA,
        "download_status": "ok",
        "install_status": "ok",
        "pip_check_status": "ok",
        "import_status": "ok",
        "smoke_status": "ok",
        "reason_code": "WHEEL_AUDIT_OK",
        "wheel_count": len(wheels),
        "sdist_count": 0,
        "resolved_package_count": 8,
        "imports": [{"module": "cryptography", "status": "ok"}],
        "smoke": {"aesgcm_roundtrip": "ok", "jwt_hs256_roundtrip": "ok"},
        "wheels": wheels,
    }


def _arm64_manifest() -> dict[str, object]:
    natives = [
        ("cryptography", "cp311-abi3-musllinux_1_2_aarch64"),
        ("psycopg2-binary", "cp311-cp311-musllinux_1_2_aarch64"),
        ("bcrypt", "cp37-abi3-musllinux_1_2_aarch64"),
        ("pydantic-core", "cp311-cp311-musllinux_1_1_aarch64"),
        ("cffi", "cp311-cp311-musllinux_1_2_aarch64"),
        ("uvloop", "cp311-cp311-musllinux_1_2_aarch64"),
        ("httptools", "cp311-cp311-musllinux_1_2_aarch64"),
        ("watchfiles", "cp311-cp311-musllinux_1_1_aarch64"),
    ]
    wheels = []
    for pkg, tag in natives:
        entry = _native_wheel(pkg, tag)
        entry["import_status"] = "NOT_EXECUTED_CROSS_ARCH"
        entry["install_status"] = "NOT_EXECUTED_CROSS_ARCH"
        wheels.append(entry)
    return {
        "schema_version": 1,
        "architecture": "arm64",
        "platform": "linux/arm64",
        "python_version": "3.11",
        "musl": True,
        "mode": "resolution_only",
        "requirements_sha256": REQ_SHA,
        "resolution_status": "ok",
        "reason_code": "WHEEL_RESOLUTION_OK",
        "wheel_count": len(wheels),
        "sdist_count": 0,
        "resolved_package_count": 8,
        "missing_packages": [],
        "wheels": wheels,
    }


def test_valid_wheel_manifests_pass(tmp_path: Path) -> None:
    (tmp_path / "wheel-amd64.json").write_text(json.dumps(_amd64_manifest()), encoding="utf-8")
    (tmp_path / "wheel-arm64.json").write_text(json.dumps(_arm64_manifest()), encoding="utf-8")
    assert validate_wheel_manifests(tmp_path) == []


def test_missing_native_package_fails(tmp_path: Path) -> None:
    manifest = _amd64_manifest()
    manifest["wheels"] = [wheel for wheel in manifest["wheels"] if wheel["package"] != "watchfiles"]  # type: ignore[index]
    manifest["wheel_count"] = len(manifest["wheels"])  # type: ignore[index]
    (tmp_path / "wheel-amd64.json").write_text(json.dumps(manifest), encoding="utf-8")
    (tmp_path / "wheel-arm64.json").write_text(json.dumps(_arm64_manifest()), encoding="utf-8")
    findings = validate_wheel_manifests(tmp_path)
    assert any("watchfiles" in finding.reason for finding in findings)


def test_host_path_in_manifest_fails(tmp_path: Path) -> None:
    manifest = _amd64_manifest()
    manifest["note"] = "/Users/secret/path"  # type: ignore[index]
    (tmp_path / "wheel-amd64.json").write_text(json.dumps(manifest), encoding="utf-8")
    (tmp_path / "wheel-arm64.json").write_text(json.dumps(_arm64_manifest()), encoding="utf-8")
    findings = validate_wheel_manifests(tmp_path)
    assert any("host path" in finding.reason for finding in findings)


def test_requirements_sha_mismatch_fails(tmp_path: Path) -> None:
    amd64 = _amd64_manifest()
    arm64 = _arm64_manifest()
    arm64["requirements_sha256"] = "c" * 64
    (tmp_path / "wheel-amd64.json").write_text(json.dumps(amd64), encoding="utf-8")
    (tmp_path / "wheel-arm64.json").write_text(json.dumps(arm64), encoding="utf-8")
    findings = validate_wheel_manifests(tmp_path)
    assert any("requirements_sha256 must match" in finding.reason for finding in findings)


def test_non_zero_sdist_count_fails(tmp_path: Path) -> None:
    manifest = _amd64_manifest()
    manifest["sdist_count"] = 1
    (tmp_path / "wheel-amd64.json").write_text(json.dumps(manifest), encoding="utf-8")
    (tmp_path / "wheel-arm64.json").write_text(json.dumps(_arm64_manifest()), encoding="utf-8")
    findings = validate_wheel_manifests(tmp_path)
    assert any("sdist_count must be 0" in finding.reason for finding in findings)
