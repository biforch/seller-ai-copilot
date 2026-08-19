"""Generate amd64 musllinux wheel install audit manifest for Alpine candidate base."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from alpine_wheel_audit_common import parse_direct_requirements, requirements_sha256

REQUIREMENTS_PATH = Path("/input/requirements.txt")
OUTPUT_PATH = Path("/output/wheel-amd64.json")
PYTHON_VERSION = "3.11"

IMPORT_CHECKS = (
    ("fastapi", "fastapi", None),
    ("starlette", "starlette", None),
    ("pydantic", "pydantic", None),
    ("uvicorn", "uvicorn", None),
    ("sqlalchemy", "sqlalchemy", None),
    ("alembic", "alembic", None),
    ("psycopg2", "psycopg2", None),
    ("jose", "jose", None),
    ("cryptography", "cryptography.hazmat.primitives.ciphers.aead", "AESGCM"),
    ("pydantic_core", "pydantic_core", None),
    ("bcrypt", "bcrypt", None),
    ("uvloop", "uvloop", None),
    ("httptools", "httptools", None),
    ("watchfiles", "watchfiles", None),
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


def _run(command: list[str], *, cwd: Path | None = None) -> None:
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        cwd=str(cwd) if cwd else None,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(f"command failed ({detail[:256]})")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _wheel_records(wheel_dir: Path) -> list[WheelRecord]:
    records: list[WheelRecord] = []
    for wheel_path in sorted(wheel_dir.glob("*.whl")):
        name = wheel_path.name
        stem = name[: -len(".whl")]
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


def _import_check(module_path: str, attr: str | None) -> dict[str, str]:
    script = f"import {module_path}"
    if attr:
        script += f"; getattr({module_path}, {attr!r})"
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )
    return {
        "module": module_path,
        "status": "ok" if completed.returncode == 0 else "failed",
    }


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
        completed = subprocess.run([sys.executable, "-c", script], check=False, capture_output=True, text=True)
        results[name] = "ok" if completed.returncode == 0 else "failed"
    return results


def main() -> int:
    if not REQUIREMENTS_PATH.is_file():
        print("requirements input missing", file=sys.stderr)
        return 2
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    req_sha = requirements_sha256(REQUIREMENTS_PATH)
    direct_requirements = parse_direct_requirements(REQUIREMENTS_PATH)

    payload: dict[str, object] = {
        "schema_version": 1,
        "architecture": "amd64",
        "platform": "linux/amd64",
        "python_version": PYTHON_VERSION,
        "musl": True,
        "requirements_sha256": req_sha,
        "download_status": "failed",
        "install_status": "failed",
        "pip_check_status": "failed",
        "import_status": "failed",
        "smoke_status": "failed",
        "reason_code": "WHEEL_AUDIT_FAILED",
        "wheel_count": 0,
        "sdist_count": 0,
        "resolved_package_count": len(direct_requirements),
        "wheels": [],
        "imports": [],
        "smoke": {},
    }

    try:
        with tempfile.TemporaryDirectory(prefix="alpine-wheel-audit-") as tmp:
            tmp_path = Path(tmp)
            venv_dir = tmp_path / "venv"
            wheel_dir = tmp_path / "wheels"
            wheel_dir.mkdir()
            _run([sys.executable, "-m", "venv", str(venv_dir)])
            pip = venv_dir / "bin" / "pip"
            _run([str(pip), "install", "--upgrade", "pip"])
            _run(
                [
                    str(pip),
                    "download",
                    "--only-binary=:all:",
                    "-r",
                    str(REQUIREMENTS_PATH),
                    "-d",
                    str(wheel_dir),
                ]
            )
            sdist_count = len(list(wheel_dir.glob("*.tar.gz"))) + len(list(wheel_dir.glob("*.zip")))
            non_wheel = [path.name for path in wheel_dir.iterdir() if path.suffix != ".whl"]
            if sdist_count or any(path.suffix != ".whl" for path in wheel_dir.iterdir()):
                payload["sdist_count"] = sdist_count + len(non_wheel)
                payload["reason_code"] = "SDIST_PRESENT"
                OUTPUT_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
                return 1

            payload["download_status"] = "ok"
            wheels = _wheel_records(wheel_dir)
            payload["wheel_count"] = len(wheels)
            payload["wheels"] = [record.as_dict() for record in wheels]

            _run(
                [
                    str(pip),
                    "install",
                    "--no-index",
                    f"--find-links={wheel_dir}",
                    "-r",
                    str(REQUIREMENTS_PATH),
                ]
            )
            payload["install_status"] = "ok"

            pip_check = subprocess.run([str(pip), "check"], check=False, capture_output=True, text=True)
            payload["pip_check_status"] = "ok" if pip_check.returncode == 0 else "failed"

            imports = [_import_check(module, attr) for _, module, attr in IMPORT_CHECKS]
            payload["imports"] = imports
            payload["import_status"] = "ok" if all(item["status"] == "ok" for item in imports) else "failed"

            smoke = _smoke_checks()
            payload["smoke"] = smoke
            payload["smoke_status"] = "ok" if all(status == "ok" for status in smoke.values()) else "failed"

            if (
                payload["pip_check_status"] == "ok"
                and payload["import_status"] == "ok"
                and payload["smoke_status"] == "ok"
            ):
                payload["reason_code"] = "WHEEL_AUDIT_OK"
            OUTPUT_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except Exception:
        OUTPUT_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        raise

    print("wheel-amd64 manifest written")
    if payload["reason_code"] != "WHEEL_AUDIT_OK":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
