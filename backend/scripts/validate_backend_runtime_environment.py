"""Fail-closed runtime checks for production backend container images."""

from __future__ import annotations

import importlib
import os
import sys
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from importlib.metadata import distributions
from pathlib import Path
from types import ModuleType

SUCCESS_MESSAGE = "backend runtime environment validation passed"

FORBIDDEN_DISTRIBUTIONS: frozenset[str] = frozenset(
    {
        "pip",
        "wheel",
        "jaraco.context",
    }
)
FORBIDDEN_MODULES: frozenset[str] = frozenset(
    {
        "pip",
        "wheel",
        "jaraco.context",
    }
)
REQUIRED_RUNTIME_MODULES: tuple[str, ...] = (
    "fastapi",
    "starlette",
    "pydantic",
    "uvicorn",
    "sqlalchemy",
    "alembic",
    "psycopg2",
    "jose",
    "cryptography",
    "app.core.security",
    "app.integrations.amazon.token_encryption",
)


@dataclass(frozen=True)
class RuntimeEnvironmentError(Exception):
    reason_code: str

    def __str__(self) -> str:
        return self.reason_code


DistributionProbe = Callable[[], Iterable[tuple[str, str | None]]]
ImportProbe = Callable[[str], ModuleType]


def normalize_distribution_name(name: str) -> str:
    return name.lower().replace("_", "-").replace(".", "-")


def _default_distribution_probe() -> Iterable[tuple[str, str | None]]:
    for dist in distributions():
        metadata_name = dist.metadata["Name"]
        if not metadata_name:
            continue
        yield metadata_name, dist.version


def _default_import_probe(module_name: str) -> ModuleType:
    return importlib.import_module(module_name)


def _distribution_present(name: str, probe: DistributionProbe) -> bool:
    target = normalize_distribution_name(name)
    for dist_name, _version in probe():
        if normalize_distribution_name(dist_name) == target:
            return True
    return False


def _module_importable(module_name: str, import_probe: ImportProbe) -> bool:
    try:
        import_probe(module_name)
    except ImportError:
        return False
    except Exception:
        raise RuntimeEnvironmentError("FORBIDDEN_MODULE_PROBE_FAILED") from None
    return True


def validate_backend_runtime_environment(
    *,
    distribution_probe: DistributionProbe | None = None,
    import_probe: ImportProbe | None = None,
    required_modules: Sequence[str] = REQUIRED_RUNTIME_MODULES,
    prepare_import_environment: Callable[[], None] | None = None,
) -> None:
    dist_probe = distribution_probe or _default_distribution_probe
    mod_probe = import_probe or _default_import_probe

    for distribution_name in sorted(FORBIDDEN_DISTRIBUTIONS):
        try:
            present = _distribution_present(distribution_name, dist_probe)
        except Exception:
            raise RuntimeEnvironmentError("FORBIDDEN_DISTRIBUTION_PROBE_FAILED") from None
        if present:
            raise RuntimeEnvironmentError(f"FORBIDDEN_DISTRIBUTION_PRESENT:{distribution_name}")

    for module_name in sorted(FORBIDDEN_MODULES):
        try:
            importable = _module_importable(module_name, mod_probe)
        except RuntimeEnvironmentError:
            raise
        except Exception:
            raise RuntimeEnvironmentError("FORBIDDEN_MODULE_PROBE_FAILED") from None
        if importable:
            raise RuntimeEnvironmentError(f"FORBIDDEN_MODULE_IMPORTABLE:{module_name}")

    if prepare_import_environment is not None:
        try:
            prepare_import_environment()
        except Exception:
            raise RuntimeEnvironmentError("IMPORT_ENVIRONMENT_PREP_FAILED") from None

    for module_name in required_modules:
        try:
            ok = _module_importable(module_name, mod_probe)
        except RuntimeEnvironmentError:
            raise
        except Exception:
            raise RuntimeEnvironmentError("REQUIRED_MODULE_PROBE_FAILED") from None
        if not ok:
            raise RuntimeEnvironmentError(f"REQUIRED_MODULE_MISSING:{module_name}")


def _default_prepare_import_environment() -> None:
    app_root = str(Path(__file__).resolve().parent.parent)
    if app_root not in sys.path:
        sys.path.insert(0, app_root)
    os.environ.setdefault("ENVIRONMENT", "testing")
    os.environ.setdefault("AMAZON_SP_API_ENDPOINT_MODE", "mock")
    os.environ.setdefault(
        "DATABASE_URL",
        "postgresql://sellerai:sellerai123@localhost:5432/sellerai_test",
    )
    os.environ.setdefault("OPENAI_API_KEY", "runtime-smoke-not-used")


def main() -> int:
    try:
        validate_backend_runtime_environment(
            prepare_import_environment=_default_prepare_import_environment,
        )
    except RuntimeEnvironmentError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except Exception:
        print("RUNTIME_ENVIRONMENT_VALIDATION_FAILED", file=sys.stderr)
        return 1
    print(SUCCESS_MESSAGE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
