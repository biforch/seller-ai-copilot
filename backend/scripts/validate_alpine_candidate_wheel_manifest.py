"""Validate Alpine candidate wheel audit manifests."""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_WHEELS = 500
MAX_STRING_LENGTH = 512
MAX_JSON_DEPTH = 24
MAX_JSON_NODES = 5000

REQUIRED_NATIVE_PACKAGES = frozenset(
    {
        "cryptography",
        "psycopg2-binary",
        "bcrypt",
        "pydantic-core",
        "cffi",
        "uvloop",
        "httptools",
        "watchfiles",
    }
)

SECRET_PATTERNS = (
    re.compile(r"access_token", re.IGNORECASE),
    re.compile(r"refresh_token", re.IGNORECASE),
    re.compile(r"client_secret", re.IGNORECASE),
    re.compile(r"eyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}"),
)
URL_USERINFO_PATTERN = re.compile(r"[a-z][a-z0-9+.-]*://[^/\s:@]+:[^/\s@]+@")
HOST_PATH_PATTERN = re.compile(
    r"(^/Users/|^/home/runner/work/|^[A-Za-z]:\\Users\\|^\$\{RUNNER_TEMP\}|^/input/|^/output/)"
)
SENSITIVE_KEY_PATTERN = re.compile(
    r"(?i)(password|secret|token|api[_-]?key|authorization|credential|oauth|jwt|private[_-]?key)$"
)
CONTROL_CHAR_PATTERN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
PACKAGE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
REASON_CODE_PATTERN = re.compile(r"^[A-Z0-9_]+$")

SUCCESS_MESSAGE = "Alpine candidate wheel manifest validation passed"


@dataclass(frozen=True)
class Finding:
    filename: str
    reason: str


def _inspect_string(value: str, filename: str) -> list[Finding]:
    findings: list[Finding] = []
    if len(value) > MAX_STRING_LENGTH:
        findings.append(Finding(filename, "string value exceeds maximum length"))
    if CONTROL_CHAR_PATTERN.search(value):
        findings.append(Finding(filename, "manifest contains control characters"))
    if HOST_PATH_PATTERN.search(value):
        findings.append(Finding(filename, "manifest contains absolute host path"))
    if URL_USERINFO_PATTERN.search(value):
        findings.append(Finding(filename, "manifest contains URL userinfo"))
    for pattern in SECRET_PATTERNS:
        if pattern.search(value):
            findings.append(Finding(filename, "manifest contains forbidden secret-like content"))
            break
    return findings


def _count_json_nodes(value: object, *, depth: int = 0) -> tuple[int, int]:
    if depth > MAX_JSON_DEPTH:
        return MAX_JSON_NODES + 1, depth
    if isinstance(value, dict):
        count = 1
        max_depth = depth
        for child in value.values():
            child_count, child_depth = _count_json_nodes(child, depth=depth + 1)
            count += child_count
            max_depth = max(max_depth, child_depth)
        return count, max_depth
    if isinstance(value, list):
        count = 1
        max_depth = depth
        for item in value:
            child_count, child_depth = _count_json_nodes(item, depth=depth + 1)
            count += child_count
            max_depth = max(max_depth, child_depth)
        return count, max_depth
    return 1, depth


def _validate_wheel_entry(entry: object, filename: str, index: int) -> list[Finding]:
    findings: list[Finding] = []
    if not isinstance(entry, dict):
        return [Finding(filename, f"wheels[{index}] must be an object")]
    package = entry.get("package")
    version = entry.get("version")
    wheel_tag = entry.get("wheel_tag")
    sha256 = entry.get("sha256")
    binary = entry.get("binary")
    source = entry.get("source")
    for field_name, value in (
        ("package", package),
        ("version", version),
        ("wheel_tag", wheel_tag),
        ("sha256", sha256),
    ):
        if not isinstance(value, str) or not value.strip():
            findings.append(Finding(filename, f"wheels[{index}].{field_name} must be a non-empty string"))
        elif isinstance(value, str):
            findings.extend(_inspect_string(value, filename))
    if isinstance(package, str) and not PACKAGE_NAME_PATTERN.fullmatch(package):
        findings.append(Finding(filename, f"wheels[{index}].package has invalid format"))
    if isinstance(sha256, str) and not SHA256_PATTERN.fullmatch(sha256):
        findings.append(Finding(filename, f"wheels[{index}].sha256 must be lowercase hex sha256"))
    if binary is not True:
        findings.append(Finding(filename, f"wheels[{index}] must be binary wheel"))
    if source is not False:
        findings.append(Finding(filename, f"wheels[{index}] must not be source distribution"))
    if isinstance(wheel_tag, str):
        if filename.startswith("wheel-amd64") and "x86_64" not in wheel_tag and "amd64" not in wheel_tag:
            if "manylinux" not in wheel_tag and "py3-none-any" not in wheel_tag:
                findings.append(Finding(filename, f"wheels[{index}] tag is not amd64-compatible"))
        if filename.startswith("wheel-arm64") and "aarch64" not in wheel_tag and "arm64" not in wheel_tag:
            if "py3-none-any" not in wheel_tag and "manylinux" not in wheel_tag:
                findings.append(Finding(filename, f"wheels[{index}] tag is not arm64-compatible"))
    return findings


def _inspect_manifest_value(value: object, filename: str, *, depth: int = 0) -> list[Finding]:
    findings: list[Finding] = []
    if depth > MAX_JSON_DEPTH:
        findings.append(Finding(filename, "manifest exceeds maximum JSON depth"))
        return findings
    if isinstance(value, str):
        findings.extend(_inspect_string(value, filename))
        return findings
    if isinstance(value, dict):
        for key, child in value.items():
            if isinstance(key, str) and SENSITIVE_KEY_PATTERN.search(key):
                findings.append(Finding(filename, "manifest contains sensitive key"))
            findings.extend(_inspect_manifest_value(child, filename, depth=depth + 1))
        return findings
    if isinstance(value, list):
        for item in value:
            findings.extend(_inspect_manifest_value(item, filename, depth=depth + 1))
    return findings


def _validate_common_fields(payload: dict[str, object], filename: str) -> list[Finding]:
    findings: list[Finding] = []
    if payload.get("schema_version") != 1:
        findings.append(Finding(filename, "schema_version must be 1"))
    architecture = payload.get("architecture")
    if filename == "wheel-amd64.json" and architecture != "amd64":
        findings.append(Finding(filename, "architecture must be amd64"))
    if filename == "wheel-arm64.json" and architecture != "arm64":
        findings.append(Finding(filename, "architecture must be arm64"))
    if payload.get("python_version") != "3.11":
        findings.append(Finding(filename, "python_version must be 3.11"))
    if payload.get("musl") is not True:
        findings.append(Finding(filename, "musl must be true"))
    req_sha = payload.get("requirements_sha256")
    if not isinstance(req_sha, str) or not SHA256_PATTERN.fullmatch(req_sha):
        findings.append(Finding(filename, "requirements_sha256 must be lowercase hex sha256"))
    sdist_count = payload.get("sdist_count")
    if sdist_count != 0:
        findings.append(Finding(filename, "sdist_count must be 0"))
    reason_code = payload.get("reason_code")
    if not isinstance(reason_code, str) or not REASON_CODE_PATTERN.fullmatch(reason_code):
        findings.append(Finding(filename, "reason_code must be uppercase token"))
    return findings


def _validate_manifest_file(path: Path) -> list[Finding]:
    filename = path.name
    if path.is_symlink():
        return [Finding(filename, "wheel manifest must not be a symlink")]
    if not path.is_file():
        return [Finding(filename, "required wheel manifest is missing")]
    raw = path.read_bytes()
    if len(raw) > MAX_FILE_BYTES:
        return [Finding(filename, "manifest exceeds maximum allowed size")]
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return [Finding(filename, "manifest is not valid UTF-8 JSON")]

    if not isinstance(payload, dict):
        return [Finding(filename, "manifest root must be a JSON object")]

    node_count, max_depth = _count_json_nodes(payload)
    findings: list[Finding] = []
    if node_count > MAX_JSON_NODES:
        findings.append(Finding(filename, "manifest exceeds maximum JSON node count"))
    if max_depth > MAX_JSON_DEPTH:
        findings.append(Finding(filename, "manifest exceeds maximum JSON depth"))

    findings.extend(_inspect_manifest_value(payload, filename))
    findings.extend(_validate_common_fields(payload, filename))

    wheels = payload.get("wheels")
    if not isinstance(wheels, list):
        return findings + [Finding(filename, "wheels must be a list")]
    if len(wheels) > MAX_WHEELS:
        findings.append(Finding(filename, "wheels exceed maximum allowed count"))
    if not wheels:
        findings.append(Finding(filename, "wheels must not be empty"))

    wheel_count = payload.get("wheel_count")
    if wheel_count != len(wheels):
        findings.append(Finding(filename, "wheel_count must match wheels list length"))

    packages_present: set[str] = set()
    for index, entry in enumerate(wheels):
        findings.extend(_validate_wheel_entry(entry, filename, index))
        if isinstance(entry, dict) and isinstance(entry.get("package"), str):
            packages_present.add(entry["package"].lower())

    if filename == "wheel-amd64.json":
        if payload.get("download_status") != "ok":
            findings.append(Finding(filename, "download_status must be ok"))
        if payload.get("install_status") != "ok":
            findings.append(Finding(filename, "install_status must be ok"))
        pip_check_status = payload.get("pip_check_status")
        if pip_check_status != "ok":
            findings.append(Finding(filename, "pip_check_status must be ok"))
        if payload.get("import_status") != "ok":
            findings.append(Finding(filename, "import_status must be ok"))
        if payload.get("smoke_status") != "ok":
            findings.append(Finding(filename, "smoke_status must be ok"))
        imports = payload.get("imports")
        if not isinstance(imports, list) or not imports:
            findings.append(Finding(filename, "imports must be a non-empty list"))
        elif isinstance(imports, list):
            for item in imports:
                if not isinstance(item, dict) or item.get("status") != "ok":
                    findings.append(Finding(filename, "all imports must succeed"))
                    break
        smoke = payload.get("smoke")
        if not isinstance(smoke, dict):
            findings.append(Finding(filename, "smoke must be an object"))
        elif isinstance(smoke, dict):
            for key, value in smoke.items():
                if value != "ok":
                    findings.append(Finding(filename, f"smoke check {key} must be ok"))
        if payload.get("reason_code") != "WHEEL_AUDIT_OK":
            findings.append(Finding(filename, "reason_code must be WHEEL_AUDIT_OK"))

    if filename == "wheel-arm64.json":
        if payload.get("mode") != "resolution_only":
            findings.append(Finding(filename, "mode must be resolution_only"))
        if payload.get("resolution_status") != "ok":
            findings.append(Finding(filename, "resolution_status must be ok"))
        missing = payload.get("missing_packages")
        if not isinstance(missing, list) or missing:
            findings.append(Finding(filename, "missing_packages must be an empty list"))
        for entry in wheels if isinstance(wheels, list) else []:
            if isinstance(entry, dict) and entry.get("import_status") != "NOT_EXECUTED_CROSS_ARCH":
                findings.append(Finding(filename, "arm64 import_status must remain NOT_EXECUTED_CROSS_ARCH"))
        if payload.get("reason_code") != "WHEEL_RESOLUTION_OK":
            findings.append(Finding(filename, "reason_code must be WHEEL_RESOLUTION_OK"))

    for package in REQUIRED_NATIVE_PACKAGES:
        normalized = package.lower()
        if normalized not in packages_present and normalized.replace("-", "_") not in packages_present:
            findings.append(Finding(filename, f"required native package missing: {package}"))

    return findings


def validate_wheel_manifests(directory: Path) -> list[Finding]:
    findings: list[Finding] = []
    manifests: dict[str, dict[str, object]] = {}
    for filename in ("wheel-amd64.json", "wheel-arm64.json"):
        path = directory / filename
        file_findings = _validate_manifest_file(path)
        findings.extend(file_findings)
        if path.is_file() and not path.is_symlink():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(payload, dict):
                    manifests[filename] = payload
            except json.JSONDecodeError:
                pass

    amd64_sha = manifests.get("wheel-amd64.json", {}).get("requirements_sha256")
    arm64_sha = manifests.get("wheel-arm64.json", {}).get("requirements_sha256")
    if isinstance(amd64_sha, str) and isinstance(arm64_sha, str) and amd64_sha != arm64_sha:
        findings.append(Finding("wheel-arm64.json", "requirements_sha256 must match wheel-amd64 manifest"))
    return findings


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1:
        print("usage: validate_alpine_candidate_wheel_manifest.py <output-directory>", file=sys.stderr)
        return 2

    findings = validate_wheel_manifests(Path(args[0]))
    if findings:
        for finding in findings:
            print(f"{finding.filename}: {finding.reason}", file=sys.stderr)
        return 1

    print(f"{SUCCESS_MESSAGE} (2 manifests)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
