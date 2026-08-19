"""Shared helpers for Alpine candidate wheel audit manifests."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

REQUIREMENTS_PACKAGE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*")


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
            names.append(token.lower().replace("_", "-"))
    return names


def normalize_package_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name.lower())
