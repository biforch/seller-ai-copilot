"""Tests for Alpine OS package validator."""

from __future__ import annotations

import subprocess
from typing import Any

import pytest

from scripts.validate_backend_alpine_os_packages import (
    REQUIRED_RUNTIME_APK_PACKAGES,
    AlpineOsPackageValidationError,
    ApkPresenceResult,
    ApkPresenceStatus,
    _probe_apk_package_presence,
    validate_backend_alpine_os_packages,
)


def _os_release_alpine_324() -> str:
    return "ID=alpine\nVERSION_ID=3.24.0\n"


def _inventory_runner(installed: set[str]):
    def runner(args, timeout_seconds):  # noqa: ANN001
        assert args == ("apk", "info", "-q")
        return "\n".join(sorted(installed)) + "\n"

    return runner


def _presence_probe_from_return_codes(return_codes: dict[str, int]):
    def probe(package_name: str) -> ApkPresenceResult:
        return_code = return_codes.get(package_name, 1)
        if return_code == 0:
            return ApkPresenceResult(ApkPresenceStatus.INSTALLED)
        if return_code == 1:
            return ApkPresenceResult(ApkPresenceStatus.ABSENT)
        return ApkPresenceResult(ApkPresenceStatus.QUERY_FAILED)

    return probe


def test_validate_alpine_os_packages_passes_with_required_packages() -> None:
    installed = set(REQUIRED_RUNTIME_APK_PACKAGES) | {"python3"}
    inventory = validate_backend_alpine_os_packages(
        inventory_runner=_inventory_runner(installed),
        presence_probe=_presence_probe_from_return_codes(
            {package: 0 for package in REQUIRED_RUNTIME_APK_PACKAGES}
        ),
        os_release_reader=_os_release_alpine_324,
        validate_python_version=False,
    )
    assert "ca-certificates" in inventory


def test_validate_alpine_os_packages_rejects_forbidden_perl() -> None:
    installed = set(REQUIRED_RUNTIME_APK_PACKAGES) | {"perl-base"}
    return_codes = {package: 0 for package in REQUIRED_RUNTIME_APK_PACKAGES}
    return_codes["perl-base"] = 0

    with pytest.raises(AlpineOsPackageValidationError) as exc:
        validate_backend_alpine_os_packages(
            inventory_runner=_inventory_runner(installed),
            presence_probe=_presence_probe_from_return_codes(return_codes),
            os_release_reader=_os_release_alpine_324,
            validate_python_version=False,
        )
    assert str(exc.value) == "FORBIDDEN_APK_INSTALLED"


def test_validate_alpine_os_packages_rejects_wrong_version() -> None:
    with pytest.raises(AlpineOsPackageValidationError) as exc:
        validate_backend_alpine_os_packages(
            inventory_runner=_inventory_runner(set()),
            presence_probe=_presence_probe_from_return_codes({}),
            os_release_reader=lambda: "ID=alpine\nVERSION_ID=3.23.0\n",
            validate_python_version=False,
        )
    assert str(exc.value) == "OS_VERSION_INVALID"


@pytest.mark.parametrize(
    ("return_code", "expected_reason"),
    [
        (0, None),
        (1, "REQUIRED_APK_MISSING"),
        (2, "APK_QUERY_FAILED"),
        (-9, "APK_QUERY_FAILED"),
    ],
)
def test_required_package_return_code_semantics(return_code: int, expected_reason: str | None) -> None:
    package = "ca-certificates"
    return_codes = {pkg: 0 for pkg in REQUIRED_RUNTIME_APK_PACKAGES}
    return_codes[package] = return_code

    if expected_reason is None:
        validate_backend_alpine_os_packages(
            inventory_runner=_inventory_runner(set(REQUIRED_RUNTIME_APK_PACKAGES)),
            presence_probe=_presence_probe_from_return_codes(return_codes),
            required_packages=(package,),
            forbidden_packages=(),
            os_release_reader=_os_release_alpine_324,
            validate_python_version=False,
        )
        return

    with pytest.raises(AlpineOsPackageValidationError) as exc:
        validate_backend_alpine_os_packages(
            inventory_runner=_inventory_runner(set(REQUIRED_RUNTIME_APK_PACKAGES)),
            presence_probe=_presence_probe_from_return_codes(return_codes),
            required_packages=(package,),
            forbidden_packages=(),
            os_release_reader=_os_release_alpine_324,
            validate_python_version=False,
        )
    assert str(exc.value) == expected_reason


@pytest.mark.parametrize(
    ("return_code", "expected_reason"),
    [
        (0, "FORBIDDEN_APK_INSTALLED"),
        (1, None),
        (2, "APK_QUERY_FAILED"),
        (-15, "APK_QUERY_FAILED"),
    ],
)
def test_forbidden_package_return_code_semantics(return_code: int, expected_reason: str | None) -> None:
    package = "perl-base"
    return_codes = {pkg: 0 for pkg in REQUIRED_RUNTIME_APK_PACKAGES}
    return_codes[package] = return_code

    if expected_reason is None:
        validate_backend_alpine_os_packages(
            inventory_runner=_inventory_runner(set(REQUIRED_RUNTIME_APK_PACKAGES)),
            presence_probe=_presence_probe_from_return_codes(return_codes),
            required_packages=(),
            forbidden_packages=(package,),
            os_release_reader=_os_release_alpine_324,
            validate_python_version=False,
        )
        return

    with pytest.raises(AlpineOsPackageValidationError) as exc:
        validate_backend_alpine_os_packages(
            inventory_runner=_inventory_runner(set(REQUIRED_RUNTIME_APK_PACKAGES)),
            presence_probe=_presence_probe_from_return_codes(return_codes),
            required_packages=(),
            forbidden_packages=(package,),
            os_release_reader=_os_release_alpine_324,
            validate_python_version=False,
        )
    assert str(exc.value) == expected_reason


def _subprocess_runner_with_return_code(return_code: int):
    def runner(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        assert kwargs.get("shell") is False
        command = kwargs.get("args", args[0] if args else None)
        assert command == ["apk", "info", "-e", "ca-certificates"]
        return subprocess.CompletedProcess(
            args=command,
            returncode=return_code,
            stdout="",
            stderr="access_token=secret-canary",
        )

    return runner


@pytest.mark.parametrize(
    "exception",
    [
        subprocess.TimeoutExpired(cmd=["apk", "info", "-e", "ca-certificates"], timeout=1),
        FileNotFoundError("apk"),
        OSError("broken pipe"),
        RuntimeError("unexpected"),
    ],
)
def test_probe_maps_execution_failures_to_query_failed(exception: Exception) -> None:
    def runner(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise exception

    result = _probe_apk_package_presence(
        "ca-certificates",
        timeout_seconds=1,
        subprocess_runner=runner,
    )
    assert result.status is ApkPresenceStatus.QUERY_FAILED


def test_probe_uses_shell_false_and_fixed_argv() -> None:
    captured: dict[str, Any] = {}

    def runner(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        captured["args"] = kwargs.get("args", args[0] if args else None)
        captured["shell"] = kwargs.get("shell")
        return subprocess.CompletedProcess(
            args=captured["args"],
            returncode=1,
            stdout="",
            stderr="",
        )

    result = _probe_apk_package_presence(
        "postgresql-libs",
        timeout_seconds=1,
        subprocess_runner=runner,
    )
    assert result.status is ApkPresenceStatus.ABSENT
    assert captured["shell"] is False
    assert captured["args"] == ["apk", "info", "-e", "postgresql-libs"]


def test_probe_does_not_leak_stderr_canary(capsys: pytest.CaptureFixture[str]) -> None:
    result = _probe_apk_package_presence(
        "ca-certificates",
        timeout_seconds=1,
        subprocess_runner=_subprocess_runner_with_return_code(2),
    )
    assert result.status is ApkPresenceStatus.QUERY_FAILED

    with pytest.raises(AlpineOsPackageValidationError) as exc:
        validate_backend_alpine_os_packages(
            inventory_runner=_inventory_runner(set(REQUIRED_RUNTIME_APK_PACKAGES)),
            presence_probe=lambda _package: result,
            required_packages=("ca-certificates",),
            forbidden_packages=(),
            os_release_reader=_os_release_alpine_324,
            validate_python_version=False,
        )
    captured = capsys.readouterr()
    assert str(exc.value) == "APK_QUERY_FAILED"
    assert "access_token" not in captured.err
    assert "secret-canary" not in captured.err
