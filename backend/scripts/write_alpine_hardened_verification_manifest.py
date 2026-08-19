"""Write hardened Alpine candidate verification manifests for CI artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Literal

MANIFEST_SCHEMA_VERSION = 1

VerificationLevel = Literal["runtime_smoke", "build_only"]
Architecture = Literal["amd64", "arm64"]


def write_manifest(
    *,
    output_path: Path,
    architecture: Architecture,
    verification_level: VerificationLevel,
    checks: dict[str, bool],
    apk_inventory: list[str] | None = None,
    image_digest: str | None = None,
) -> None:
    payload: dict[str, object] = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "architecture": architecture,
        "verification_level": verification_level,
        "checks": checks,
        "apk_inventory": sorted(apk_inventory or []),
    }
    if image_digest is not None:
        payload["image_digest"] = image_digest
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("architecture", choices=("amd64", "arm64"))
    parser.add_argument("verification_level", choices=("runtime_smoke", "build_only"))
    parser.add_argument("output_path", type=Path)
    parser.add_argument("--check", action="append", default=[], metavar="NAME=BOOL")
    parser.add_argument("--apk-inventory-file", type=Path, default=None)
    parser.add_argument("--image-digest", default=None)
    args = parser.parse_args()

    checks: dict[str, bool] = {}
    for item in args.check:
        if "=" not in item:
            print("CHECK_FORMAT_INVALID", file=sys.stderr)
            return 1
        name, raw_value = item.split("=", 1)
        name = name.strip()
        if not name:
            print("CHECK_NAME_INVALID", file=sys.stderr)
            return 1
        if raw_value.lower() not in {"true", "false"}:
            print("CHECK_VALUE_INVALID", file=sys.stderr)
            return 1
        checks[name] = raw_value.lower() == "true"

    inventory: list[str] | None = None
    if args.apk_inventory_file is not None:
        if not args.apk_inventory_file.is_file():
            print("APK_INVENTORY_FILE_MISSING", file=sys.stderr)
            return 1
        inventory = [
            line.strip()
            for line in args.apk_inventory_file.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    write_manifest(
        output_path=args.output_path,
        architecture=args.architecture,
        verification_level=args.verification_level,
        checks=checks,
        apk_inventory=inventory,
        image_digest=args.image_digest,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
