"""Fail-closed Alpine OS package checks for hardened backend candidate images."""

from __future__ import annotations

import re
import subprocess
import sys
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from enum import Enum

SUCCESS_MESSAGE = "backend alpine os package validation passed"

ALPINE_ID = "alpine"
EXPECTED_VERSION_PREFIX = "3.24."
EXPECTED_PYTHON_MAJOR = 3
EXPECTED_PYTHON_MINOR = 11

FORBIDDEN_APK_PACKAGES: frozenset[str] = frozenset(
    {
        "perl",
        "perl-base",
        "util-linux",
        "util-linux-dev",
        "gcc",
        "musl-dev",
        "postgresql-dev",
        "build-base",
        "binutils",
        "make",
        "curl",
    }
)

REQUIRED_RUNTIME_APK_PACKAGES: frozenset[str] = frozenset(
    {
        "ca-certificates",
        "libstdc++",
        "postgresql-libs",
    }
)

DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_MAX_OUTPUT_BYTES = 64 * 1024

CANARY_PATTERNS = (
    re.compile(r"access_token", re.IGNORECASE),
    re.compile(r"refresh_token", re.IGNORECASE),
    re.compile(r"client_secret", re.IGNORECASE),
    re.compile(r"eyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}"),
)

ApkInventoryRunner = Callable[[Sequence[str], int], str]
SubprocessRunner = Callable[..., subprocess.CompletedProcess[str]]


class ApkPresenceStatus(str, Enum):
    INSTALLED = "installed"
    ABSENT = "absent"
    QUERY_FAILED = "query_failed"


@dataclass(frozen=True)
class ApkPresenceResult:
    status: ApkPresenceStatus


@dataclass(frozen=True)
class AlpineOsPackageValidationError(Exception):
    reason_code: str

    def __str__(self) -> str:
        return self.reason_code


class _AlpineOsPackageValidationError(AlpineOsPackageValidationError):
    """Mutable subclass for raise-from-safe exception chaining in probes."""


def _fail(reason_code: str) -> None:
    raise _AlpineOsPackageValidationError(reason_code)


def _probe_apk_package_presence(
    package_name: str,
    *,
    timeout_seconds: int,
    subprocess_runner: SubprocessRunner = subprocess.run,
) -> ApkPresenceResult:
    try:
        completed = subprocess_runner(
            ["apk", "info", "-e", package_name],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            shell=False,
        )
    except subprocess.TimeoutExpired:
        return ApkPresenceResult(ApkPresenceStatus.QUERY_FAILED)
    except FileNotFoundError:
        return ApkPresenceResult(ApkPresenceStatus.QUERY_FAILED)
    except OSError:
        return ApkPresenceResult(ApkPresenceStatus.QUERY_FAILED)
    except Exception:
        return ApkPresenceResult(ApkPresenceStatus.QUERY_FAILED)

    output = (completed.stdout or "") + (completed.stderr or "")
    if len(output.encode("utf-8", errors="replace")) > DEFAULT_MAX_OUTPUT_BYTES:
        return ApkPresenceResult(ApkPresenceStatus.QUERY_FAILED)

    return_code = completed.returncode
    if return_code == 0:
        return ApkPresenceResult(ApkPresenceStatus.INSTALLED)
    if return_code == 1:
        return ApkPresenceResult(ApkPresenceStatus.ABSENT)
    return ApkPresenceResult(ApkPresenceStatus.QUERY_FAILED)


def _default_apk_inventory_runner(args: Sequence[str], timeout_seconds: int) -> str:
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
        _fail("APK_OUTPUT_TOO_LARGE")
    if completed.returncode != 0:
        _fail("APK_QUERY_FAILED")
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


def _installed_apk_inventory(runner: ApkInventoryRunner, timeout_seconds: int) -> list[str]:
    output = runner(("apk", "info", "-q"), timeout_seconds)
    names = sorted({line.strip() for line in output.splitlines() if line.strip()})
    return names


def validate_backend_alpine_os_packages(
    *,
    forbidden_packages: Iterable[str] = FORBIDDEN_APK_PACKAGES,
    required_packages: Iterable[str] = REQUIRED_RUNTIME_APK_PACKAGES,
    inventory_runner: ApkInventoryRunner | None = None,
    presence_probe: Callable[[str], ApkPresenceResult] | None = None,
    os_release_reader: Callable[[], str] | None = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    validate_python_version: bool = True,
) -> list[str]:
    inventory = inventory_runner or _default_apk_inventory_runner

    def probe(package_name: str) -> ApkPresenceResult:
        if presence_probe is not None:
            return presence_probe(package_name)
        return _probe_apk_package_presence(
            package_name,
            timeout_seconds=timeout_seconds,
        )

    os_release = _read_os_release(os_release_reader)
    if os_release.get("ID") != ALPINE_ID:
        _fail("OS_ID_INVALID")
    version_id = os_release.get("VERSION_ID", "")
    if not version_id.startswith(EXPECTED_VERSION_PREFIX):
        _fail("OS_VERSION_INVALID")

    if validate_python_version:
        if sys.version_info.major != EXPECTED_PYTHON_MAJOR:
            _fail("PYTHON_MAJOR_INVALID")
        if sys.version_info.minor != EXPECTED_PYTHON_MINOR:
            _fail("PYTHON_MINOR_INVALID")

    for package_name in sorted(forbidden_packages):
        result = probe(package_name)
        if result.status is ApkPresenceStatus.QUERY_FAILED:
            _fail("APK_QUERY_FAILED")
        if result.status is ApkPresenceStatus.INSTALLED:
            _fail("FORBIDDEN_APK_INSTALLED")

    for package_name in sorted(required_packages):
        result = probe(package_name)
        if result.status is ApkPresenceStatus.QUERY_FAILED:
            _fail("APK_QUERY_FAILED")
        if result.status is ApkPresenceStatus.ABSENT:
            _fail("REQUIRED_APK_MISSING")

    try:
        return _installed_apk_inventory(inventory, timeout_seconds)
    except _AlpineOsPackageValidationError:
        raise
    except AlpineOsPackageValidationError:
        raise
    except subprocess.TimeoutExpired:
        _fail("APK_QUERY_FAILED")
    except Exception:
        _fail("APK_INVENTORY_FAILED")
    raise _AlpineOsPackageValidationError("APK_INVENTORY_FAILED")


def main() -> int:
    try:
        validate_backend_alpine_os_packages()
    except AlpineOsPackageValidationError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except Exception:
        print("ALPINE_OS_PACKAGE_VALIDATION_FAILED", file=sys.stderr)
        return 1
    print(SUCCESS_MESSAGE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
