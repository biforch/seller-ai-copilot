"""Static fail-closed checks for pinned container base images.

Scans an explicit allowlist of Dockerfiles, Compose files, and CI workflow
definitions. Does not access the network or Docker daemon.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
POLICY_DOC = REPO_ROOT / "docs" / "runtime-image-policy.md"

SCAN_TARGETS = (
    REPO_ROOT / "backend" / "Dockerfile",
    REPO_ROOT / "backend" / "Dockerfile.prod",
    REPO_ROOT / "frontend" / "Dockerfile",
    REPO_ROOT / "frontend" / "Dockerfile.prod",
    REPO_ROOT / "nginx" / "Dockerfile.rc",
    REPO_ROOT / "docker-compose.yml",
    REPO_ROOT / "docker-compose.rc.yml",
    REPO_ROOT / ".github" / "workflows" / "quality.yml",
)

EXPECTED_SCAN_FILE_COUNT = len(SCAN_TARGETS)
EXPECTED_EXTERNAL_PINNED_REF_COUNT = 13
EXPECTED_INTERNAL_BUILD_REF_COUNT = 4

INTERNAL_BUILD_IMAGES = frozenset(
    {
        "sellerai-backend-prod:rc",
        "sellerai-frontend-prod:rc",
        "sellerai-nginx-prod:rc",
    }
)

ALLOWED_REGISTRIES = frozenset(
    {
        "",
        "docker.io",
        "index.docker.io",
        "registry-1.docker.io",
    }
)

DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
FROM_LINE = re.compile(
    r"^\s*FROM\s+(?P<ref>\S+)(?:\s+AS\s+(?P<alias>[A-Za-z0-9_.-]+))?\s*(?:#.*)?$",
    re.IGNORECASE,
)
COMPOSE_IMAGE = re.compile(
    r"^\s*image:\s*(?P<ref>.+?)\s*(?:#.*)?$",
)
WORKFLOW_SERVICE_IMAGE = re.compile(
    r"^\s*image:\s*(?P<ref>\S+)\s*(?:#.*)?$",
)
POLICY_IMAGE_DIGEST = re.compile(
    r"`([a-z0-9._/-]+:[^`]+)`\s*\|\s*`(sha256:[0-9a-f]{64})`",
)

SUCCESS_MESSAGE = "Container base image pin validation passed"


@dataclass(frozen=True)
class InventoryStats:
    scanned_files: int
    external_pinned_refs: int
    internal_build_refs: int


@dataclass(frozen=True)
class Finding:
    path: Path
    line_no: int
    reason: str


def _relative(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _split_registry(image_ref: str) -> tuple[str, str]:
    if "/" not in image_ref:
        return "", image_ref
    first, remainder = image_ref.split("/", 1)
    if "." in first or first == "localhost" or ":" in first:
        return first, remainder
    return "", image_ref


def _validate_external_image(path: Path, line_no: int, ref: str) -> list[Finding]:
    findings: list[Finding] = []

    if "$" in ref or "{" in ref or "}" in ref:
        return [
            Finding(
                path,
                line_no,
                "image reference must not use variable substitution",
            )
        ]

    if ref.lower() == "scratch":
        return []

    if DIGEST_PATTERN.fullmatch(ref):
        return [
            Finding(
                path,
                line_no,
                "image reference must include human-readable tag before @sha256 digest",
            )
        ]

    if ":latest" in ref.lower() or ref.lower().endswith(":latest"):
        return [Finding(path, line_no, "latest tag is not allowed")]

    if "@" not in ref:
        return [Finding(path, line_no, "base image must pin digest with tag@sha256:<64hex>")]

    image_part, digest_part = ref.rsplit("@", 1)
    if not DIGEST_PATTERN.fullmatch(digest_part):
        return [Finding(path, line_no, "digest must be sha256:<64 lowercase hex>")]

    if ":" not in image_part:
        return [
            Finding(
                path,
                line_no,
                "image reference must include human-readable tag before @sha256 digest",
            )
        ]

    registry, _repository = _split_registry(image_part)
    if registry not in ALLOWED_REGISTRIES:
        return [Finding(path, line_no, "registry is not approved for base images")]

    return findings


def _scan_dockerfile(path: Path, content: str) -> tuple[list[Finding], list[tuple[Path, int, str]], int]:
    findings: list[Finding] = []
    external_refs: list[tuple[Path, int, str]] = []
    known_stages: set[str] = set()

    for line_no, line in enumerate(content.splitlines(), start=1):
        match = FROM_LINE.match(line)
        if not match:
            continue

        ref = match.group("ref")
        alias = match.group("alias")

        if ref.lower() == "scratch":
            if alias:
                known_stages.add(alias)
            continue

        if "@" not in ref and ":" not in ref and "/" not in ref and "$" not in ref and "{" not in ref:
            if ref in known_stages:
                if alias:
                    known_stages.add(alias)
                continue
            findings.append(Finding(path, line_no, f"unknown stage alias {ref!r}"))
            continue

        findings.extend(_validate_external_image(path, line_no, ref))
        external_refs.append((path, line_no, ref))
        if alias:
            known_stages.add(alias)

    return findings, external_refs, 0


@dataclass
class ComposeService:
    name: str
    has_build: bool = False
    images: list[str] = field(default_factory=list)


def _parse_compose_services(content: str) -> list[ComposeService]:
    services: list[ComposeService] = []
    current: ComposeService | None = None

    for line in content.splitlines():
        if re.match(r"^services:\s*$", line):
            continue
        service_match = re.match(r"^  ([a-zA-Z0-9_.-]+):\s*$", line)
        if service_match:
            if current is not None:
                services.append(current)
            current = ComposeService(name=service_match.group(1))
            continue
        if current is None:
            continue
        if re.match(r"^[a-zA-Z]", line):
            if current is not None:
                services.append(current)
            current = None
            continue
        if re.match(r"^\s+build:", line):
            current.has_build = True
            continue
        image_match = COMPOSE_IMAGE.match(line)
        if image_match:
            ref = image_match.group("ref").strip().strip("'\"")
            current.images.append(ref)

    if current is not None:
        services.append(current)
    return services


def _internal_build_image_name(ref: str) -> str | None:
    image_part = ref.split("@", 1)[0]
    registry, repository = _split_registry(image_part)
    if registry not in ALLOWED_REGISTRIES:
        return None
    if repository in INTERNAL_BUILD_IMAGES:
        return repository
    return None


def _scan_compose(path: Path, content: str) -> tuple[list[Finding], list[tuple[Path, int, str]], int]:
    findings: list[Finding] = []
    external_refs: list[tuple[Path, int, str]] = []
    internal_refs = 0

    for line_no, line in enumerate(content.splitlines(), start=1):
        match = COMPOSE_IMAGE.match(line)
        if not match:
            continue

        ref = match.group("ref").strip().strip("'\"")
        if ref in INTERNAL_BUILD_IMAGES:
            internal_refs += 1
            continue

        internal_name = _internal_build_image_name(ref)
        if internal_name is not None:
            internal_refs += 1
            findings.append(
                Finding(path, line_no, "internal build image must not include registry hostname")
            )
            continue

        findings.extend(_validate_external_image(path, line_no, ref))
        external_refs.append((path, line_no, ref))

    for service in _parse_compose_services(content):
        for ref in service.images:
            if ref in INTERNAL_BUILD_IMAGES:
                if not service.has_build:
                    findings.append(
                        Finding(
                            path,
                            0,
                            f"service {service.name!r} uses internal image {ref!r} without build configuration",
                        )
                    )
                continue
            if service.has_build and "@" not in ref and "/" not in ref.split("@", 1)[0]:
                findings.append(
                    Finding(
                        path,
                        0,
                        f"locally-built image {ref!r} is not on the internal allowlist",
                    )
                )

    for line_no, line in enumerate(content.splitlines(), start=1):
        match = COMPOSE_IMAGE.match(line)
        if not match:
            continue
        ref = match.group("ref").strip().strip("'\"")
        if ref in INTERNAL_BUILD_IMAGES:
            continue
        if "@" not in ref and service_has_build_nearby(content, line_no):
            findings.append(
                Finding(
                    path,
                    line_no,
                    "external image must remain digest-pinned even when service defines build",
                )
            )

    return findings, external_refs, internal_refs


def service_has_build_nearby(content: str, image_line_no: int) -> bool:
    lines = content.splitlines()
    service_start = image_line_no - 1
    while service_start >= 0:
        if re.match(r"^  ([a-zA-Z0-9_.-]+):\s*$", lines[service_start]):
            break
        service_start -= 1
    if service_start < 0:
        return False
    for line in lines[service_start:image_line_no]:
        if re.match(r"^\s+build:", line):
            return True
    return False


def _scan_workflow(path: Path, content: str) -> tuple[list[Finding], list[tuple[Path, int, str]], int]:
    findings: list[Finding] = []
    external_refs: list[tuple[Path, int, str]] = []
    in_services = False

    for line_no, line in enumerate(content.splitlines(), start=1):
        if re.match(r"^    services:\s*$", line):
            in_services = True
            continue

        if in_services and re.match(r"^    \S", line) and not re.match(r"^      ", line):
            in_services = False

        if not in_services:
            continue

        match = re.match(r"^        image:\s*(?P<ref>\S+)", line)
        if not match:
            continue

        ref = match.group("ref")
        if "${{" in ref:
            findings.append(
                Finding(path, line_no, "service image digest must be static and not use workflow interpolation")
            )
            continue
        findings.extend(_validate_external_image(path, line_no, ref))
        external_refs.append((path, line_no, ref))

    return findings, external_refs, 0


def _scan_file(path: Path) -> tuple[list[Finding], list[tuple[Path, int, str]], int]:
    if not path.is_file():
        return [Finding(path, 0, "scan target is missing")], [], 0

    content = path.read_text(encoding="utf-8")
    name = path.name.lower()

    if name.startswith("dockerfile"):
        return _scan_dockerfile(path, content)
    if name.startswith("docker-compose") and name.endswith((".yml", ".yaml")):
        return _scan_compose(path, content)
    if path.suffix in {".yml", ".yaml"} and "workflows" in path.parts:
        return _scan_workflow(path, content)

    return [Finding(path, 0, "unsupported scan target type")], [], 0


def _check_consistent_digests(findings: list[Finding], refs: list[tuple[Path, int, str]]) -> None:
    tag_to_digest: dict[str, str] = {}
    for path, line_no, ref in refs:
        if "@" not in ref:
            continue
        image_part, digest_part = ref.rsplit("@", 1)
        existing = tag_to_digest.get(image_part)
        if existing is None:
            tag_to_digest[image_part] = digest_part
            continue
        if existing != digest_part:
            findings.append(
                Finding(
                    path,
                    line_no,
                    f"inconsistent digest for {image_part}",
                )
            )


def _check_policy_doc_consistency(findings: list[Finding], refs: list[tuple[Path, int, str]]) -> None:
    if not POLICY_DOC.is_file():
        findings.append(Finding(POLICY_DOC, 0, "runtime image policy document is missing"))
        return

    policy_content = POLICY_DOC.read_text(encoding="utf-8")
    policy_map: dict[str, str] = {}
    for image_ref, digest in POLICY_IMAGE_DIGEST.findall(policy_content):
        policy_map[image_ref] = digest

    code_map: dict[str, str] = {}
    for _path, _line_no, ref in refs:
        if "@" not in ref:
            continue
        image_part, digest_part = ref.rsplit("@", 1)
        code_map[image_part] = digest_part

    for image_part, digest_part in code_map.items():
        policy_digest = policy_map.get(image_part)
        if policy_digest is None:
            findings.append(
                Finding(
                    POLICY_DOC,
                    0,
                    f"policy document missing digest entry for {image_part}",
                )
            )
            continue
        if policy_digest != digest_part:
            findings.append(
                Finding(
                    POLICY_DOC,
                    0,
                    f"policy digest for {image_part} does not match repository configuration",
                )
            )


def validate_container_image_pins() -> tuple[list[Finding], InventoryStats]:
    findings: list[Finding] = []
    scanned_files = 0
    external_refs: list[tuple[Path, int, str]] = []
    internal_build_refs = 0

    for target in SCAN_TARGETS:
        file_findings, file_external_refs, file_internal_refs = _scan_file(target)
        findings.extend(file_findings)
        if target.is_file():
            scanned_files += 1
            external_refs.extend(file_external_refs)
            internal_build_refs += file_internal_refs

    _check_consistent_digests(findings, external_refs)
    _check_policy_doc_consistency(findings, external_refs)

    if scanned_files != EXPECTED_SCAN_FILE_COUNT:
        findings.append(
            Finding(
                REPO_ROOT,
                0,
                f"expected {EXPECTED_SCAN_FILE_COUNT} scan files, found {scanned_files}",
            )
        )

    external_count = len(external_refs)
    if external_count != EXPECTED_EXTERNAL_PINNED_REF_COUNT:
        findings.append(
            Finding(
                REPO_ROOT,
                0,
                (
                    "expected "
                    f"{EXPECTED_EXTERNAL_PINNED_REF_COUNT} external pinned references, "
                    f"found {external_count}"
                ),
            )
        )

    if internal_build_refs != EXPECTED_INTERNAL_BUILD_REF_COUNT:
        findings.append(
            Finding(
                REPO_ROOT,
                0,
                (
                    "expected "
                    f"{EXPECTED_INTERNAL_BUILD_REF_COUNT} internal build references, "
                    f"found {internal_build_refs}"
                ),
            )
        )

    stats = InventoryStats(
        scanned_files=scanned_files,
        external_pinned_refs=external_count,
        internal_build_refs=internal_build_refs,
    )
    return findings, stats


def main() -> int:
    findings, stats = validate_container_image_pins()
    if findings:
        for finding in findings:
            rel = _relative(finding.path)
            if finding.line_no:
                print(f"{rel}:{finding.line_no}: {finding.reason}", file=sys.stderr)
            else:
                print(f"{rel}: {finding.reason}", file=sys.stderr)
        return 1

    print(
        f"{SUCCESS_MESSAGE} "
        f"({stats.scanned_files} files scanned, "
        f"{stats.external_pinned_refs} external pinned references, "
        f"{stats.internal_build_refs} internal build references)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
