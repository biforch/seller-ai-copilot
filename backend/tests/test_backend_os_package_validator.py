"""Tests for backend OS package version validator."""

from __future__ import annotations

import subprocess

import pytest

from scripts.validate_backend_os_packages import (
    PERL_BASE_PACKAGE,
    SCANNER_TARGET_PACKAGES,
    OsPackageValidationError,
    validate_backend_os_packages,
)


def _os_release(codename: str = "trixie") -> str:
    return "\n".join(
        [
            'PRETTY_NAME="Debian GNU/Linux 13 (trixie)"',
            "NAME=Debian",
            'VERSION_ID="13"',
            f"VERSION_CODENAME={codename}",
            "ID=debian",
            "",
        ]
    )


def _query_runner(installed: dict[str, str]):
    def runner(args: tuple[str, ...], timeout_seconds: int) -> str:
        package = args[-1]
        version = installed.get(package)
        if version is None:
            return ""
        return f"install ok installed\t{version}\n"

    return runner


def test_clean_map_passes() -> None:
    installed = dict(SCANNER_TARGET_PACKAGES)
    installed[PERL_BASE_PACKAGE] = "5.40.1-6"
    validate_backend_os_packages(
        query_runner=_query_runner(installed),
        os_release_reader=lambda: _os_release(),
    )


def test_missing_package_fails() -> None:
    installed = dict(SCANNER_TARGET_PACKAGES)
    del installed["mount"]
    installed[PERL_BASE_PACKAGE] = "5.40.1-6"
    with pytest.raises(OsPackageValidationError, match="PACKAGE_NOT_INSTALLED:mount"):
        validate_backend_os_packages(
            query_runner=_query_runner(installed),
            os_release_reader=lambda: _os_release(),
        )


def test_wrong_version_fails() -> None:
    installed = dict(SCANNER_TARGET_PACKAGES)
    installed["libuuid1"] = "2.41-5"
    installed[PERL_BASE_PACKAGE] = "5.40.1-6"
    with pytest.raises(OsPackageValidationError, match="PACKAGE_VERSION_MISMATCH:libuuid1"):
        validate_backend_os_packages(
            query_runner=_query_runner(installed),
            os_release_reader=lambda: _os_release(),
        )


def test_epoch_difference_rejected() -> None:
    installed = dict(SCANNER_TARGET_PACKAGES)
    installed["bsdutils"] = "2.41.5-0+deb13u1"
    installed[PERL_BASE_PACKAGE] = "5.40.1-6"
    with pytest.raises(OsPackageValidationError, match="PACKAGE_VERSION_MISMATCH:bsdutils"):
        validate_backend_os_packages(
            query_runner=_query_runner(installed),
            os_release_reader=lambda: _os_release(),
        )


def test_really_version_difference_rejected() -> None:
    installed = dict(SCANNER_TARGET_PACKAGES)
    installed["login"] = "1:4.16.0-2+really2.41-5"
    installed[PERL_BASE_PACKAGE] = "5.40.1-6"
    with pytest.raises(OsPackageValidationError, match="PACKAGE_VERSION_MISMATCH:login"):
        validate_backend_os_packages(
            query_runner=_query_runner(installed),
            os_release_reader=lambda: _os_release(),
        )


def test_dpkg_nonzero_fails() -> None:
    def runner(args: tuple[str, ...], timeout_seconds: int) -> str:
        raise OsPackageValidationError("DPKG_QUERY_FAILED")

    with pytest.raises(OsPackageValidationError, match="DPKG_QUERY_FAILED"):
        validate_backend_os_packages(
            query_runner=runner,
            os_release_reader=lambda: _os_release(),
        )


def test_dpkg_timeout_fails() -> None:
    def runner(args: tuple[str, ...], timeout_seconds: int) -> str:
        raise subprocess.TimeoutExpired(cmd=args, timeout=timeout_seconds)

    with pytest.raises(OsPackageValidationError, match="DPKG_QUERY_TIMEOUT"):
        validate_backend_os_packages(
            query_runner=runner,
            os_release_reader=lambda: _os_release(),
        )


def test_oversized_output_fails() -> None:
    def runner(args: tuple[str, ...], timeout_seconds: int) -> str:
        raise OsPackageValidationError("DPKG_OUTPUT_TOO_LARGE")

    with pytest.raises(OsPackageValidationError, match="DPKG_OUTPUT_TOO_LARGE"):
        validate_backend_os_packages(
            query_runner=runner,
            os_release_reader=lambda: _os_release(),
        )


def test_malformed_output_treated_as_missing() -> None:
    def runner(args: tuple[str, ...], timeout_seconds: int) -> str:
        return "deinstall ok not-installed\n"

    installed = dict(SCANNER_TARGET_PACKAGES)
    installed[PERL_BASE_PACKAGE] = "5.40.1-6"
    with pytest.raises(OsPackageValidationError, match="PACKAGE_NOT_INSTALLED:"):
        validate_backend_os_packages(
            query_runner=runner,
            os_release_reader=lambda: _os_release(),
        )


def test_wrong_os_id_fails() -> None:
    installed = dict(SCANNER_TARGET_PACKAGES)
    installed[PERL_BASE_PACKAGE] = "5.40.1-6"
    with pytest.raises(OsPackageValidationError, match="OS_ID_INVALID"):
        validate_backend_os_packages(
            query_runner=_query_runner(installed),
            os_release_reader=lambda: 'ID=ubuntu\nVERSION_CODENAME=trixie\n',
        )


def test_wrong_codename_fails() -> None:
    installed = dict(SCANNER_TARGET_PACKAGES)
    installed[PERL_BASE_PACKAGE] = "5.40.1-6"
    with pytest.raises(OsPackageValidationError, match="OS_CODENAME_INVALID"):
        validate_backend_os_packages(
            query_runner=_query_runner(installed),
            os_release_reader=lambda: _os_release("bookworm"),
        )


def test_perl_base_missing_rejected() -> None:
    installed = dict(SCANNER_TARGET_PACKAGES)
    with pytest.raises(OsPackageValidationError, match="PERL_BASE_MISSING"):
        validate_backend_os_packages(
            query_runner=_query_runner(installed),
            os_release_reader=lambda: _os_release(),
        )


def test_canary_not_leaked_on_version_mismatch(capsys: pytest.CaptureFixture[str]) -> None:
    installed = dict(SCANNER_TARGET_PACKAGES)
    installed["login"] = "access_token-canary-value"
    installed[PERL_BASE_PACKAGE] = "5.40.1-6"
    with pytest.raises(OsPackageValidationError, match="PACKAGE_VERSION_MISMATCH:login"):
        validate_backend_os_packages(
            query_runner=_query_runner(installed),
            os_release_reader=lambda: _os_release(),
        )
    captured = capsys.readouterr()
    assert "access_token-canary-value" not in captured.out + captured.err


def test_main_guard_does_not_run_on_import() -> None:
    from scripts import validate_backend_os_packages as module

    assert callable(module.validate_backend_os_packages)
