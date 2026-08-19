"""Validate installed distributions and Requires-Dist within a target site-packages tree."""

from __future__ import annotations

import sys
from importlib.metadata import Distribution, distributions
from pathlib import Path

try:
    from alpine_wheel_audit_common import normalize_package_name
except ImportError:  # pragma: no cover - local pytest imports via scripts package path
    from scripts.alpine_wheel_audit_common import normalize_package_name

try:
    from packaging.requirements import Requirement
    from packaging.version import InvalidVersion, Version
except ImportError:  # pragma: no cover - packaging is a runtime dependency of pip/pydantic
    Requirement = None  # type: ignore[misc, assignment]
    Version = None  # type: ignore[misc, assignment]
    InvalidVersion = Exception  # type: ignore[misc, assignment]


def _distribution_map(target: Path) -> dict[str, Distribution]:
    mapped: dict[str, Distribution] = {}
    for dist in distributions(path=[str(target)]):
        name = dist.metadata["Name"]
        if not name:
            continue
        mapped[normalize_package_name(name)] = dist
    return mapped


def validate_target_site_packages(target: Path) -> tuple[str, list[str]]:
    if Requirement is None or Version is None:
        return "failed", ["packaging_unavailable"]

    if not target.is_dir():
        return "failed", ["target_missing"]

    dist_map = _distribution_map(target)
    if not dist_map:
        return "failed", ["target_empty"]

    issues: list[str] = []
    env = {"python_version": "3.11", "os_name": "posix", "sys_platform": "linux", "platform_system": "Linux"}
    for dist in dist_map.values():
        for req_str in dist.requires or []:
            requirement = Requirement(req_str)
            if requirement.marker is not None and not requirement.marker.evaluate(env):
                continue
            dep_name = normalize_package_name(requirement.name)
            installed = dist_map.get(dep_name)
            if installed is None:
                issues.append(f"missing:{dep_name}")
                continue
            try:
                installed_version = Version(installed.version)
            except InvalidVersion:
                issues.append(f"invalid_version:{dep_name}")
                continue
            if requirement.specifier and not requirement.specifier.contains(installed_version, prereleases=True):
                issues.append(f"version:{dep_name}")

    return ("ok" if not issues else "failed"), sorted(set(issues))


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1:
        print("usage: validate_target_site_packages.py <target-site-packages>", file=sys.stderr)
        return 2
    status, issues = validate_target_site_packages(Path(args[0]))
    if status != "ok":
        for issue in issues:
            print(issue, file=sys.stderr)
        return 1
    print("target dependency validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
