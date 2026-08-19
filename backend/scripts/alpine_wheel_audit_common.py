"""Shared helpers for Alpine candidate wheel audit manifests."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path

REQUIREMENTS_PACKAGE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*")
PROBE_FILENAME = ".write-probe"


class ManifestWriteError(RuntimeError):
    """Raised when a wheel audit manifest cannot be written safely."""


def requirements_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_direct_requirements(path: Path) -> list[str]:
    names: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        token = re.split(r"[<>=!\[;]", stripped, maxsplit=1)[0].strip()
        if token and REQUIREMENTS_PACKAGE_PATTERN.match(token):
            names.append(normalize_package_name(token))
    return names


def normalize_package_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name.lower())


def atomic_write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp-{os.getpid()}")
    try:
        encoded = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
        with tmp_path.open("wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except OSError as exc:
        raise ManifestWriteError("manifest write failed") from exc
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


def write_output_probe(output_dir: Path) -> None:
    probe_path = output_dir / PROBE_FILENAME
    probe_path.write_text("ok\n", encoding="utf-8")
    probe_path.unlink(missing_ok=True)


def finalize_manifest_exit(manifest_path: Path, payload: dict[str, object]) -> int:
    try:
        atomic_write_json(manifest_path, payload)
    except ManifestWriteError:
        print("wheel manifest write failed", file=sys.stderr)
        return 2
    return 0
