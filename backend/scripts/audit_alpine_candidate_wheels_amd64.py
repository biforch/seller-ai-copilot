"""Generate amd64 musllinux wheel install audit manifest for Alpine candidate base."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

REQUIREMENTS_PATH = Path("/input/requirements.txt")
OUTPUT_PATH = Path("/output/wheel-amd64.json")

IMPORT_CHECKS = (
    ("cryptography", "cryptography.hazmat.primitives.ciphers.aead", "AESGCM"),
    ("psycopg2", "psycopg2", None),
    ("pydantic_core", "pydantic_core", None),
    ("bcrypt", "bcrypt", None),
    ("uvloop", "uvloop", None),
    ("httptools", "httptools", None),
    ("watchfiles", "watchfiles", None),
    ("fastapi", "fastapi", None),
    ("starlette", "starlette", None),
)

SMOKE_CHECKS = (
    "aesgcm_roundtrip",
    "jwt_hs256_roundtrip",
)


@dataclass(frozen=True)
class WheelRecord:
    package: str
    version: str
    wheel_tag: str
    sha256: str
    binary: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "package": self.package,
            "version": self.version,
            "wheel_tag": self.wheel_tag,
            "sha256": self.sha256,
            "binary": self.binary,
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
        raise RuntimeError(f"command failed: {' '.join(command)} ({detail})")


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
            raise RuntimeError(f"unexpected wheel filename: {name}")
        package = parts[0].replace("_", "-")
        version = parts[1]
        tag = parts[-1]
        records.append(
            WheelRecord(
                package=package,
                version=version,
                wheel_tag=tag,
                sha256=_sha256_file(wheel_path),
                binary=True,
            )
        )
    return records


def _import_check(module_path: str, attr: str | None) -> dict[str, object]:
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
        if any(path.suffix != ".whl" for path in wheel_dir.iterdir()):
            raise RuntimeError("non-wheel artifact downloaded")
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
        _run([str(pip), "check"])
        wheels = _wheel_records(wheel_dir)
        imports = [_import_check(module, attr) for _, module, attr in IMPORT_CHECKS]
        smoke = _smoke_checks()
        pip_check = subprocess.run([str(pip), "check"], check=False, capture_output=True, text=True)
        payload = {
            "schema_version": 1,
            "architecture": "amd64",
            "platform": "linux/amd64",
            "install_status": "ok" if pip_check.returncode == 0 else "failed",
            "pip_check": "ok" if pip_check.returncode == 0 else "failed",
            "wheels": [record.as_dict() for record in wheels],
            "imports": imports,
            "smoke": smoke,
        }
        OUTPUT_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("wheel-amd64 manifest written")
    if payload["install_status"] != "ok":
        return 1
    if any(item["status"] != "ok" for item in imports):
        return 1
    if any(status != "ok" for status in smoke.values()):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
