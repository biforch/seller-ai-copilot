"""Tests for SBOM artifact validation."""

from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stderr
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from scripts.validate_sbom_artifacts import (  # noqa: E402
    MAX_COMPONENTS,
    MAX_FILE_BYTES,
    REQUIRED_FILES,
    main,
    validate_sbom_directory,
    validate_sbom_file,
)

SECRET_CANARY = "state-canary-secret-do-not-echo"


def _minimal_sbom(name: str = "example", version: str = "1.0.0", spec_version: str = "1.5") -> dict:
    return {
        "bomFormat": "CycloneDX",
        "specVersion": spec_version,
        "components": [{"name": name, "version": version, "purl": "pkg:npm/example@1.0.0"}],
    }


def _write_sboms(directory: Path) -> None:
    for filename in REQUIRED_FILES:
        (directory / filename).write_text(json.dumps(_minimal_sbom(filename.split(".")[0])), encoding="utf-8")


def test_three_valid_minimal_cyclonedx_files_pass(tmp_path: Path) -> None:
    _write_sboms(tmp_path)
    findings, checked = validate_sbom_directory(tmp_path)
    assert findings == []
    assert checked == 3


def test_missing_required_file_fails(tmp_path: Path) -> None:
    _write_sboms(tmp_path)
    (tmp_path / "nginx.cdx.json").unlink()
    findings, _ = validate_sbom_directory(tmp_path)
    assert any("missing" in finding.reason for finding in findings)


def test_malformed_json_fails(tmp_path: Path) -> None:
    _write_sboms(tmp_path)
    (tmp_path / "backend.cdx.json").write_text("{not-json", encoding="utf-8")
    findings = validate_sbom_file(tmp_path / "backend.cdx.json")
    assert any("not valid JSON" in finding.reason for finding in findings)


def test_wrong_bom_format_fails(tmp_path: Path) -> None:
    payload = _minimal_sbom()
    payload["bomFormat"] = "SPDX"
    (tmp_path / "backend.cdx.json").write_text(json.dumps(payload), encoding="utf-8")
    findings = validate_sbom_file(tmp_path / "backend.cdx.json")
    assert any("bomFormat must be CycloneDX" in finding.reason for finding in findings)


def test_unsupported_spec_version_fails(tmp_path: Path) -> None:
    payload = _minimal_sbom(spec_version="9.9")
    (tmp_path / "backend.cdx.json").write_text(json.dumps(payload), encoding="utf-8")
    findings = validate_sbom_file(tmp_path / "backend.cdx.json")
    assert any("specVersion" in finding.reason for finding in findings)


def test_components_must_be_list(tmp_path: Path) -> None:
    payload = _minimal_sbom()
    payload["components"] = {}
    (tmp_path / "backend.cdx.json").write_text(json.dumps(payload), encoding="utf-8")
    findings = validate_sbom_file(tmp_path / "backend.cdx.json")
    assert any("components must be a list" in finding.reason for finding in findings)


def test_component_missing_name_fails(tmp_path: Path) -> None:
    payload = _minimal_sbom()
    payload["components"] = [{"version": "1.0.0"}]
    (tmp_path / "backend.cdx.json").write_text(json.dumps(payload), encoding="utf-8")
    findings = validate_sbom_file(tmp_path / "backend.cdx.json")
    assert any("must include non-empty name" in finding.reason for finding in findings)


def test_oversized_file_fails(tmp_path: Path) -> None:
    payload = _minimal_sbom()
    (tmp_path / "backend.cdx.json").write_bytes(json.dumps(payload).encode("utf-8") + (b"x" * (MAX_FILE_BYTES + 1)))
    findings = validate_sbom_file(tmp_path / "backend.cdx.json")
    assert any("maximum allowed size" in finding.reason for finding in findings)


def test_too_many_components_fails(tmp_path: Path) -> None:
    payload = _minimal_sbom()
    payload["components"] = [{"name": f"pkg-{index}", "version": "1.0.0"} for index in range(MAX_COMPONENTS + 1)]
    (tmp_path / "backend.cdx.json").write_text(json.dumps(payload), encoding="utf-8")
    findings = validate_sbom_file(tmp_path / "backend.cdx.json")
    assert any("maximum allowed count" in finding.reason for finding in findings)


def test_absolute_host_path_fails(tmp_path: Path) -> None:
    payload = _minimal_sbom()
    payload["metadata"] = {"properties": [{"value": "/Users/secret/path"}]}
    (tmp_path / "backend.cdx.json").write_text(json.dumps(payload), encoding="utf-8")
    findings = validate_sbom_file(tmp_path / "backend.cdx.json")
    assert any("absolute host path" in finding.reason for finding in findings)


@pytest.mark.parametrize(
    "needle",
    [
        "access_token=abc",
        "refresh_token=abc",
        "client_secret=abc",
        "AMAZON_LWA_CLIENT_SECRET=abc",
        "JWT_SECRET=abc",
        "spapi_oauth_code=abc",
    ],
)
def test_secret_like_content_fails(tmp_path: Path, needle: str) -> None:
    payload = _minimal_sbom()
    payload["metadata"] = {"note": needle}
    (tmp_path / "backend.cdx.json").write_text(json.dumps(payload), encoding="utf-8")
    findings = validate_sbom_file(tmp_path / "backend.cdx.json")
    assert any("secret-like content" in finding.reason for finding in findings)


def test_error_output_does_not_echo_secret_canary(tmp_path: Path) -> None:
    payload = _minimal_sbom()
    payload["metadata"] = {"note": SECRET_CANARY}
    (tmp_path / "backend.cdx.json").write_text(json.dumps(payload), encoding="utf-8")
    stderr_buffer = io.StringIO()
    with redirect_stderr(stderr_buffer):
        exit_code = main([str(tmp_path)])
    output = stderr_buffer.getvalue()
    assert exit_code == 1
    assert SECRET_CANARY not in output


def test_main_success_message(tmp_path: Path) -> None:
    _write_sboms(tmp_path)
    assert main([str(tmp_path)]) == 0


def test_invalid_component_field_types_fail(tmp_path: Path) -> None:
    payload = _minimal_sbom()
    payload["components"] = [{"name": "pkg", "version": 1, "purl": 2}]
    (tmp_path / "backend.cdx.json").write_text(json.dumps(payload), encoding="utf-8")
    findings = validate_sbom_file(tmp_path / "backend.cdx.json")
    assert any("version must be a string" in finding.reason for finding in findings)
    assert any("purl must be a string" in finding.reason for finding in findings)


def test_symlink_input_is_rejected(tmp_path: Path) -> None:
    real_file = tmp_path / "backend.cdx.json"
    real_file.write_text(json.dumps(_minimal_sbom()), encoding="utf-8")
    symlink = tmp_path / "backend-link.cdx.json"
    symlink.symlink_to(real_file)
    findings = validate_sbom_file(symlink)
    assert any("regular file" in finding.reason for finding in findings)


def test_excessive_json_depth_fails(tmp_path: Path) -> None:
    nested: object = {"name": "leaf", "version": "1.0.0"}
    for _ in range(40):
        nested = {"components": [nested]}
    payload = _minimal_sbom()
    payload["metadata"] = nested
    (tmp_path / "backend.cdx.json").write_text(json.dumps(payload), encoding="utf-8")
    findings = validate_sbom_file(tmp_path / "backend.cdx.json")
    assert any("maximum JSON nesting depth" in finding.reason for finding in findings)


def test_oversized_string_value_fails(tmp_path: Path) -> None:
    payload = _minimal_sbom()
    payload["metadata"] = {"note": "x" * 9000}
    (tmp_path / "backend.cdx.json").write_text(json.dumps(payload), encoding="utf-8")
    findings = validate_sbom_file(tmp_path / "backend.cdx.json")
    assert any("oversized string" in finding.reason for finding in findings)


def test_nested_property_secret_fails(tmp_path: Path) -> None:
    payload = _minimal_sbom()
    payload["metadata"] = {"properties": [{"name": "token", "value": "client_secret=abc"}]}
    (tmp_path / "backend.cdx.json").write_text(json.dumps(payload), encoding="utf-8")
    findings = validate_sbom_file(tmp_path / "backend.cdx.json")
    assert any("secret-like content" in finding.reason for finding in findings)


def test_external_reference_userinfo_fails(tmp_path: Path) -> None:
    payload = _minimal_sbom()
    payload["externalReferences"] = [{"url": "https://user:pass@example.com/repo"}]
    (tmp_path / "backend.cdx.json").write_text(json.dumps(payload), encoding="utf-8")
    findings = validate_sbom_file(tmp_path / "backend.cdx.json")
    assert any("URL userinfo" in finding.reason for finding in findings)
