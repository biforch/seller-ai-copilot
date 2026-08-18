"""Fail-closed OS package version checks for production backend container images."""

from __future__ import annotations

import re
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

SUCCESS_MESSAGE = "backend os package validation passed"

DEBIAN_ID = "debian"
EXPECTED_CODENAME = "trixie"

# DSA-6442 / CVE-2026-53615 — trixie-security Packages.xz (deb.debian.org), 2026-08-18.
# amd64 Packages.xz SHA256: bef94f56c0654dda3cce3747d118595a37a028f44e0eb61075dbd72f842a69ea
# arm64 Packages.xz SHA256: eafe6d65c615e24a096b09b18d079173b7e7813b7ccb6b69dc300f4cc02b6afe
SCANNER_TARGET_PACKAGES: dict[str, str] = {
    "bsdutils": "1:2.41.5-0+deb13u1",
    "libblkid1": "2.41.5-0+deb13u1",
    "liblastlog2-2": "2.41.5-0+deb13u1",
    "libmount1": "2.41.5-0+deb13u1",
    "libsmartcols1": "2.41.5-0+deb13u1",
    "libuuid1": "2.41.5-0+deb13u1",
    "login": "1:4.16.0-2+really2.41.5-0+deb13u1",
    "mount": "2.41.5-0+deb13u1",
    "util-linux": "2.41.5-0+deb13u1",
}

REQUIRED_DEPENDENCY_CLOSURE: dict[str, str] = {}

PERL_BASE_PACKAGE = "perl-base"

DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_MAX_OUTPUT_BYTES = 64 * 1024

CANARY_PATTERNS = (
    re.compile(r"access_token", re.IGNORECASE),
    re.compile(r"refresh_token", re.IGNORECASE),
    re.compile(r"client_secret", re.IGNORECASE),
    re.compile(r"eyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}"),
)

DpkgQueryRunner = Callable[[Sequence[str], int], str]


@dataclass(frozen=True)
class OsPackageValidationError(Exception):
    reason_code: str

    def __str__(self) -> str:
        return self.reason_code


class _OsPackageValidationError(OsPackageValidationError):
    """Mutable subclass for raise-from-safe exception chaining in probes."""


def _fail(reason_code: str) -> None:
    raise _OsPackageValidationError(reason_code)


def _safe_output(value: str) -> str:
    for pattern in CANARY_PATTERNS:
        if pattern.search(value):
            return "[redacted]"
    if len(value) > 256:
        return value[:256] + "..."
    return value


def _default_dpkg_query(args: Sequence[str], timeout_seconds: int) -> str:
    completed = subprocess.run(
        list(args),
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        shell=False,
    )
    output = (completed.stdout or "") + (completed.stderr or "")
    if len(output.encode("utf-8", errors="replace")) > DEFAULT_MAX_OUTPUT_BYTES:
        _fail("DPKG_OUTPUT_TOO_LARGE")
    if completed.returncode != 0:
        _fail("DPKG_QUERY_FAILED")
    return output


def _read_os_release(
    reader: Callable[[], str] | None = None,
) -> dict[str, str]:
    if reader is not None:
        content = reader()
    else:
        try:
            with open("/etc/os-release", encoding="utf-8") as handle:
                content = handle.read()
        except OSError:
            _fail("OS_RELEASE_UNREADABLE")

    if len(content.encode("utf-8", errors="replace")) > DEFAULT_MAX_OUTPUT_BYTES:
        _fail("OS_RELEASE_TOO_LARGE")

    parsed: dict[str, str] = {}
    for line in content.splitlines():
        if "=" not in line or line.startswith("#"):
            continue
        key, raw_value = line.split("=", 1)
        parsed[key.strip()] = raw_value.strip().strip('"')
    return parsed


def _package_exact_version(
    package_name: str,
    query_runner: DpkgQueryRunner,
    timeout_seconds: int,
) -> str | None:
    output = query_runner(
        (
            "dpkg-query",
            "-W",
            "-f=${Status}\t${Version}\n",
            package_name,
        ),
        timeout_seconds,
    )
    line = output.strip().splitlines()[0] if output.strip() else ""
    if not line or "\t" not in line:
        return None
    status, version = line.split("\t", 1)
    if "install ok installed" not in status:
        return None
    return version.strip()


def validate_backend_os_packages(
    *,
    scanner_targets: Mapping[str, str] | None = None,
    dependency_closure: Mapping[str, str] | None = None,
    query_runner: DpkgQueryRunner | None = None,
    os_release_reader: Callable[[], str] | None = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> None:
    targets = dict(scanner_targets or SCANNER_TARGET_PACKAGES)
    closure = dict(dependency_closure or REQUIRED_DEPENDENCY_CLOSURE)
    runner = query_runner or _default_dpkg_query

    os_release = _read_os_release(os_release_reader)
    if os_release.get("ID") != DEBIAN_ID:
        _fail("OS_ID_INVALID")
    if os_release.get("VERSION_CODENAME") != EXPECTED_CODENAME:
        _fail("OS_CODENAME_INVALID")

    combined = {**closure, **targets}
    for package_name, expected_version in sorted(combined.items()):
        try:
            installed_version = _package_exact_version(package_name, runner, timeout_seconds)
        except subprocess.TimeoutExpired:
            _fail("DPKG_QUERY_TIMEOUT")
        except _OsPackageValidationError:
            raise
        except OsPackageValidationError:
            raise
        except Exception:
            _fail("DPKG_QUERY_FAILED")

        if installed_version is None:
            _fail(f"PACKAGE_NOT_INSTALLED:{package_name}")
        assert installed_version is not None
        if installed_version != expected_version:
            _fail(
                f"PACKAGE_VERSION_MISMATCH:{package_name}:{_safe_output(installed_version)}"
            )

    try:
        perl_version = _package_exact_version(PERL_BASE_PACKAGE, runner, timeout_seconds)
    except subprocess.TimeoutExpired:
        _fail("DPKG_QUERY_TIMEOUT")
    except _OsPackageValidationError:
        raise
    except OsPackageValidationError:
        raise
    except Exception:
        _fail("DPKG_QUERY_FAILED")

    if perl_version is None:
        _fail("PERL_BASE_MISSING")


def main() -> int:
    try:
        validate_backend_os_packages()
    except OsPackageValidationError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except Exception:
        print("OS_PACKAGE_VALIDATION_FAILED", file=sys.stderr)
        return 1
    print(SUCCESS_MESSAGE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
