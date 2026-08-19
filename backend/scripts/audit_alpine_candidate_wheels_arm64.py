"""Cross-platform arm64 musllinux wheel resolution audit for Alpine candidate base."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

DEFAULT_REQUIREMENTS = Path(__file__).resolve().parents[1] / "requirements.txt"

PLATFORM_TAGS = (
    "musllinux_1_2_aarch64",
    "musllinux_1_1_aarch64",
)
PYTHON_VERSION = "3.11"
ABIS = ("cp311", "cp311-abi3", "abi3", "none")

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


@dataclass(frozen=True)
class WheelRecord:
    package: str
    version: str
    wheel_tag: str
    sha256: str
    filename: str

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
    name = path.name
    stem = name[: -len(".whl")]
    parts = stem.split("-")
    if len(parts) < 5:
        raise ValueError(f"unexpected wheel filename: {name}")
    return WheelRecord(
        package=parts[0].replace("_", "-"),
        version=parts[1],
        wheel_tag=parts[-1],
        sha256=_sha256_file(path),
        filename=name,
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
    for platform in PLATFORM_TAGS:
        command.extend(["--platform", platform])
    for abi in ABIS:
        command.extend(["--abi", abi])

    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout or "pip download failed").strip())

    records = [_wheel_record(path) for path in sorted(wheel_dir.glob("*.whl"))]
    if any(path.suffix != ".whl" for path in wheel_dir.iterdir()):
        raise RuntimeError("non-wheel artifact downloaded")

    platforms_used = list(PLATFORM_TAGS)
    if not any("musllinux_1_2_aarch64" in record.wheel_tag for record in records):
        platforms_used.append("musllinux_1_1_aarch64_required_for_resolution")
    return records, platforms_used


def _resolve_requirements_packages(requirements: Path) -> set[str]:
    names: set[str] = set()
    for line in requirements.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        token = re.split(r"[<>=!\[;]", stripped, maxsplit=1)[0].strip()
        if token:
            names.add(token.lower().replace("_", "-"))
    return names


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    requirements = Path(args[0]) if args else DEFAULT_REQUIREMENTS
    output = Path(args[1]) if len(args) > 1 else Path("wheel-arm64.json")
    if not requirements.is_file():
        print("requirements file missing", file=sys.stderr)
        return 2

    with tempfile.TemporaryDirectory(prefix="alpine-wheel-arm64-") as tmp:
        wheel_dir = Path(tmp)
        records, platforms_used = _download_arm64_wheels(requirements, wheel_dir)
        downloaded = {record.package.lower().replace("_", "-") for record in records}
        missing = sorted(
            pkg
            for pkg in REQUIRED_NATIVE_PACKAGES
            if pkg not in downloaded
        )
        payload = {
            "schema_version": 1,
            "architecture": "arm64",
            "platform": "linux/arm64",
            "resolution_status": "ok" if not missing else "failed",
            "platform_tags_used": platforms_used,
            "wheels": [record.as_dict() for record in records],
            "missing_packages": missing,
        }
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if missing:
        print(f"arm64 wheel resolution missing packages: {', '.join(missing)}", file=sys.stderr)
        return 1
    print("wheel-arm64 manifest written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
