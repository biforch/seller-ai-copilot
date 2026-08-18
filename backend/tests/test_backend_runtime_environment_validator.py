"""Tests for production backend runtime environment validator."""

from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout
from types import ModuleType

import pytest

from scripts.validate_backend_runtime_environment import (
    SUCCESS_MESSAGE,
    RuntimeEnvironmentError,
    normalize_distribution_name,
    validate_backend_runtime_environment,
)


class _FakeModule(ModuleType):
    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.__file__ = f"/virtual/{name.replace('.', '/')}.py"


CANARY_SECRET = "CANARY_RUNTIME_VALIDATOR_SECRET_MARKER"


def _clean_distribution_probe() -> list[tuple[str, str | None]]:
    return [
        ("fastapi", "0.133.0"),
        ("starlette", "1.6.0"),
        ("cryptography", "50.0.0"),
    ]


def _import_map(modules: set[str]) -> callable:
    def _probe(module_name: str) -> ModuleType:
        if module_name not in modules:
            raise ImportError(module_name)
        return _FakeModule(module_name)

    return _probe


def test_normalize_distribution_name_treats_equivalent_names() -> None:
    assert normalize_distribution_name("jaraco.context") == "jaraco-context"
    assert normalize_distribution_name("Jaraco_Context") == "jaraco-context"
    assert normalize_distribution_name("pip") == "pip"


def test_clean_runtime_passes() -> None:
    validate_backend_runtime_environment(
        distribution_probe=_clean_distribution_probe,
        import_probe=_import_map({"fastapi", "starlette"}),
        prepare_import_environment=lambda: None,
        required_modules=("fastapi", "starlette"),
    )


def test_forbidden_distribution_pip_rejected() -> None:
    with pytest.raises(RuntimeEnvironmentError, match="FORBIDDEN_DISTRIBUTION_PRESENT:pip"):
        validate_backend_runtime_environment(
            distribution_probe=lambda: [("pip", "24.0"), ("fastapi", "0.133.0")],
            import_probe=_import_map({"fastapi"}),
            prepare_import_environment=lambda: None,
            required_modules=("fastapi",),
        )


def test_forbidden_distribution_wheel_rejected() -> None:
    with pytest.raises(RuntimeEnvironmentError, match="FORBIDDEN_DISTRIBUTION_PRESENT:wheel"):
        validate_backend_runtime_environment(
            distribution_probe=lambda: [("wheel", "0.45.0")],
            import_probe=_import_map(set()),
            prepare_import_environment=lambda: None,
            required_modules=(),
        )


def test_forbidden_distribution_jaraco_context_rejected() -> None:
    with pytest.raises(RuntimeEnvironmentError, match="FORBIDDEN_DISTRIBUTION_PRESENT:jaraco.context"):
        validate_backend_runtime_environment(
            distribution_probe=lambda: [("jaraco.context", "6.0.0")],
            import_probe=_import_map(set()),
            prepare_import_environment=lambda: None,
            required_modules=(),
        )


    with pytest.raises(RuntimeEnvironmentError, match="REQUIRED_MODULE_MISSING:cryptography"):
        validate_backend_runtime_environment(
            distribution_probe=_clean_distribution_probe,
            import_probe=_import_map({"fastapi", "starlette"}),
            prepare_import_environment=lambda: None,
            required_modules=("fastapi", "cryptography"),
        )


def test_distribution_probe_exception_fail_closed() -> None:
    def _broken_probe() -> list[tuple[str, str | None]]:
        raise RuntimeError(CANARY_SECRET)

    with pytest.raises(RuntimeEnvironmentError, match="FORBIDDEN_DISTRIBUTION_PROBE_FAILED"):
        validate_backend_runtime_environment(
            distribution_probe=_broken_probe,
            import_probe=_import_map(set()),
            prepare_import_environment=lambda: None,
            required_modules=(),
        )


def test_import_probe_exception_fail_closed() -> None:
    def _broken_import(_: str) -> ModuleType:
        raise RuntimeError(CANARY_SECRET)

    with pytest.raises(RuntimeEnvironmentError, match="FORBIDDEN_MODULE_PROBE_FAILED"):
        validate_backend_runtime_environment(
            distribution_probe=_clean_distribution_probe,
            import_probe=_broken_import,
            prepare_import_environment=lambda: None,
            required_modules=(),
        )


def test_main_success_message(monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import validate_backend_runtime_environment as module

    monkeypatch.setattr(
        module,
        "validate_backend_runtime_environment",
        lambda **_: None,
    )
    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        exit_code = module.main()
    assert exit_code == 0
    assert stdout.getvalue().strip() == SUCCESS_MESSAGE
    assert CANARY_SECRET not in stdout.getvalue()
    assert CANARY_SECRET not in stderr.getvalue()


def test_main_failure_does_not_leak_canary() -> None:
    from scripts import validate_backend_runtime_environment as module

    original = module.validate_backend_runtime_environment

    def _raise_canary(**_: object) -> None:
        raise RuntimeError(CANARY_SECRET)

    module.validate_backend_runtime_environment = _raise_canary  # type: ignore[assignment]
    stderr = io.StringIO()
    try:
        with redirect_stderr(stderr):
            exit_code = module.main()
    finally:
        module.validate_backend_runtime_environment = original  # type: ignore[assignment]
    assert exit_code == 1
    assert stderr.getvalue().strip() == "RUNTIME_ENVIRONMENT_VALIDATION_FAILED"
    assert CANARY_SECRET not in stderr.getvalue()
