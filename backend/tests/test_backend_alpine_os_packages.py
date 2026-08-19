"""Tests for Alpine OS package validator."""

from __future__ import annotations

import pytest

from scripts.validate_backend_alpine_os_packages import (
    AlpineOsPackageValidationError,
    validate_backend_alpine_os_packages,
)


def _os_release_alpine_324() -> str:
    return 'ID=alpine\nVERSION_ID=3.24.0\n'


def test_validate_alpine_os_packages_passes_with_required_packages() -> None:
    installed = {"ca-certificates", "libstdc++", "postgresql-libs", "python3"}

    def runner(args, timeout_seconds):  # noqa: ANN001
        if args[:2] == ("apk", "info") and args[2] == "-e":
            package = args[3]
            return package if package in installed else ""
        if args == ("apk", "info", "-q"):
            return "\n".join(sorted(installed)) + "\n"
        raise AssertionError(f"unexpected args: {args}")

    inventory = validate_backend_alpine_os_packages(
        query_runner=runner,
        os_release_reader=_os_release_alpine_324,
        validate_python_version=False,
    )
    assert "ca-certificates" in inventory


def test_validate_alpine_os_packages_rejects_forbidden_perl() -> None:
    installed = {"ca-certificates", "libstdc++", "postgresql-libs", "perl-base"}

    def runner(args, timeout_seconds):  # noqa: ANN001
        if args[:2] == ("apk", "info") and args[2] == "-e":
            package = args[3]
            return package if package in installed else ""
        if args == ("apk", "info", "-q"):
            return "\n".join(sorted(installed)) + "\n"
        raise AssertionError(f"unexpected args: {args}")

    with pytest.raises(AlpineOsPackageValidationError) as exc:
        validate_backend_alpine_os_packages(
            query_runner=runner,
            os_release_reader=_os_release_alpine_324,
            validate_python_version=False,
        )
    assert str(exc.value) == "FORBIDDEN_APK_PRESENT:perl-base"


def test_validate_alpine_os_packages_rejects_wrong_version() -> None:
    def runner(args, timeout_seconds):  # noqa: ANN001
        raise AssertionError("apk should not be queried when version fails")

    with pytest.raises(AlpineOsPackageValidationError) as exc:
        validate_backend_alpine_os_packages(
            query_runner=runner,
            os_release_reader=lambda: "ID=alpine\nVERSION_ID=3.23.0\n",
            validate_python_version=False,
        )
    assert str(exc.value) == "OS_VERSION_INVALID"
