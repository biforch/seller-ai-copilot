"""Tests for hardened Alpine verification manifest validator."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.validate_alpine_hardened_verification_manifest import (
    ManifestValidationError,
    validate_manifest,
)


def _write_manifest(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def test_validate_amd64_runtime_smoke_manifest_passes(tmp_path: Path) -> None:
    manifest = tmp_path / "amd64.json"
    _write_manifest(
        manifest,
        {
            "schema_version": 1,
            "architecture": "amd64",
            "verification_level": "runtime_smoke",
            "checks": {
                "runtime_environment": True,
                "alpine_os_packages": True,
                "production_smoke": True,
                "hardened_smoke": True,
                "uvicorn_health": True,
                "non_root_user": True,
            },
            "apk_inventory": ["ca-certificates", "libstdc++", "postgresql-libs"],
        },
    )
    validate_manifest(manifest)


def test_validate_manifest_rejects_forbidden_apk_inventory(tmp_path: Path) -> None:
    manifest = tmp_path / "arm64.json"
    _write_manifest(
        manifest,
        {
            "schema_version": 1,
            "architecture": "arm64",
            "verification_level": "build_only",
            "checks": {
                "image_config": True,
                "runtime_environment": True,
                "alpine_os_packages": True,
                "non_root_user": True,
            },
            "apk_inventory": ["perl-base"],
        },
    )
    with pytest.raises(ManifestValidationError) as exc:
        validate_manifest(manifest)
    assert str(exc.value) == "FORBIDDEN_APK_IN_INVENTORY"


def test_validate_manifest_rejects_malformed_json(tmp_path: Path) -> None:
    manifest = tmp_path / "bad.json"
    manifest.write_text("{not-json", encoding="utf-8")
    with pytest.raises(ManifestValidationError) as exc:
        validate_manifest(manifest)
    assert str(exc.value) == "MANIFEST_MALFORMED"
