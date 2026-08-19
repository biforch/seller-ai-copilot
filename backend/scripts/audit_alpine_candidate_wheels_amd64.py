"""Generate amd64 musllinux wheel install audit manifest for Alpine candidate base."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from alpine_wheel_audit_common import (
    finalize_manifest_exit,
    parse_direct_requirements,
    requirements_sha256,
    write_output_probe,
)
from validate_target_site_packages import validate_target_site_packages

REQUIREMENTS_PATH = Path("/input/requirements.txt")
OUTPUT_PATH = Path("/output/wheel-amd64.json")
OUTPUT_DIR = Path("/output")
WHEELHOUSE = Path("/wheelhouse")
TARGET_SITE_PACKAGES = Path("/target")
TARGET_ROOT = "/target"
PYTHON_VERSION = "3.11"

IMPORT_CHECKS = (
    ("fastapi", "fastapi"),
    ("starlette", "starlette"),
    ("pydantic", "pydantic"),
    ("uvicorn", "uvicorn"),
    ("sqlalchemy", "sqlalchemy"),
    ("alembic", "alembic"),
    ("psycopg2", "psycopg2"),
    ("jose", "jose"),
    ("cryptography", "cryptography"),
)


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
        }


def _base_payload(req_sha: str, direct_count: int) -> dict[str, object]:
    return {
        "schema_version": 1,
        "architecture": "amd64",
        "platform": "linux/amd64",
        "python_version": PYTHON_VERSION,
        "musl": True,
        "mode": "install_and_import",
        "requirements_sha256": req_sha,
        "resolved_package_count": direct_count,
        "wheel_count": 0,
        "sdist_count": 0,
        "missing_binary_package_count": 0,
        "missing_packages": [],
        "dependency_validation_method": "target_dependency_check",
        "download_status": "failed",
        "install_status": "failed",
        "dependency_check_status": "failed",
        "import_status": "failed",
        "smoke_status": "failed",
        "status": "failed",
        "reason_code": "WHEEL_AUDIT_FAILED",
        "wheels": [],
        "imports": [],
        "smoke": {},
    }


def _run_pip(args: list[str], *, env: dict[str, str] | None = None) -> None:
    command = [sys.executable, "-m", "pip", *args]
    completed = subprocess.run(command, check=False, capture_output=True, text=True, env=env)
    if completed.returncode != 0:
        raise RuntimeError("pip command failed")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _wheel_records(wheel_dir: Path) -> list[WheelRecord]:
    records: list[WheelRecord] = []
    for wheel_path in sorted(wheel_dir.glob("*.whl")):
        stem = wheel_path.name[: -len(".whl")]
        parts = stem.split("-")
        if len(parts) < 5:
            raise RuntimeError("unexpected wheel filename")
        records.append(
            WheelRecord(
                package=parts[0].replace("_", "-"),
                version=parts[1],
                wheel_tag=parts[-1],
                sha256=_sha256_file(wheel_path),
            )
        )
    return records


def _target_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(TARGET_SITE_PACKAGES)
    env["PYTHONNOUSERSITE"] = "1"
    return env


def _import_check(module_name: str) -> dict[str, str]:
    script = (
        "import importlib.util, inspect, sys; "
        f"mod = importlib.import_module({module_name!r}); "
        f"origin = inspect.getfile(mod); "
        f"assert origin.replace('\\\\', '/').startswith({TARGET_ROOT!r}), 'import origin outside target'"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
        env=_target_env(),
    )
    return {"module": module_name, "status": "ok" if completed.returncode == 0 else "failed"}


def _smoke_checks() -> dict[str, str]:
    aes_script = (
        "from cryptography.hazmat.primitives.ciphers.aead import AESGCM; "
        "key = AESGCM.generate_key(128); "
        "aes = AESGCM(key); "
        "nonce = b'012345678901'; "
        "ct = aes.encrypt(nonce, b'audit', None); "
        "assert aes.decrypt(nonce, ct, None) == b'audit'"
    )
    jwt_script = (
        "from jose import jwt; "
        "token = jwt.encode({'sub': 'audit'}, 'audit-secret-key-min-32-chars-long', algorithm='HS256'); "
        "payload = jwt.decode(token, 'audit-secret-key-min-32-chars-long', algorithms=['HS256']); "
        "assert payload['sub'] == 'audit'"
    )
    results: dict[str, str] = {}
    for name, script in (("aesgcm_roundtrip", aes_script), ("jwt_hs256_roundtrip", jwt_script)):
        completed = subprocess.run(
            [sys.executable, "-c", script],
            check=False,
            capture_output=True,
            text=True,
            env=_target_env(),
        )
        results[name] = "ok" if completed.returncode == 0 else "failed"
    return results


def _count_sdist(wheel_dir: Path) -> int:
    count = 0
    for path in wheel_dir.iterdir():
        if path.suffix in {".gz", ".zip"} or (path.suffix == ".tar" and path.name.endswith(".tar.gz")):
            count += 1
        elif path.suffix != ".whl":
            count += 1
    return count


def run_probe() -> int:
    write_output_probe(OUTPUT_DIR)
    print("amd64 output probe passed")
    return 0


def run_download(payload: dict[str, object]) -> None:
    WHEELHOUSE.mkdir(parents=True, exist_ok=True)
    _run_pip(
        [
            "download",
            "--only-binary=:all:",
            "-r",
            str(REQUIREMENTS_PATH),
            "-d",
            str(WHEELHOUSE),
        ]
    )
    sdist_count = _count_sdist(WHEELHOUSE)
    if sdist_count:
        payload["sdist_count"] = sdist_count
        payload["reason_code"] = "SDIST_PRESENT"
        raise RuntimeError("sdist present")

    wheels = _wheel_records(WHEELHOUSE)
    payload["download_status"] = "ok"
    payload["wheel_count"] = len(wheels)
    payload["wheels"] = [record.as_dict() for record in wheels]


def run_install(payload: dict[str, object]) -> None:
    if not WHEELHOUSE.is_dir() or not any(WHEELHOUSE.glob("*.whl")):
        payload["reason_code"] = "WHEELHOUSE_EMPTY"
        raise RuntimeError("wheelhouse empty")

    if TARGET_SITE_PACKAGES.exists():
        for child in TARGET_SITE_PACKAGES.iterdir():
            if child.is_dir():
                for nested in child.rglob("*"):
                    if nested.is_file():
                        nested.unlink(missing_ok=True)
                child.rmdir()
            else:
                child.unlink(missing_ok=True)
    TARGET_SITE_PACKAGES.mkdir(parents=True, exist_ok=True)

    _run_pip(
        [
            "install",
            "--no-index",
            f"--find-links={WHEELHOUSE}",
            "--target",
            str(TARGET_SITE_PACKAGES),
            "--no-compile",
            "-r",
            str(REQUIREMENTS_PATH),
        ],
        env=_target_env(),
    )
    payload["install_status"] = "ok"

    dep_status, _issues = validate_target_site_packages(TARGET_SITE_PACKAGES)
    payload["dependency_check_status"] = dep_status
    if dep_status != "ok":
        payload["reason_code"] = "TARGET_DEPENDENCY_CHECK_FAILED"
        raise RuntimeError("target dependency check failed")

    imports = [_import_check(module) for _, module in IMPORT_CHECKS]
    payload["imports"] = imports
    payload["import_status"] = "ok" if all(item["status"] == "ok" for item in imports) else "failed"

    smoke = _smoke_checks()
    payload["smoke"] = smoke
    payload["smoke_status"] = "ok" if all(value == "ok" for value in smoke.values()) else "failed"

    if payload["import_status"] != "ok" or payload["smoke_status"] != "ok":
        payload["reason_code"] = "IMPORT_OR_SMOKE_FAILED"
        raise RuntimeError("import or smoke failed")

    payload["status"] = "passed"
    payload["reason_code"] = "WHEEL_AUDIT_OK"


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    phase = args[0] if args else "install"
    if not REQUIREMENTS_PATH.is_file():
        print("requirements input missing", file=sys.stderr)
        return 2

    req_sha = requirements_sha256(REQUIREMENTS_PATH)
    direct_requirements = parse_direct_requirements(REQUIREMENTS_PATH)
    payload = _base_payload(req_sha, len(direct_requirements))

    try:
        if phase == "probe":
            return run_probe()
        if phase == "download":
            run_download(payload)
        elif phase == "install":
            if payload["download_status"] == "failed" and WHEELHOUSE.is_dir() and any(WHEELHOUSE.glob("*.whl")):
                wheels = _wheel_records(WHEELHOUSE)
                payload["download_status"] = "ok"
                payload["wheel_count"] = len(wheels)
                payload["wheels"] = [record.as_dict() for record in wheels]
            run_install(payload)
        else:
            print("unknown audit phase", file=sys.stderr)
            return 2
    except RuntimeError:
        payload["status"] = "failed"

    if phase in {"download", "install"}:
        exit_code = finalize_manifest_exit(OUTPUT_PATH, payload)
        if payload["status"] == "passed":
            print("wheel-amd64 manifest written")
        else:
            print("wheel-amd64 manifest recorded failure", file=sys.stderr)
        return exit_code
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
