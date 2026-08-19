"""Cross-platform arm64 musllinux wheel resolution audit for Alpine candidate base."""

from __future__ import annotations

import hashlib
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from alpine_wheel_audit_common import (
    finalize_manifest_exit,
    normalize_package_name,
    parse_direct_requirements,
    requirements_sha256,
)

DEFAULT_REQUIREMENTS = Path(__file__).resolve().parents[1] / "requirements.txt"

PLATFORM_TAGS = (
    "musllinux_1_2_aarch64",
    "musllinux_1_1_aarch64",
)
PYTHON_VERSION = "3.11"
ABIS = ("cp311", "cp311-abi3", "abi3", "none")


@dataclass(frozen=True)
class WheelRecord:
    package: str
    version: str
    wheel_tag: str
    sha256: str

    def as_dict(self) -> dict[str, object]:
        return {
            "package": self.package,
            "version": self.version,
            "wheel_tag": self.wheel_tag,
            "sha256": self.sha256,
            "binary": True,
            "source": False,
            "install_status": "NOT_EXECUTED_CROSS_ARCH",
            "import_status": "NOT_EXECUTED_CROSS_ARCH",
        }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _wheel_record(path: Path) -> WheelRecord:
    stem = path.name[: -len(".whl")]
    parts = stem.split("-")
    if len(parts) < 5:
        raise ValueError("unexpected wheel filename")
    return WheelRecord(
        package=parts[0].replace("_", "-"),
        version=parts[1],
        wheel_tag=parts[-1],
        sha256=_sha256_file(path),
    )


def _download_arm64_wheels(requirements: Path, wheel_dir: Path) -> tuple[list[WheelRecord], list[str]]:
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

    records = [_wheel_record(path) for path in sorted(wheel_dir.glob("*.whl"))]
    sdist_count = sum(1 for path in wheel_dir.iterdir() if path.suffix != ".whl")
    if sdist_count:
        raise RuntimeError("sdist artifact present")

    platforms_used = list(PLATFORM_TAGS)
    if records and not any("musllinux_1_2_aarch64" in record.wheel_tag for record in records):
        platforms_used.append("musllinux_1_1_aarch64_required_for_resolution")
    return records, platforms_used


def _missing_direct_requirements(requirements: Path, records: list[WheelRecord]) -> list[str]:
    downloaded = {normalize_package_name(record.package) for record in records}
    missing: list[str] = []
    for package in parse_direct_requirements(requirements):
        if package not in downloaded:
            missing.append(package)
    return sorted(missing)


def _base_payload(req_sha: str, direct_count: int) -> dict[str, object]:
    return {
        "schema_version": 1,
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
                "wheels": [record.as_dict() for record in records],
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
