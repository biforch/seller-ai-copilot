"""Cross-platform arm64 musllinux wheel resolution audit for Alpine candidate base."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from alpine_wheel_audit_common import (
    WHEEL_MANIFEST_SCHEMA_VERSION,
    finalize_manifest_exit,
    normalize_package_name,
    parse_direct_requirements,
    requirements_sha256,
    wheel_records_from_directory,
)

DEFAULT_REQUIREMENTS = Path(__file__).resolve().parents[1] / "requirements.txt"

PLATFORM_TAGS = (
    "musllinux_1_2_aarch64",
    "musllinux_1_1_aarch64",
)
PYTHON_VERSION = "3.11"
ABIS = ("cp311", "cp311-abi3", "abi3", "none")


def _download_arm64_wheels(requirements: Path, wheel_dir: Path) -> tuple[list, list[str]]:
    command = [
        sys.executable,
        "-m",
        "pip",
        "download",
        "--only-binary=:all:",
        "-r",
        str(requirements),
        "-d",
        str(wheel_dir),
        f"--python-version={PYTHON_VERSION}",
        "--implementation=cp",
    ]
    for platform_tag in PLATFORM_TAGS:
        command.extend(["--platform", platform_tag])
    for abi in ABIS:
        command.extend(["--abi", abi])

    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        raise RuntimeError("pip download failed")

    records = wheel_records_from_directory(wheel_dir)
    sdist_count = sum(1 for path in wheel_dir.iterdir() if path.suffix != ".whl")
    if sdist_count:
        raise RuntimeError("sdist artifact present")

    platforms_used = list(PLATFORM_TAGS)
    if records and not any(
        any("musllinux_1_2_aarch64" in tag for tag in record.wheel_tags) for record in records
    ):
        platforms_used.append("musllinux_1_1_aarch64_required_for_resolution")
    return records, platforms_used


def _missing_direct_requirements(requirements: Path, records: list) -> list[str]:
    downloaded = {normalize_package_name(record.package) for record in records}
    missing: list[str] = []
    for package in parse_direct_requirements(requirements):
        if package not in downloaded:
            missing.append(package)
    return sorted(missing)


def _base_payload(req_sha: str, direct_count: int) -> dict[str, object]:
    return {
        "schema_version": WHEEL_MANIFEST_SCHEMA_VERSION,
        "architecture": "arm64",
        "platform": "linux/arm64",
        "python_version": PYTHON_VERSION,
        "musl": True,
        "mode": "resolution_only",
        "requirements_sha256": req_sha,
        "dependency_validation_method": "wheel_resolution_only",
        "download_status": "failed",
        "resolution_status": "failed",
        "wheel_count": 0,
        "sdist_count": 0,
        "resolved_package_count": direct_count,
        "missing_binary_package_count": direct_count,
        "missing_packages": [],
        "platform_tags_used": list(PLATFORM_TAGS),
        "status": "failed",
        "reason_code": "WHEEL_RESOLUTION_FAILED",
        "wheels": [],
    }


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    requirements = Path(args[0]) if args else DEFAULT_REQUIREMENTS
    output = Path(args[1]) if len(args) > 1 else Path("wheel-arm64.json")
    wheelhouse = Path(args[2]) if len(args) > 2 else output.parent / "staging-arm64" / "wheelhouse"
    if not requirements.is_file():
        print("requirements file missing", file=sys.stderr)
        return 2

    req_sha = requirements_sha256(requirements)
    direct_requirements = parse_direct_requirements(requirements)
    payload = _base_payload(req_sha, len(direct_requirements))
    payload["missing_packages"] = list(direct_requirements)

    try:
        wheelhouse.mkdir(parents=True, exist_ok=True)
        records, platforms_used = _download_arm64_wheels(requirements, wheelhouse)
        missing = _missing_direct_requirements(requirements, records)
        payload.update(
            {
                "platform_tags_used": platforms_used,
                "download_status": "ok",
                "wheel_count": len(records),
                "sdist_count": 0,
                "missing_packages": missing,
                "missing_binary_package_count": len(missing),
                    "wheels": [
                        record.as_dict(
                            extra={
                                "install_status": "NOT_EXECUTED_CROSS_ARCH",
                                "import_status": "NOT_EXECUTED_CROSS_ARCH",
                            }
                        )
                        for record in records
                    ],
                "resolution_status": "ok" if not missing else "failed",
            }
        )
        if missing:
            payload["reason_code"] = "MISSING_BINARY_WHEEL"
        else:
            payload["status"] = "passed"
            payload["reason_code"] = "WHEEL_RESOLUTION_OK"
    except RuntimeError:
        payload["status"] = "failed"

    exit_code = finalize_manifest_exit(output, payload)
    if payload["status"] == "passed":
        print("wheel-arm64 manifest written")
    else:
        print("wheel-arm64 manifest recorded failure", file=sys.stderr)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
