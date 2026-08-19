"""Fail-closed validation for hardened Alpine candidate verification manifests."""

from __future__ import annotations

import json
import sys
from pathlib import Path

SUCCESS_MESSAGE = "alpine hardened verification manifest validation passed"

ALLOWED_ARCHITECTURES = frozenset({"amd64", "arm64"})
ALLOWED_LEVELS = frozenset({"runtime_smoke", "build_only"})

AMD64_REQUIRED_CHECKS = frozenset(
    {
        "runtime_environment",
        "alpine_os_packages",
        "production_smoke",
        "hardened_smoke",
        "uvicorn_health",
        "non_root_user",
    }
)

ARM64_BUILD_ONLY_CHECKS = frozenset(
    {
        "image_config",
        "runtime_environment",
        "alpine_os_packages",
        "non_root_user",
    }
)


class ManifestValidationError(Exception):
    reason_code: str

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


def _load_manifest(path: Path) -> dict[str, object]:
    if not path.is_file():
        raise ManifestValidationError("MANIFEST_MISSING")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        raise ManifestValidationError("MANIFEST_MALFORMED") from None
    if not isinstance(payload, dict):
        raise ManifestValidationError("MANIFEST_MALFORMED")
    return payload


def validate_manifest(path: Path) -> None:
    payload = _load_manifest(path)

    schema_version = payload.get("schema_version")
    if schema_version != 1:
        raise ManifestValidationError("SCHEMA_VERSION_INVALID")

    architecture = payload.get("architecture")
    if not isinstance(architecture, str) or architecture not in ALLOWED_ARCHITECTURES:
        raise ManifestValidationError("ARCHITECTURE_INVALID")

    level = payload.get("verification_level")
    if not isinstance(level, str) or level not in ALLOWED_LEVELS:
        raise ManifestValidationError("VERIFICATION_LEVEL_INVALID")

    checks = payload.get("checks")
    if not isinstance(checks, dict):
        raise ManifestValidationError("CHECKS_INVALID")

    normalized_checks: dict[str, bool] = {}
    for key, value in checks.items():
        if not isinstance(key, str) or not key:
            raise ManifestValidationError("CHECK_KEY_INVALID")
        if not isinstance(value, bool):
            raise ManifestValidationError("CHECK_VALUE_INVALID")
        normalized_checks[key] = value

    inventory = payload.get("apk_inventory")
    if not isinstance(inventory, list) or not all(isinstance(item, str) for item in inventory):
        raise ManifestValidationError("APK_INVENTORY_INVALID")

    forbidden_hits = [
        name
        for name in inventory
        if name.startswith("perl") or name.startswith("util-linux") or name in {"gcc", "musl-dev", "build-base"}
    ]
    if forbidden_hits:
        raise ManifestValidationError("FORBIDDEN_APK_IN_INVENTORY")

    if architecture == "amd64":
        if level != "runtime_smoke":
            raise ManifestValidationError("AMD64_LEVEL_INVALID")
        missing = AMD64_REQUIRED_CHECKS - normalized_checks.keys()
        if missing:
            raise ManifestValidationError("AMD64_CHECKS_INCOMPLETE")
    else:
        if level != "build_only":
            raise ManifestValidationError("ARM64_LEVEL_INVALID")
        missing = ARM64_BUILD_ONLY_CHECKS - normalized_checks.keys()
        if missing:
            raise ManifestValidationError("ARM64_CHECKS_INCOMPLETE")

    for key, value in normalized_checks.items():
        if not value:
            raise ManifestValidationError(f"CHECK_FAILED:{key}")


def main() -> int:
    if len(sys.argv) != 2:
        print("USAGE_INVALID", file=sys.stderr)
        return 1
    try:
        validate_manifest(Path(sys.argv[1]))
    except ManifestValidationError as exc:
        print(exc.reason_code, file=sys.stderr)
        return 1
    except Exception:
        print("MANIFEST_VALIDATION_FAILED", file=sys.stderr)
        return 1
    print(SUCCESS_MESSAGE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
