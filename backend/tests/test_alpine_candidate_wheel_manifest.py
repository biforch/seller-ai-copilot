"""Tests for Alpine candidate wheel manifest validation."""

from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from scripts.validate_alpine_candidate_wheel_manifest import (  # noqa: E402
    validate_wheel_manifests,
    wheel_tags_compatible_with_architecture,
)

REQ_SHA = "b" * 64


def _wheel_entry(package: str, wheel_filename: str, wheel_tags: list[str]) -> dict[str, object]:
    return {
        "package": package,
        "version": "1.0.0",
        "filename": wheel_filename,
        "wheel_tags": wheel_tags,
        "sha256": "a" * 64,
        "binary": True,
        "source": False,
    }


def _amd64_manifest(*, extra_wheels: list[dict[str, object]] | None = None) -> dict[str, object]:
    natives = [
        ("cryptography", "cryptography-42.0.0-cp311-abi3-musllinux_1_2_x86_64.whl", ["cp311-abi3-musllinux_1_2_x86_64"]),
        ("psycopg2-binary", "psycopg2_binary-2.9.9-cp311-cp311-musllinux_1_2_x86_64.whl", ["cp311-cp311-musllinux_1_2_x86_64"]),
        ("bcrypt", "bcrypt-4.1.2-cp37-abi3-musllinux_1_2_x86_64.whl", ["cp37-abi3-musllinux_1_2_x86_64"]),
        ("pydantic-core", "pydantic_core-2.6.0-cp311-cp311-musllinux_1_1_x86_64.whl", ["cp311-cp311-musllinux_1_1_x86_64"]),
        ("cffi", "cffi-1.16.0-cp311-cp311-musllinux_1_2_x86_64.whl", ["cp311-cp311-musllinux_1_2_x86_64"]),
        ("uvloop", "uvloop-0.19.0-cp311-cp311-musllinux_1_2_x86_64.whl", ["cp311-cp311-musllinux_1_2_x86_64"]),
        ("httptools", "httptools-0.6.1-cp311-cp311-musllinux_1_2_x86_64.whl", ["cp311-cp311-musllinux_1_2_x86_64"]),
        ("watchfiles", "watchfiles-0.21.0-cp311-cp311-musllinux_1_1_x86_64.whl", ["cp311-cp311-musllinux_1_1_x86_64"]),
    ]
    wheels = [_wheel_entry(pkg, filename, tags) for pkg, filename, tags in natives]
    if extra_wheels:
        wheels.extend(extra_wheels)
    return {
        "schema_version": 2,
        "architecture": "amd64",
        "platform": "linux/amd64",
        "python_version": "3.11",
        "musl": True,
        "mode": "install_and_import",
        "status": "passed",
        "requirements_sha256": REQ_SHA,
        "dependency_validation_method": "target_dependency_check",
        "download_status": "ok",
        "install_status": "ok",
        "dependency_check_status": "ok",
        "import_status": "ok",
        "smoke_status": "ok",
        "reason_code": "WHEEL_AUDIT_OK",
        "wheel_count": len(wheels),
        "sdist_count": 0,
        "resolved_package_count": len(wheels),
        "missing_binary_package_count": 0,
        "missing_packages": [],
        "imports": [{"module": "cryptography", "status": "ok"}],
        "smoke": {"aesgcm_roundtrip": "ok", "jwt_hs256_roundtrip": "ok"},
        "wheels": wheels,
    }


def _arm64_manifest(*, extra_wheels: list[dict[str, object]] | None = None) -> dict[str, object]:
    natives = [
        ("cryptography", "cryptography-42.0.0-cp311-abi3-musllinux_1_2_aarch64.whl", ["cp311-abi3-musllinux_1_2_aarch64"]),
        ("psycopg2-binary", "psycopg2_binary-2.9.9-cp311-cp311-musllinux_1_2_aarch64.whl", ["cp311-cp311-musllinux_1_2_aarch64"]),
        ("bcrypt", "bcrypt-4.1.2-cp37-abi3-musllinux_1_2_aarch64.whl", ["cp37-abi3-musllinux_1_2_aarch64"]),
        ("pydantic-core", "pydantic_core-2.6.0-cp311-cp311-musllinux_1_1_aarch64.whl", ["cp311-cp311-musllinux_1_1_aarch64"]),
        ("cffi", "cffi-1.16.0-cp311-cp311-musllinux_1_2_aarch64.whl", ["cp311-cp311-musllinux_1_2_aarch64"]),
        ("uvloop", "uvloop-0.19.0-cp311-cp311-musllinux_1_2_aarch64.whl", ["cp311-cp311-musllinux_1_2_aarch64"]),
        ("httptools", "httptools-0.6.1-cp311-cp311-musllinux_1_2_aarch64.whl", ["cp311-cp311-musllinux_1_2_aarch64"]),
        ("watchfiles", "watchfiles-0.21.0-cp311-cp311-musllinux_1_1_aarch64.whl", ["cp311-cp311-musllinux_1_1_aarch64"]),
    ]
    wheels = []
    for pkg, filename, tags in natives:
        entry = _wheel_entry(pkg, filename, tags)
        entry["import_status"] = "NOT_EXECUTED_CROSS_ARCH"
        entry["install_status"] = "NOT_EXECUTED_CROSS_ARCH"
        wheels.append(entry)
    if extra_wheels:
        wheels.extend(extra_wheels)
    return {
        "schema_version": 2,
        "architecture": "arm64",
        "platform": "linux/arm64",
        "python_version": "3.11",
        "musl": True,
        "mode": "resolution_only",
        "status": "passed",
        "requirements_sha256": REQ_SHA,
        "dependency_validation_method": "wheel_resolution_only",
        "download_status": "ok",
        "resolution_status": "ok",
        "reason_code": "WHEEL_RESOLUTION_OK",
        "wheel_count": len(wheels),
        "sdist_count": 0,
        "resolved_package_count": len(wheels),
        "missing_binary_package_count": 0,
        "missing_packages": [],
        "wheels": wheels,
    }


def _write_manifests(tmp_path: Path, amd64: dict[str, object], arm64: dict[str, object]) -> None:
    (tmp_path / "wheel-amd64.json").write_text(json.dumps(amd64), encoding="utf-8")
    (tmp_path / "wheel-arm64.json").write_text(json.dumps(arm64), encoding="utf-8")


def test_valid_wheel_manifests_pass(tmp_path: Path) -> None:
    _write_manifests(tmp_path, _amd64_manifest(), _arm64_manifest())
    assert validate_wheel_manifests(tmp_path) == []


def test_py3_none_any_compatible_on_both_architectures() -> None:
    assert wheel_tags_compatible_with_architecture(["py3-none-any"], "amd64")
    assert wheel_tags_compatible_with_architecture(["py3-none-any"], "arm64")


def test_py311_none_any_compatible_on_both_architectures() -> None:
    assert wheel_tags_compatible_with_architecture(["py311-none-any"], "amd64")
    assert wheel_tags_compatible_with_architecture(["py311-none-any"], "arm64")


def test_x86_64_musllinux_amd64_only() -> None:
    tag = "cp311-cp311-musllinux_1_2_x86_64"
    assert wheel_tags_compatible_with_architecture([tag], "amd64")
    assert not wheel_tags_compatible_with_architecture([tag], "arm64")


def test_aarch64_musllinux_arm64_only() -> None:
    tag = "cp311-cp311-musllinux_1_2_aarch64"
    assert wheel_tags_compatible_with_architecture([tag], "arm64")
    assert not wheel_tags_compatible_with_architecture([tag], "amd64")


def test_one_compatible_tag_among_many_passes() -> None:
    tags = ["cp311-cp311-musllinux_1_2_aarch64", "py311-none-any"]
    assert wheel_tags_compatible_with_architecture(tags, "amd64")
    assert wheel_tags_compatible_with_architecture(tags, "arm64")


def test_empty_tags_rejected() -> None:
    assert not wheel_tags_compatible_with_architecture([], "amd64")


def test_s3d4c1c_universal_wheel_fixture_passes(tmp_path: Path) -> None:
    universal = _wheel_entry("click", "click-8.1.7-py3-none-any.whl", ["py3-none-any"])
    _write_manifests(
        tmp_path,
        _amd64_manifest(extra_wheels=[universal]),
        _arm64_manifest(extra_wheels=[{**universal, "import_status": "NOT_EXECUTED_CROSS_ARCH", "install_status": "NOT_EXECUTED_CROSS_ARCH"}]),
    )
    assert validate_wheel_manifests(tmp_path) == []


def test_legacy_wheel_tag_field_rejected(tmp_path: Path) -> None:
    manifest = _amd64_manifest()
    manifest["wheels"] = [  # type: ignore[index]
        {
            "package": "click",
            "version": "8.1.7",
            "wheel_tag": "any",
            "sha256": "a" * 64,
            "binary": True,
            "source": False,
        }
    ]
    manifest["wheel_count"] = 1  # type: ignore[index]
    _write_manifests(tmp_path, manifest, _arm64_manifest())
    findings = validate_wheel_manifests(tmp_path)
    assert any("legacy wheel_tag" in finding.reason for finding in findings)


def test_wrong_architecture_fixture_rejected(tmp_path: Path) -> None:
    wrong = _wheel_entry(
        "uvloop",
        "uvloop-0.19.0-cp311-cp311-musllinux_1_2_aarch64.whl",
        ["cp311-cp311-musllinux_1_2_aarch64"],
    )
    _write_manifests(tmp_path, _amd64_manifest(extra_wheels=[wrong]), _arm64_manifest())
    findings = validate_wheel_manifests(tmp_path)
    assert any("architecture-compatible wheel tag" in finding.reason for finding in findings)


def test_malformed_wheel_filename_rejected(tmp_path: Path) -> None:
    manifest = _amd64_manifest(
        extra_wheels=[_wheel_entry("broken", "not-a-wheel.txt", ["py3-none-any"])]
    )
    _write_manifests(tmp_path, manifest, _arm64_manifest())
    findings = validate_wheel_manifests(tmp_path)
    assert any("invalid wheel filename format" in finding.reason for finding in findings)


def test_failed_status_manifest_fails(tmp_path: Path) -> None:
    manifest = _amd64_manifest()
    manifest["status"] = "failed"
    manifest["reason_code"] = "WHEEL_AUDIT_FAILED"
    _write_manifests(tmp_path, manifest, _arm64_manifest())
    findings = validate_wheel_manifests(tmp_path)
    assert any("status must be passed" in finding.reason for finding in findings)


def test_missing_native_package_fails(tmp_path: Path) -> None:
    manifest = _amd64_manifest()
    manifest["wheels"] = [wheel for wheel in manifest["wheels"] if wheel["package"] != "watchfiles"]  # type: ignore[index]
    manifest["wheel_count"] = len(manifest["wheels"])  # type: ignore[index]
    _write_manifests(tmp_path, manifest, _arm64_manifest())
    findings = validate_wheel_manifests(tmp_path)
    assert any("watchfiles" in finding.reason for finding in findings)


def test_host_path_in_manifest_fails(tmp_path: Path) -> None:
    manifest = _amd64_manifest()
    manifest["note"] = "/Users/secret/path"  # type: ignore[index]
    _write_manifests(tmp_path, manifest, _arm64_manifest())
    findings = validate_wheel_manifests(tmp_path)
    assert any("host path" in finding.reason for finding in findings)


def test_requirements_sha_mismatch_fails(tmp_path: Path) -> None:
    amd64 = _amd64_manifest()
    arm64 = _arm64_manifest()
    arm64["requirements_sha256"] = "c" * 64
    _write_manifests(tmp_path, amd64, arm64)
    findings = validate_wheel_manifests(tmp_path)
    assert any("requirements_sha256 must match" in finding.reason for finding in findings)


def test_non_zero_sdist_count_fails(tmp_path: Path) -> None:
    manifest = _amd64_manifest()
    manifest["sdist_count"] = 1
    _write_manifests(tmp_path, manifest, _arm64_manifest())
    findings = validate_wheel_manifests(tmp_path)
    assert any("sdist_count must be 0" in finding.reason for finding in findings)
