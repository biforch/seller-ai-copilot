"""Validate CycloneDX SBOM artifacts produced by the supply-chain scan pipeline."""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

REQUIRED_FILES = ("backend.cdx.json", "frontend.cdx.json", "nginx.cdx.json")
ALLOWED_SPEC_VERSIONS = frozenset({"1.4", "1.5", "1.6"})
MAX_FILE_BYTES = 50 * 1024 * 1024
MAX_COMPONENTS = 50_000
MAX_JSON_DEPTH = 32
MAX_STRING_LENGTH = 8_192

SECRET_VALUE_PATTERNS = (
    re.compile(r"access_token", re.IGNORECASE),
    re.compile(r"refresh_token", re.IGNORECASE),
    re.compile(r"client_secret", re.IGNORECASE),
    re.compile(r"authorization:\s*bearer", re.IGNORECASE),
    re.compile(r"eyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}"),
    re.compile(r"spapi_oauth_code", re.IGNORECASE),
    re.compile(r"AMAZON_LWA_CLIENT_SECRET", re.IGNORECASE),
    re.compile(r"JWT_SECRET", re.IGNORECASE),
)
SENSITIVE_KEY_PATTERN = re.compile(
    r"(?i)(password|secret|token|api[_-]?key|authorization|credential|oauth|jwt|private[_-]?key)$"
)
ABSOLUTE_PATH_PATTERN = re.compile(
    r"(/Users/|/home/|[A-Za-z]:\\|/home/runner/work/|\$\{RUNNER_TEMP\})"
)
URL_USERINFO_PATTERN = re.compile(r"[a-z][a-z0-9+.-]*://[^/\s:@]+:[^/\s@]+@")
CONTROL_CHAR_PATTERN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

SUCCESS_MESSAGE = "SBOM artifact validation passed"


@dataclass(frozen=True)
class Finding:
    filename: str
    reason: str


def _validate_component(component: object, filename: str, index: int) -> list[Finding]:
    findings: list[Finding] = []
    if not isinstance(component, dict):
        return [Finding(filename, f"components[{index}] must be an object")]

    name = component.get("name")
    if not isinstance(name, str) or not name.strip():
        findings.append(Finding(filename, f"components[{index}] must include non-empty name"))

    version = component.get("version")
    if version is not None and not isinstance(version, str):
        findings.append(Finding(filename, f"components[{index}].version must be a string when present"))

    purl = component.get("purl")
    if purl is not None and not isinstance(purl, str):
        findings.append(Finding(filename, f"components[{index}].purl must be a string when present"))

    nested = component.get("components")
    if nested is not None and not isinstance(nested, list):
        findings.append(Finding(filename, f"components[{index}].components must be a list when present"))

    return findings


def _inspect_json_value(
    value: object,
    filename: str,
    *,
    depth: int,
    key: str | None = None,
) -> list[Finding]:
    findings: list[Finding] = []
    if depth > MAX_JSON_DEPTH:
        return [Finding(filename, "artifact exceeds maximum JSON nesting depth")]

    if isinstance(value, str):
        if len(value) > MAX_STRING_LENGTH:
            findings.append(Finding(filename, "artifact contains oversized string value"))
        if CONTROL_CHAR_PATTERN.search(value):
            findings.append(Finding(filename, "artifact contains control characters"))
        if ABSOLUTE_PATH_PATTERN.search(value):
            findings.append(Finding(filename, "artifact contains absolute host path"))
        if URL_USERINFO_PATTERN.search(value):
            findings.append(Finding(filename, "artifact contains URL userinfo"))
        if key and SENSITIVE_KEY_PATTERN.search(key):
            findings.append(Finding(filename, "artifact contains sensitive key"))
        for pattern in SECRET_VALUE_PATTERNS:
            if pattern.search(value):
                findings.append(Finding(filename, "artifact contains forbidden secret-like content"))
                break
        return findings

    if isinstance(value, dict):
        for child_key, child_value in value.items():
            if not isinstance(child_key, str):
                findings.append(Finding(filename, "artifact contains non-string object key"))
                continue
            findings.extend(
                _inspect_json_value(child_value, filename, depth=depth + 1, key=child_key)
            )
        return findings

    if isinstance(value, list):
        for item in value:
            findings.extend(_inspect_json_value(item, filename, depth=depth + 1, key=key))
        return findings

    return findings


def validate_sbom_file(path: Path) -> list[Finding]:
    filename = path.name
    findings: list[Finding] = []

    if path.is_symlink():
        return [Finding(filename, "required SBOM artifact must be a regular file")]
    if not path.is_file():
        return [Finding(filename, "required SBOM artifact is missing")]

    raw = path.read_bytes()
    if len(raw) > MAX_FILE_BYTES:
        return [Finding(filename, "artifact exceeds maximum allowed size")]

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return [Finding(filename, "artifact must be UTF-8 encoded JSON")]

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return [Finding(filename, "artifact is not valid JSON")]

    if not isinstance(payload, dict):
        return [Finding(filename, "artifact root must be a JSON object")]

    findings.extend(_inspect_json_value(payload, filename, depth=0))

    bom_format = payload.get("bomFormat")
    if bom_format != "CycloneDX":
        findings.append(Finding(filename, "bomFormat must be CycloneDX"))

    spec_version = payload.get("specVersion")
    if not isinstance(spec_version, str) or spec_version not in ALLOWED_SPEC_VERSIONS:
        findings.append(Finding(filename, "specVersion is missing or not allowlisted"))

    components = payload.get("components")
    if not isinstance(components, list):
        findings.append(Finding(filename, "components must be a list"))
        return findings

    if len(components) > MAX_COMPONENTS:
        findings.append(Finding(filename, "components exceed maximum allowed count"))

    for index, component in enumerate(components):
        findings.extend(_validate_component(component, filename, index))
        if isinstance(component, dict):
            nested = component.get("components")
            if isinstance(nested, list):
                for nested_index, nested_component in enumerate(nested):
                    findings.extend(_validate_component(nested_component, filename, nested_index))

    return findings


def validate_sbom_directory(directory: Path) -> tuple[list[Finding], int]:
    findings: list[Finding] = []
    checked = 0

    for filename in REQUIRED_FILES:
        checked += 1
        findings.extend(validate_sbom_file(directory / filename))

    return findings, checked


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1:
        print("usage: validate_sbom_artifacts.py <output-directory>", file=sys.stderr)
        return 2

    directory = Path(args[0])
    findings, checked = validate_sbom_directory(directory)
    if findings:
        for finding in findings:
            print(f"{finding.filename}: {finding.reason}", file=sys.stderr)
        return 1

    print(f"{SUCCESS_MESSAGE} ({checked} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
