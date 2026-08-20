#!/usr/bin/env python3
"""Static gate: production backend must not reintroduce Bearer authentication."""

from __future__ import annotations

import re
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
SCAN_ROOTS = (BACKEND_ROOT / "app", BACKEND_ROOT / "services")
TEST_MARKERS = ("/tests/", "\\tests\\")
FORBIDDEN_PATTERNS = (
    (re.compile(r"\bHTTPBearer\b"), "HTTPBearer"),
    (re.compile(r"\bHTTPAuthorizationCredentials\b"), "HTTPAuthorizationCredentials"),
    (re.compile(r"Authorization\s*:\s*[`'\"]\s*Bearer"), "Authorization Bearer header construction"),
    (re.compile(r"WWW-Authenticate['\"]?\s*:\s*[`'\"]Bearer"), "WWW-Authenticate Bearer challenge"),
)


def iter_source_files() -> list[Path]:
    files: list[Path] = []
    for root in SCAN_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            normalized = str(path)
            if any(marker in normalized for marker in TEST_MARKERS):
                continue
            files.append(path)
    return sorted(files)


def validate_cookie_only_auth() -> list[str]:
    violations: list[str] = []
    for path in iter_source_files():
        source = path.read_text(encoding="utf-8")
        for pattern, label in FORBIDDEN_PATTERNS:
            if pattern.search(source):
                violations.append(f"{path.relative_to(BACKEND_ROOT)}: {label}")
    return violations


def main() -> int:
    violations = validate_cookie_only_auth()
    if violations:
        print("\n".join(violations), file=sys.stderr)
        return 1
    print("COOKIE_ONLY_AUTH_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
