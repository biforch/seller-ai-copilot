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
    REPO_ROOT / "backend" / "Dockerfile.alpine-candidate",
    REPO_ROOT / "frontend" / "Dockerfile",
    REPO_ROOT / "frontend" / "Dockerfile.prod",
    REPO_ROOT / "nginx" / "Dockerfile.rc",
    REPO_ROOT / "docker-compose.yml",
    REPO_ROOT / "docker-compose.rc.yml",
    REPO_ROOT / ".github" / "workflows" / "quality.yml",
)

EXPECTED_SCAN_FILE_COUNT = len(SCAN_TARGETS)
EXPECTED_RUNTIME_EXTERNAL_PINNED_REF_COUNT = 15
EXPECTED_INTERNAL_BUILD_REF_COUNT = 4
EXPECTED_SCANNER_PINNED_REF_COUNT = 14
EXPECTED_SCANNER_APPROVED_IDENTITY_COUNT = 6

ALLOWED_SCANNER_SHELL_VARS = frozenset(
    {
        "SYFT_IMAGE",
        "TRIVY_IMAGE",
        "RUNNER_TEMP",
        "RUNNER_UID",
        "RUNNER_GID",
        "IMAGE_TAG",
        "TRIVY_CACHE_DIR",
        "SCAN_INPUT",
        "SCAN_OUTPUT",
        "ALPINE_CANDIDATE_INDEX_REF",
        "ALPINE_CANDIDATE_AMD64_REF",
        "ALPINE_CANDIDATE_ARM64_REF",
        "ALPINE_AUDIT_INPUT",
        "ALPINE_AUDIT_OUTPUT",
        "ALPINE_TRIVY_CACHE_DIR",
        "HARDENED_INPUT",
        "HARDENED_OUTPUT",
        "HARDENED_TRIVY_CACHE_DIR",
        "CLEANUP_TARGET",
    }
)

APPROVED_AUDIT_CANDIDATES = frozenset(
    {
        "python:3.11-alpine3.24@sha256:6857d2dae63e052057f2db389a7061188ac9a92a3fa8d402bde68f36df6fada1",
        "python:3.11-alpine3.24@sha256:cc19a3e1085aba7d26690cf0725d9a3e083cbea0feec34ba8133d40a8ac1d399",
        "python:3.11-alpine3.24@sha256:df8376721de6f98515643fca8e7aac56e6a39bc178697a1d8c020ffa050b655e",
    }
)

CONTAINERS_JOB_NAME = "containers"
ALPINE_CANDIDATE_JOB_NAME = "backend-alpine-candidate-audit"
ALPINE_HARDENED_JOB_NAME = "backend-alpine-hardened-candidate"

APPROVED_BUILD_ACTIONS = frozenset(
    {
        "docker/setup-qemu-action@c7c53464625b32c7a7e944ae62b3e17d2b600130",
        "docker/setup-buildx-action@8d2750c68a42422c14e847fe6c8ac0403b4cbd6f",
    }
)

ALPINE_CANDIDATE_DOCKERFILE = REPO_ROOT / "backend" / "Dockerfile.alpine-candidate"

SCANNER_FORBIDDEN_WORKFLOW_PATTERNS = (
    (re.compile(r"/var/run/docker\.sock"), "workflow must not mount Docker socket into scanner containers"),
    (re.compile(r"--privileged\b"), "scanner containers must not run privileged"),
    (re.compile(r"--network\s+host\b"), "scanner containers must not use host network"),
    (re.compile(r"--net\s+host\b"), "scanner containers must not use host network"),
    (re.compile(r"--env-file\b"), "scanner containers must not use env-file mounts"),
    (re.compile(r"GITHUB_WORKSPACE"), "scanner containers must not mount GitHub workspace"),
    (re.compile(r"github\.workspace"), "scanner containers must not mount GitHub workspace"),
    (re.compile(r"\$HOME"), "scanner containers must not mount user home directories"),
)
SCANNER_FORBIDDEN_CREDENTIAL_ENV = re.compile(
    r"-e\s+(?:GITHUB_TOKEN|AWS_|AMAZON_|OPENAI_|JWT_|POSTGRES_|DATABASE_|"
    r"NPM_TOKEN|REGISTRY_|DOCKER_AUTH|client_secret|access_token|refresh_token)",
    re.IGNORECASE,
)
TRIVY_STEP_NAME = "Generate Trivy vulnerability reports"
ALPINE_TRIVY_STEP_NAME = "Generate Alpine candidate Trivy reports"
ALPINE_SYFT_STEP_NAME = "Generate Alpine candidate CycloneDX SBOMs"
CLEANUP_STEP_NAME = "Cleanup supply-chain scan workspace"
ALPINE_CLEANUP_STEP_NAME = "Cleanup Alpine candidate audit workspace"
ALPINE_ARTIFACT_STEP_NAME = "Upload Alpine candidate audit artifacts"
ALPINE_WHEEL_AMD64_STEP = "Audit amd64 musllinux wheel install"
ALPINE_WHEEL_ARM64_STEP = "Audit arm64 musllinux wheel resolution"
ALPINE_WHEEL_VALIDATE_STEP = "Validate Alpine candidate wheel manifests"
ALPINE_POLICY_STEP = "Evaluate Alpine candidate vulnerability policy"
ALPINE_SBOM_VALIDATE_STEP = "Validate Alpine candidate SBOM artifacts"
ALPINE_TRIVY_GENERATE_STEP = "Generate Alpine candidate Trivy reports"
ALPINE_HARDENED_SYFT_STEP = "Generate hardened Alpine candidate CycloneDX SBOMs"
ALPINE_HARDENED_TRIVY_STEP = "Generate hardened Alpine candidate Trivy reports"
ALPINE_HARDENED_SBOM_VALIDATE_STEP = "Validate hardened Alpine candidate SBOM artifacts"
ALPINE_HARDENED_POLICY_STEP = "Evaluate hardened Alpine candidate vulnerability policy"
ALPINE_HARDENED_ARTIFACT_STEP = "Upload hardened Alpine candidate artifacts"
ALPINE_HARDENED_CLEANUP_STEP = "Cleanup Alpine hardened candidate workspace"
ALPINE_HARDENED_AMD64_BUILD_STEP = "Build amd64 hardened Alpine backend candidate"
ALPINE_HARDENED_AMD64_SMOKE_STEP = "Run amd64 hardened runtime and smoke validation"
ALPINE_HARDENED_ARM64_BUILD_STEP = "Build arm64 hardened Alpine backend candidate"
ALPINE_HARDENED_ARM64_VERIFY_STEP = "Run arm64 build-only verification"
RUNTIME_SMOKE_STEP_NAME = "Validate backend production runtime environment"
FRONTEND_RUNTIME_SMOKE_STEP_NAME = "Validate frontend production runtime environment"

ALLOWED_SCANNER_IMAGES = frozenset(
    {
        "anchore/syft:v1.51.0@sha256:678bfa565b60f747aac0f8e964fe5588a24445b8d0a480e91f6efd70020dfbb0",
        "aquasec/trivy:0.74.0@sha256:62b1e65e8869bc4b4c6aa4fa2b21595256c7c2f6018a9d9ad61caf87187c1969",
    }
)

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
    scanner_pinned_refs: int


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

    if ref in ALLOWED_SCANNER_IMAGES:
        return [
            Finding(
                path,
                line_no,
                "scanner image must not be used as a runtime base image",
            )
        ]

    if ref in APPROVED_AUDIT_CANDIDATES:
        return [
            Finding(
                path,
                line_no,
                "approved audit candidate image must not be used as runtime base image",
            )
        ]

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


def _validate_alpine_candidate_dockerfile_content(path: Path, content: str) -> list[Finding]:
    findings: list[Finding] = []
    required_tokens = (
        "AS wheels",
        "AS install",
        "AS runtime",
        "pip download --only-binary=:all:",
        "pip install --no-index",
        "apk add --no-cache",
        "ca-certificates",
        "libstdc++",
        "postgresql-libs",
        "pip uninstall -y jaraco.context wheel setuptools",
        "pip uninstall -y pip",
        "validate_backend_runtime_environment.py",
        "validate_backend_alpine_os_packages.py",
        "USER app",
        'CMD ["uvicorn", "app.main:app"',
    )
    for token in required_tokens:
        if token not in content:
            findings.append(Finding(path, 0, f"Alpine candidate Dockerfile must include {token!r}"))

    forbidden_apk_packages = (
        "perl",
        "util-linux",
        "curl",
        "gcc",
        "musl-dev",
        "postgresql-dev",
        "build-base",
    )
    for line_no, line in enumerate(content.splitlines(), start=1):
        if "apk add" not in line:
            continue
        for pkg in forbidden_apk_packages:
            if pkg in line:
                findings.append(
                    Finding(path, line_no, f"Alpine candidate Dockerfile must not apk add {pkg!r}")
                )

    for token in ("--trusted-host", "PIP_INDEX_URL", "PIP_EXTRA_INDEX_URL"):
        if token in content:
            findings.append(Finding(path, 0, f"Alpine candidate Dockerfile must not include {token!r}"))

    if "DATABASE_URL=" in content:
        db_fragment = content.split("DATABASE_URL=", 1)[-1].split("\n", 1)[0]
        if "@" in db_fragment or "://" in db_fragment and "://" in db_fragment.split("://", 1)[-1]:
            if "postgresql://localhost" not in db_fragment:
                findings.append(
                    Finding(path, 0, "Alpine candidate Dockerfile must not embed credential DATABASE_URL")
                )
    return findings


def _scan_dockerfile(path: Path, content: str) -> tuple[list[Finding], list[tuple[Path, int, str]], int]:
    findings: list[Finding] = []
    external_refs: list[tuple[Path, int, str]] = []
    known_stages: set[str] = set()

    if path.name == "Dockerfile.alpine-candidate":
        findings.extend(_validate_alpine_candidate_dockerfile_content(path, content))

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

        if path.name == "Dockerfile.alpine-candidate" and ref in APPROVED_AUDIT_CANDIDATES:
            external_refs.append((path, line_no, ref))
            if alias:
                known_stages.add(alias)
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


def _extract_step_run_block(content: str, step_name: str) -> str | None:
    marker = f"- name: {step_name}"
    start = content.find(marker)
    if start < 0:
        return None
    run_marker = "run: |"
    run_start = content.find(run_marker, start)
    if run_start < 0:
        return None
    body_start = content.find("\n", run_start) + 1
    lines: list[str] = []
    for line in content[body_start:].splitlines():
        if line.startswith("      - name:") or line.startswith("      uses:"):
            break
        if line.startswith("      if:"):
            break
        lines.append(line)
    return "\n".join(lines)


def _validate_trivy_scan_step(path: Path, content: str) -> list[Finding]:
    findings: list[Finding] = []
    block = _extract_step_run_block(content, TRIVY_STEP_NAME)
    if block is None:
        findings.append(Finding(path, 0, "containers job must define Generate Trivy vulnerability reports step"))
        return findings

    if not re.search(r'RUNNER_UID="\$\(id -u\)"', block):
        findings.append(Finding(path, 0, "Trivy step must capture RUNNER_UID from id -u"))
    if not re.search(r'RUNNER_GID="\$\(id -g\)"', block):
        findings.append(Finding(path, 0, "Trivy step must capture RUNNER_GID from id -g"))
    if not re.search(r'\$\{RUNNER_UID\}" =~ \^\[0-9\]\+\$', block):
        findings.append(Finding(path, 0, "Trivy step must validate RUNNER_UID as decimal digits"))
    if not re.search(r'\$\{RUNNER_GID\}" =~ \^\[0-9\]\+\$', block):
        findings.append(Finding(path, 0, "Trivy step must validate RUNNER_GID as decimal digits"))
    if "scanner-user-validated" not in block:
        findings.append(Finding(path, 0, "Trivy step must emit scanner-user-validated after uid/gid validation"))

    user_runs = re.findall(r'--user "\$\{RUNNER_UID\}:\$\{RUNNER_GID\}"', block)
    if len(user_runs) != 3:
        findings.append(
            Finding(path, 0, f"Trivy step must run three scanner containers as runner uid/gid, found {len(user_runs)}")
        )

    cache_dir_flags = re.findall(r"--cache-dir /trivy-cache", block)
    if len(cache_dir_flags) != 3:
        findings.append(
            Finding(path, 0, f"Trivy step must pass --cache-dir /trivy-cache three times, found {len(cache_dir_flags)}")
        )

    cache_mounts = re.findall(r'"\$\{TRIVY_CACHE_DIR\}:/trivy-cache:rw"', block)
    if len(cache_mounts) != 3:
        findings.append(
            Finding(path, 0, f"Trivy step must mount TRIVY_CACHE_DIR to /trivy-cache three times, found {len(cache_mounts)}")
        )

    if "/root/.cache/trivy" in block:
        findings.append(Finding(path, 0, "Trivy step must not mount root-owned default cache path"))
    if "sudo" in block or "chmod 777" in block or "--privileged" in block:
        findings.append(Finding(path, 0, "Trivy step must not use sudo, chmod 777, or privileged helpers"))
    if re.search(r"--network\s+host|--net\s+host", block):
        findings.append(Finding(path, 0, "Trivy step must not use host network"))
    if "$HOME" in block or "GITHUB_WORKSPACE" in block:
        findings.append(Finding(path, 0, "Trivy step must not mount runner home or workspace"))

    input_mounts = re.findall(r'"\$\{SCAN_INPUT\}:/input:ro"', block)
    output_mounts = re.findall(r'"\$\{SCAN_OUTPUT\}:/output:rw"', block)
    if len(input_mounts) != 3 or len(output_mounts) != 3:
        findings.append(Finding(path, 0, "Trivy step must keep input :ro and output :rw for all three scans"))

    return findings


def _validate_runtime_smoke_step(path: Path, content: str) -> list[Finding]:
    findings: list[Finding] = []
    marker = f"- name: {RUNTIME_SMOKE_STEP_NAME}"
    if marker not in content:
        findings.append(Finding(path, 0, "containers job must define backend runtime smoke step"))
        return findings

    block = _extract_step_run_block(content, RUNTIME_SMOKE_STEP_NAME)
    if block is None:
        findings.append(Finding(path, 0, "runtime smoke step must define a run block"))
        return findings

    required_tokens = (
        "docker run --rm",
        "--network none",
        "--read-only",
        "--tmpfs /tmp:rw,noexec,nosuid,nodev",
        "--cap-drop ALL",
        "--security-opt no-new-privileges",
        "sellerai-backend-ci:${IMAGE_TAG}",
        "python scripts/validate_backend_runtime_environment.py",
        "python scripts/validate_backend_os_packages.py",
        "python scripts/validate_backend_production_smoke.py",
        "-e ENVIRONMENT=testing",
        "-e AMAZON_SP_API_ENDPOINT_MODE=mock",
    )
    for token in required_tokens:
        if token not in block:
            findings.append(Finding(path, 0, f"runtime smoke step missing required contract token: {token}"))

    forbidden = (
        "sudo",
        "chmod 777",
        "|| true",
        "continue-on-error",
        "--privileged",
        "--env-file",
        "/var/run/docker.sock",
        "GITHUB_WORKSPACE",
        "github.workspace",
        "$HOME",
    )
    for token in forbidden:
        if token in block:
            findings.append(Finding(path, 0, f"runtime smoke step must not use {token}"))

    build_marker = "- name: Build production backend image"
    save_marker = "- name: Save production images for offline scan"
    if build_marker not in content or save_marker not in content:
        findings.append(Finding(path, 0, "runtime smoke step requires backend build and image save anchors"))
    else:
        build_index = content.index(build_marker)
        smoke_index = content.index(marker)
        save_index = content.index(save_marker)
        if not (build_index < smoke_index < save_index):
            findings.append(
                Finding(
                    path,
                    0,
                    "runtime smoke step must run after backend build and before image save",
                )
            )

    return findings


def _validate_frontend_runtime_smoke_step(path: Path, content: str) -> list[Finding]:
    findings: list[Finding] = []
    marker = f"- name: {FRONTEND_RUNTIME_SMOKE_STEP_NAME}"
    if marker not in content:
        findings.append(Finding(path, 0, "containers job must define frontend runtime smoke step"))
        return findings

    block = _extract_step_run_block(content, FRONTEND_RUNTIME_SMOKE_STEP_NAME)
    if block is None:
        findings.append(Finding(path, 0, "frontend runtime smoke step must define a run block"))
        return findings

    required_tokens = (
        "docker run --rm",
        "--network none",
        "--read-only",
        "--tmpfs /tmp:rw,noexec,nosuid,nodev",
        "--cap-drop ALL",
        "--security-opt no-new-privileges",
        "sellerai-frontend-ci:${IMAGE_TAG}",
        "node scripts/validate-frontend-runtime.mjs",
        "node scripts/validate-frontend-runtime.mjs --smoke",
    )
    for token in required_tokens:
        if token not in block:
            findings.append(
                Finding(path, 0, f"frontend runtime smoke step missing required contract token: {token}")
            )

    forbidden = (
        "sudo",
        "chmod 777",
        "|| true",
        "continue-on-error",
        "--privileged",
        "--env-file",
        "/var/run/docker.sock",
        "GITHUB_WORKSPACE",
        "github.workspace",
        "$HOME",
    )
    for token in forbidden:
        if token in block:
            findings.append(Finding(path, 0, f"frontend runtime smoke step must not use {token}"))

    build_marker = "- name: Build production frontend image"
    save_marker = "- name: Save production images for offline scan"
    if build_marker not in content or save_marker not in content:
        findings.append(
            Finding(path, 0, "frontend runtime smoke step requires frontend build and image save anchors")
        )
    else:
        build_index = content.index(build_marker)
        smoke_index = content.index(marker)
        save_index = content.index(save_marker)
        if not (build_index < smoke_index < save_index):
            findings.append(
                Finding(
                    path,
                    0,
                    "frontend runtime smoke step must run after frontend build and before image save",
                )
            )

    backend_smoke_marker = f"- name: {RUNTIME_SMOKE_STEP_NAME}"
    if backend_smoke_marker in content:
        backend_smoke_index = content.index(backend_smoke_marker)
        frontend_smoke_index = content.index(marker)
        if not (backend_smoke_index < frontend_smoke_index):
            findings.append(
                Finding(
                    path,
                    0,
                    "frontend runtime smoke step must run after backend runtime smoke step",
                )
            )

    return findings


def _validate_cleanup_step(path: Path, content: str) -> list[Finding]:
    findings: list[Finding] = []
    marker = f"- name: {CLEANUP_STEP_NAME}"
    if marker not in content:
        findings.append(Finding(path, 0, "containers job must define cleanup step"))
        return findings

    cleanup_section = content.split(marker, 1)[1].split("- name:", 1)[0]
    if "if: always()" not in cleanup_section:
        findings.append(Finding(path, 0, "cleanup step must use if: always()"))

    block = _extract_step_run_block(content, CLEANUP_STEP_NAME)
    if block is None:
        findings.append(Finding(path, 0, "cleanup step must define a run block"))
        return findings

    if 'rm -rf "${CLEANUP_TARGET}"' not in block:
        findings.append(Finding(path, 0, "cleanup step must remove sellerai-scan workspace via CLEANUP_TARGET"))
    if ": \"${RUNNER_TEMP:?RUNNER_TEMP must be set}\"" not in block:
        findings.append(Finding(path, 0, "cleanup step must fail closed when RUNNER_TEMP is unset"))
    if 'CLEANUP_TARGET="${RUNNER_TEMP}/sellerai-scan"' not in block:
        findings.append(Finding(path, 0, "cleanup step must define a fixed CLEANUP_TARGET"))
    if '[[ "${CLEANUP_TARGET}" == "/" ]]' not in block:
        findings.append(Finding(path, 0, "cleanup step must reject root cleanup target"))
    if '[[ "${CLEANUP_TARGET}" == "${RUNNER_TEMP}" ]]' not in block:
        findings.append(Finding(path, 0, "cleanup step must reject RUNNER_TEMP itself as cleanup target"))

    forbidden = ("sudo", "chmod 777", "|| true", "continue-on-error", "docker run")
    for token in forbidden:
        if token in block:
            findings.append(Finding(path, 0, f"cleanup step must not use {token}"))

    return findings


def _validate_scanner_env_line(path: Path, line_no: int, line: str, var_name: str) -> list[Finding]:
    findings: list[Finding] = []
    if "${{" in line:
        findings.append(
            Finding(
                path,
                line_no,
                f"{var_name} must not use workflow interpolation",
            )
        )
    if re.search(r"\b(secrets|inputs|vars)\.", line):
        findings.append(
            Finding(
                path,
                line_no,
                f"{var_name} must not reference secrets, inputs, or repository variables",
            )
        )
    value_match = re.match(rf"^\s+{var_name}:\s*(?P<ref>\S+)\s*(?:#.*)?$", line)
    if not value_match:
        findings.append(Finding(path, line_no, f"{var_name} must define a static pinned scanner reference"))
        return findings
    ref = value_match.group("ref")
    if ref not in ALLOWED_SCANNER_IMAGES:
        findings.append(
            Finding(path, line_no, f"{var_name} must use an approved pinned scanner reference")
        )
    return findings


def _validate_alpine_candidate_env_line(path: Path, line_no: int, line: str, var_name: str) -> list[Finding]:
    findings: list[Finding] = []
    if "${{" in line:
        findings.append(
            Finding(path, line_no, f"{var_name} must not use workflow interpolation")
        )
    if re.search(r"\b(secrets|inputs|vars)\.", line):
        findings.append(
            Finding(path, line_no, f"{var_name} must not reference secrets, inputs, or repository variables")
        )
    value_match = re.match(rf"^\s+{var_name}:\s*(?P<ref>\S+)\s*(?:#.*)?$", line)
    if not value_match:
        findings.append(Finding(path, line_no, f"{var_name} must define a static pinned candidate reference"))
        return findings
    ref = value_match.group("ref")
    if ref not in APPROVED_AUDIT_CANDIDATES:
        findings.append(
            Finding(path, line_no, f"{var_name} must use an approved audit candidate reference")
        )
    return findings


def _validate_alpine_trivy_step(path: Path, content: str) -> list[Finding]:
    findings: list[Finding] = []
    block = _extract_step_run_block(content, ALPINE_TRIVY_STEP_NAME)
    if block is None:
        findings.append(Finding(path, 0, "Alpine candidate job must define Generate Alpine candidate Trivy reports step"))
        return findings

    user_runs = re.findall(r'--user "\$\{RUNNER_UID\}:\$\{RUNNER_GID\}"', block)
    if len(user_runs) != 2:
        findings.append(
            Finding(path, 0, f"Alpine Trivy step must run two scanner containers as runner uid/gid, found {len(user_runs)}")
        )
    cache_mounts = re.findall(r'"\$\{ALPINE_TRIVY_CACHE_DIR\}:/trivy-cache:rw"', block)
    if len(cache_mounts) != 2:
        findings.append(
            Finding(path, 0, f"Alpine Trivy step must mount ALPINE_TRIVY_CACHE_DIR twice, found {len(cache_mounts)}")
        )
    if "/var/run/docker.sock" in block or "sudo" in block or "chmod 777" in block:
        findings.append(Finding(path, 0, "Alpine Trivy step must not use docker socket or privilege helpers"))
    return findings


def _extract_alpine_job_step_names(content: str) -> list[str]:
    marker = f"{ALPINE_CANDIDATE_JOB_NAME}:"
    if marker not in content:
        return []
    job_block = content.split(marker, 1)[1]
    step_names: list[str] = []
    for line in job_block.splitlines():
        if re.match(r"^  [a-zA-Z0-9_-]+:\s*$", line):
            break
        match = re.match(r"^      - name: (.+)$", line)
        if match:
            step_names.append(match.group(1))
    return step_names


def _validate_alpine_step_order(path: Path, content: str) -> list[Finding]:
    findings: list[Finding] = []
    steps = _extract_alpine_job_step_names(content)
    if not steps:
        findings.append(Finding(path, 0, "Alpine candidate job must define ordered steps"))
        return findings

    required_order = (
        ALPINE_SBOM_VALIDATE_STEP,
        ALPINE_TRIVY_GENERATE_STEP,
        ALPINE_WHEEL_AMD64_STEP,
        ALPINE_WHEEL_ARM64_STEP,
        ALPINE_WHEEL_VALIDATE_STEP,
        ALPINE_POLICY_STEP,
        ALPINE_ARTIFACT_STEP_NAME,
        ALPINE_CLEANUP_STEP_NAME,
    )
    indices = {name: steps.index(name) for name in required_order if name in steps}
    missing = [name for name in required_order if name not in indices]
    if missing:
        findings.append(Finding(path, 0, f"Alpine candidate job missing required steps: {', '.join(missing)}"))
        return findings

    ordered_pairs = (
        (ALPINE_SBOM_VALIDATE_STEP, ALPINE_TRIVY_GENERATE_STEP),
        (ALPINE_TRIVY_GENERATE_STEP, ALPINE_WHEEL_AMD64_STEP),
        (ALPINE_WHEEL_AMD64_STEP, ALPINE_WHEEL_ARM64_STEP),
        (ALPINE_WHEEL_ARM64_STEP, ALPINE_WHEEL_VALIDATE_STEP),
        (ALPINE_WHEEL_VALIDATE_STEP, ALPINE_POLICY_STEP),
        (ALPINE_POLICY_STEP, ALPINE_ARTIFACT_STEP_NAME),
        (ALPINE_ARTIFACT_STEP_NAME, ALPINE_CLEANUP_STEP_NAME),
    )
    for earlier, later in ordered_pairs:
        if indices[earlier] >= indices[later]:
            findings.append(
                Finding(path, 0, f"Alpine step order invalid: {earlier} must precede {later}")
            )
    return findings


def _validate_alpine_wheel_steps(path: Path, content: str) -> list[Finding]:
    findings: list[Finding] = []
    for step_name in (ALPINE_WHEEL_AMD64_STEP, ALPINE_WHEEL_ARM64_STEP):
        block = _extract_step_run_block(content, step_name)
        if block is None:
            findings.append(Finding(path, 0, f"{step_name} must define a run block"))
            continue
        for token in ("continue-on-error", "|| true", "/var/run/docker.sock", "$HOME", "--env-file"):
            if token in block:
                findings.append(Finding(path, 0, f"{step_name} must not use {token}"))
        if step_name == ALPINE_WHEEL_AMD64_STEP:
            if "audit_alpine_candidate_wheels_amd64.py" not in block:
                findings.append(Finding(path, 0, "amd64 wheel audit must invoke audit_alpine_candidate_wheels_amd64.py"))
            if "alpine_wheel_audit_common.py" not in block:
                findings.append(Finding(path, 0, "amd64 wheel audit must mount alpine_wheel_audit_common.py"))
            if "validate_target_site_packages.py" not in block:
                findings.append(Finding(path, 0, "amd64 wheel audit must mount validate_target_site_packages.py"))
            if "/audit/ro/" not in block:
                findings.append(Finding(path, 0, "amd64 wheel audit must mount scripts under /audit/ro"))
            if '--user "${RUNNER_UID}:${RUNNER_GID}"' not in block:
                findings.append(Finding(path, 0, "amd64 wheel audit must run as runner uid/gid"))
            for phase in (" probe", " download", " install"):
                if phase not in block:
                    findings.append(Finding(path, 0, f"amd64 wheel audit must invoke{phase} phase"))
            if "docker_run_amd64 none" not in block and "--network none" not in block:
                findings.append(Finding(path, 0, "amd64 wheel install phase must disable network"))
            if "staging-amd64/wheelhouse" not in block:
                findings.append(Finding(path, 0, "amd64 wheel audit must use staging-amd64 wheelhouse"))
        if step_name == ALPINE_WHEEL_ARM64_STEP:
            if "audit_alpine_candidate_wheels_arm64.py" not in block:
                findings.append(Finding(path, 0, "arm64 wheel audit must invoke audit_alpine_candidate_wheels_arm64.py"))
            if "if: ${{ !cancelled() }}" not in content.split(f"- name: {ALPINE_WHEEL_ARM64_STEP}", 1)[1].split("- name:", 1)[0]:
                findings.append(Finding(path, 0, "arm64 wheel audit must use if not cancelled"))
    policy_marker = f"- name: {ALPINE_POLICY_STEP}"
    if policy_marker in content:
        policy_section = content.split(policy_marker, 1)[1].split("- name:", 1)[0]
        if "if: ${{ !cancelled() }}" not in policy_section:
            findings.append(Finding(path, 0, "Alpine policy step must use if not cancelled"))
    return findings


def _validate_alpine_cleanup_step(path: Path, content: str) -> list[Finding]:
    findings: list[Finding] = []
    marker = f"- name: {ALPINE_CLEANUP_STEP_NAME}"
    if marker not in content:
        findings.append(Finding(path, 0, "Alpine candidate job must define cleanup step"))
        return findings
    cleanup_section = content.split(marker, 1)[1].split("- name:", 1)[0]
    if "if: always()" not in cleanup_section:
        findings.append(Finding(path, 0, "Alpine cleanup step must use if: always()"))
    block = _extract_step_run_block(content, ALPINE_CLEANUP_STEP_NAME)
    if block is None:
        findings.append(Finding(path, 0, "Alpine cleanup step must define a run block"))
        return findings
    if 'CLEANUP_TARGET="${RUNNER_TEMP}/sellerai-alpine-audit"' not in block:
        findings.append(Finding(path, 0, "Alpine cleanup step must target sellerai-alpine-audit workspace"))
    if 'rm -rf "${CLEANUP_TARGET}"' not in block:
        findings.append(Finding(path, 0, "Alpine cleanup step must remove CLEANUP_TARGET"))
    for token in ("sudo", "chmod 777", "|| true", "docker run"):
        if token in block:
            findings.append(Finding(path, 0, f"Alpine cleanup step must not use {token}"))
    return findings


def _validate_alpine_artifact_upload(path: Path, content: str) -> list[Finding]:
    findings: list[Finding] = []
    marker = f"- name: {ALPINE_ARTIFACT_STEP_NAME}"
    if marker not in content:
        findings.append(Finding(path, 0, "Alpine candidate job must define artifact upload step"))
        return findings
    section = content.split(marker, 1)[1].split("- name:", 1)[0]
    if "if: always()" not in section:
        findings.append(Finding(path, 0, "Alpine artifact upload must use if: always()"))
    if "if-no-files-found: error" not in section:
        findings.append(Finding(path, 0, "Alpine artifact upload must fail when files are missing"))
    forbidden_artifacts = (".tar", ".whl", "trivy-cache", "pip-cache", ".env")
    for forbidden in forbidden_artifacts:
        if forbidden in section:
            findings.append(Finding(path, 0, f"Alpine artifact upload must not include {forbidden}"))
    required_files = (
        "candidate-amd64.cdx.json",
        "candidate-arm64.cdx.json",
        "candidate-amd64.trivy.json",
        "candidate-arm64.trivy.json",
        "candidate-policy-summary.json",
        "wheel-amd64.json",
        "wheel-arm64.json",
    )
    for filename in required_files:
        if filename not in section:
            findings.append(Finding(path, 0, f"Alpine artifact upload must include {filename}"))
    return findings


def _validate_alpine_hardened_trivy_step(path: Path, content: str) -> list[Finding]:
    findings: list[Finding] = []
    block = _extract_step_run_block(content, ALPINE_HARDENED_TRIVY_STEP)
    if block is None:
        findings.append(
            Finding(path, 0, "Alpine hardened job must define Generate hardened Alpine candidate Trivy reports step")
        )
        return findings

    user_runs = re.findall(r'--user "\$\{RUNNER_UID\}:\$\{RUNNER_GID\}"', block)
    if len(user_runs) != 2:
        findings.append(
            Finding(
                path,
                0,
                f"Alpine hardened Trivy step must run two scanner containers as runner uid/gid, found {len(user_runs)}",
            )
        )
    cache_mounts = re.findall(r'"\$\{HARDENED_TRIVY_CACHE_DIR\}:/trivy-cache:rw"', block)
    if len(cache_mounts) != 2:
        findings.append(
            Finding(
                path,
                0,
                f"Alpine hardened Trivy step must mount HARDENED_TRIVY_CACHE_DIR twice, found {len(cache_mounts)}",
            )
        )
    if "/var/run/docker.sock" in block or "sudo" in block or "chmod 777" in block:
        findings.append(Finding(path, 0, "Alpine hardened Trivy step must not use docker socket or privilege helpers"))
    return findings


def _extract_alpine_hardened_job_step_names(content: str) -> list[str]:
    marker = f"{ALPINE_HARDENED_JOB_NAME}:"
    if marker not in content:
        return []
    job_block = content.split(marker, 1)[1]
    step_names: list[str] = []
    for line in job_block.splitlines():
        if re.match(r"^  [a-zA-Z0-9_-]+:\s*$", line):
            break
        match = re.match(r"^      - name: (.+)$", line)
        if match:
            step_names.append(match.group(1))
        uses_match = re.match(r"^      - uses: (.+)$", line)
        if uses_match and not step_names:
            step_names.append(f"uses:{uses_match.group(1)}")
    return step_names


def _validate_alpine_hardened_step_order(path: Path, content: str) -> list[Finding]:
    findings: list[Finding] = []
    if f"{ALPINE_HARDENED_JOB_NAME}:" not in content:
        return findings

    required_steps = (
        ALPINE_HARDENED_AMD64_BUILD_STEP,
        ALPINE_HARDENED_AMD64_SMOKE_STEP,
        ALPINE_HARDENED_ARM64_BUILD_STEP,
        ALPINE_HARDENED_ARM64_VERIFY_STEP,
        ALPINE_HARDENED_SBOM_VALIDATE_STEP,
        ALPINE_HARDENED_TRIVY_STEP,
        ALPINE_HARDENED_POLICY_STEP,
        ALPINE_HARDENED_ARTIFACT_STEP,
        ALPINE_HARDENED_CLEANUP_STEP,
    )
    indices: dict[str, int] = {}
    for step_name in required_steps:
        marker = f"- name: {step_name}"
        if marker not in content:
            findings.append(Finding(path, 0, f"Alpine hardened job missing required step: {step_name}"))
            continue
        indices[step_name] = content.index(marker)

    if findings:
        return findings

    ordered_pairs = (
        (ALPINE_HARDENED_AMD64_BUILD_STEP, ALPINE_HARDENED_AMD64_SMOKE_STEP),
        (ALPINE_HARDENED_AMD64_SMOKE_STEP, ALPINE_HARDENED_ARM64_BUILD_STEP),
        (ALPINE_HARDENED_ARM64_BUILD_STEP, ALPINE_HARDENED_ARM64_VERIFY_STEP),
        (ALPINE_HARDENED_ARM64_VERIFY_STEP, ALPINE_HARDENED_SBOM_VALIDATE_STEP),
        (ALPINE_HARDENED_SBOM_VALIDATE_STEP, ALPINE_HARDENED_TRIVY_STEP),
        (ALPINE_HARDENED_TRIVY_STEP, ALPINE_HARDENED_POLICY_STEP),
        (ALPINE_HARDENED_POLICY_STEP, ALPINE_HARDENED_ARTIFACT_STEP),
        (ALPINE_HARDENED_ARTIFACT_STEP, ALPINE_HARDENED_CLEANUP_STEP),
    )
    for earlier, later in ordered_pairs:
        if indices[earlier] >= indices[later]:
            findings.append(
                Finding(path, 0, f"Alpine hardened step order invalid: {earlier} must precede {later}")
            )
    return findings


def _validate_alpine_hardened_smoke_step(path: Path, content: str) -> list[Finding]:
    findings: list[Finding] = []
    block = _extract_step_run_block(content, ALPINE_HARDENED_AMD64_SMOKE_STEP)
    if block is None:
        findings.append(Finding(path, 0, "Alpine hardened job must define amd64 smoke step"))
        return findings
    required_tokens = (
        "--network none",
        "--read-only",
        "--tmpfs /tmp:rw,noexec,nosuid,nodev",
        "--cap-drop ALL",
        "--security-opt no-new-privileges",
        "validate_alpine_hardened_smoke.py",
        "DATABASE_URL=postgresql://localhost:5432/sellerai_test",
        "backend-alpine-amd64-smoke-manifest.json",
    )
    for token in required_tokens:
        if token not in block:
            findings.append(Finding(path, 0, f"Alpine hardened amd64 smoke step must include {token!r}"))
    for token in ("continue-on-error", "|| true", "/var/run/docker.sock", "--env-file"):
        if token in block:
            findings.append(Finding(path, 0, f"Alpine hardened amd64 smoke step must not use {token}"))
    return findings


def _validate_alpine_hardened_arm64_step(path: Path, content: str) -> list[Finding]:
    findings: list[Finding] = []
    block = _extract_step_run_block(content, ALPINE_HARDENED_ARM64_VERIFY_STEP)
    if block is None:
        findings.append(Finding(path, 0, "Alpine hardened job must define arm64 build-only verification step"))
        return findings
    required_tokens = (
        "build_only",
        "backend-alpine-arm64-verification-manifest.json",
        "validate_backend_runtime_environment.py",
        "validate_backend_alpine_os_packages.py",
        'test "$(id -u)" -eq 1001',
    )
    for token in required_tokens:
        if token not in block:
            findings.append(Finding(path, 0, f"Alpine hardened arm64 verification step must include {token!r}"))
    if "validate_alpine_hardened_smoke.py" in block:
        findings.append(Finding(path, 0, "arm64 verification must not claim runtime smoke"))
    return findings


def _validate_alpine_hardened_build_actions(path: Path, content: str) -> list[Finding]:
    findings: list[Finding] = []
    marker = f"{ALPINE_HARDENED_JOB_NAME}:"
    if marker not in content:
        return findings
    job_block = content.split(marker, 1)[1].split("\n  backend-", 1)[0]
    for line_no_offset, line in enumerate(job_block.splitlines(), start=1):
        uses_match = re.match(r"^      - uses: (\S+)", line)
        if not uses_match:
            continue
        action_ref = uses_match.group(1)
        if action_ref.startswith("actions/"):
            continue
        if action_ref.startswith("docker/setup-"):
            if action_ref not in APPROVED_BUILD_ACTIONS:
                findings.append(
                    Finding(path, line_no_offset, f"unapproved build action reference {action_ref!r}")
                )
            if "@v" in action_ref and "@" in action_ref.split("@", 1)[1][:2]:
                if not re.search(r"@[0-9a-f]{40}\b", action_ref):
                    findings.append(Finding(path, line_no_offset, "build actions must pin full commit SHA"))
        if "docker push" in line:
            findings.append(Finding(path, line_no_offset, "Alpine hardened job must not push images"))
    build_block = _extract_step_run_block(content, ALPINE_HARDENED_AMD64_BUILD_STEP)
    if build_block is None or "Dockerfile.alpine-candidate" not in build_block:
        findings.append(Finding(path, 0, "Alpine hardened job must build from Dockerfile.alpine-candidate"))
    arm64_build = _extract_step_run_block(content, ALPINE_HARDENED_ARM64_BUILD_STEP)
    if arm64_build is None or "--platform linux/arm64" not in arm64_build:
        findings.append(Finding(path, 0, "Alpine hardened job must build arm64 with buildx platform flag"))
    return findings


def _validate_alpine_hardened_cleanup_step(path: Path, content: str) -> list[Finding]:
    findings: list[Finding] = []
    marker = f"- name: {ALPINE_HARDENED_CLEANUP_STEP}"
    if marker not in content:
        findings.append(Finding(path, 0, "Alpine hardened job must define cleanup step"))
        return findings
    cleanup_section = content.split(marker, 1)[1].split("- name:", 1)[0]
    if "if: always()" not in cleanup_section:
        findings.append(Finding(path, 0, "Alpine hardened cleanup step must use if: always()"))
    block = _extract_step_run_block(content, ALPINE_HARDENED_CLEANUP_STEP)
    if block is None:
        findings.append(Finding(path, 0, "Alpine hardened cleanup step must define a run block"))
        return findings
    if 'CLEANUP_TARGET="${RUNNER_TEMP}/sellerai-alpine-hardened"' not in block:
        findings.append(Finding(path, 0, "Alpine hardened cleanup step must target sellerai-alpine-hardened workspace"))
    for token in ("sudo", "chmod 777", "|| true", "docker run"):
        if token in block:
            findings.append(Finding(path, 0, f"Alpine hardened cleanup step must not use {token}"))
    return findings


def _validate_alpine_hardened_artifact_upload(path: Path, content: str) -> list[Finding]:
    findings: list[Finding] = []
    marker = f"- name: {ALPINE_HARDENED_ARTIFACT_STEP}"
    if marker not in content:
        findings.append(Finding(path, 0, "Alpine hardened job must define artifact upload step"))
        return findings
    section = content.split(marker, 1)[1].split("- name:", 1)[0]
    if "if: always()" not in section:
        findings.append(Finding(path, 0, "Alpine hardened artifact upload must use if: always()"))
    if "if-no-files-found: error" not in section:
        findings.append(Finding(path, 0, "Alpine hardened artifact upload must fail when files are missing"))
    forbidden_artifacts = (".tar", ".whl", "trivy-cache", "pip-cache", ".env")
    for forbidden in forbidden_artifacts:
        if forbidden in section:
            findings.append(Finding(path, 0, f"Alpine hardened artifact upload must not include {forbidden}"))
    required_files = (
        "backend-alpine-amd64.cdx.json",
        "backend-alpine-arm64.cdx.json",
        "backend-alpine-amd64.trivy.json",
        "backend-alpine-arm64.trivy.json",
        "backend-alpine-hardened-summary.json",
        "backend-alpine-amd64-smoke-manifest.json",
        "backend-alpine-arm64-verification-manifest.json",
    )
    for filename in required_files:
        if filename not in section:
            findings.append(Finding(path, 0, f"Alpine hardened artifact upload must include {filename}"))
    return findings


def _scan_workflow(path: Path, content: str) -> tuple[list[Finding], list[tuple[Path, int, str]], int, int]:
    findings: list[Finding] = []
    external_refs: list[tuple[Path, int, str]] = []
    scanner_refs = 0
    scanner_identities = 0
    containers_syft_pin: str | None = None
    containers_trivy_pin: str | None = None
    alpine_syft_pin: str | None = None
    alpine_trivy_pin: str | None = None
    hardened_syft_pin: str | None = None
    hardened_trivy_pin: str | None = None
    alpine_candidate_env_count = 0
    hardened_candidate_env_count = 0
    in_services = False
    current_job: str | None = None
    in_scanner_step = False

    for line_no, line in enumerate(content.splitlines(), start=1):
        job_match = re.match(r"^  ([a-zA-Z0-9_-]+):\s*$", line)
        if job_match and not line.startswith("    "):
            current_job = job_match.group(1)
            in_scanner_step = False
            continue

        in_scan_job = current_job in {
            CONTAINERS_JOB_NAME,
            ALPINE_CANDIDATE_JOB_NAME,
            ALPINE_HARDENED_JOB_NAME,
        }

        if in_scan_job and re.match(
            r"^      - name: (Generate CycloneDX SBOMs|Generate Trivy vulnerability reports|"
            r"Generate Alpine candidate CycloneDX SBOMs|Generate Alpine candidate Trivy reports|"
            r"Generate hardened Alpine candidate CycloneDX SBOMs|"
            r"Generate hardened Alpine candidate Trivy reports)\s*$",
            line,
        ):
            in_scanner_step = True
            continue
        if in_scan_job and re.match(r"^      - name:", line):
            in_scanner_step = False

        if in_scan_job and in_scanner_step:
            for pattern, reason in SCANNER_FORBIDDEN_WORKFLOW_PATTERNS:
                if pattern.search(line):
                    findings.append(Finding(path, line_no, reason))
            if SCANNER_FORBIDDEN_CREDENTIAL_ENV.search(line):
                findings.append(
                    Finding(path, line_no, "scanner containers must not receive credential env vars")
                )

        if current_job == CONTAINERS_JOB_NAME:
            if re.match(r"^      SYFT_IMAGE:", line):
                scanner_identities += 1
                match = re.match(r"^      SYFT_IMAGE:\s*(?P<ref>\S+)", line)
                if match:
                    containers_syft_pin = match.group("ref")
                findings.extend(_validate_scanner_env_line(path, line_no, line, "SYFT_IMAGE"))
            elif re.match(r"^          SYFT_IMAGE:", line):
                findings.append(Finding(path, line_no, "step env must not override SYFT_IMAGE"))
            if re.match(r"^      TRIVY_IMAGE:", line):
                scanner_identities += 1
                match = re.match(r"^      TRIVY_IMAGE:\s*(?P<ref>\S+)", line)
                if match:
                    containers_trivy_pin = match.group("ref")
                findings.extend(_validate_scanner_env_line(path, line_no, line, "TRIVY_IMAGE"))
            elif re.match(r"^          TRIVY_IMAGE:", line):
                findings.append(Finding(path, line_no, "step env must not override TRIVY_IMAGE"))

        if current_job == ALPINE_CANDIDATE_JOB_NAME:
            if re.match(r"^      SYFT_IMAGE:", line):
                scanner_identities += 1
                match = re.match(r"^      SYFT_IMAGE:\s*(?P<ref>\S+)", line)
                if match:
                    alpine_syft_pin = match.group("ref")
                findings.extend(_validate_scanner_env_line(path, line_no, line, "SYFT_IMAGE"))
            elif re.match(r"^          SYFT_IMAGE:", line):
                findings.append(Finding(path, line_no, "step env must not override SYFT_IMAGE"))
            if re.match(r"^      TRIVY_IMAGE:", line):
                scanner_identities += 1
                match = re.match(r"^      TRIVY_IMAGE:\s*(?P<ref>\S+)", line)
                if match:
                    alpine_trivy_pin = match.group("ref")
                findings.extend(_validate_scanner_env_line(path, line_no, line, "TRIVY_IMAGE"))
            elif re.match(r"^          TRIVY_IMAGE:", line):
                findings.append(Finding(path, line_no, "step env must not override TRIVY_IMAGE"))
            for var_name in (
                "ALPINE_CANDIDATE_INDEX_REF",
                "ALPINE_CANDIDATE_AMD64_REF",
                "ALPINE_CANDIDATE_ARM64_REF",
            ):
                if re.match(rf"^      {var_name}:", line):
                    alpine_candidate_env_count += 1
                    findings.extend(_validate_alpine_candidate_env_line(path, line_no, line, var_name))
                elif re.match(rf"^          {var_name}:", line):
                    findings.append(Finding(path, line_no, f"step env must not override {var_name}"))
            if "docker push" in line:
                findings.append(Finding(path, line_no, "Alpine candidate job must not push images"))
            if current_job == ALPINE_CANDIDATE_JOB_NAME:
                for candidate_ref in APPROVED_AUDIT_CANDIDATES:
                    if candidate_ref not in line:
                        continue
                    if re.match(r"^\s+ALPINE_CANDIDATE_(INDEX|AMD64|ARM64)_REF:", line):
                        continue
                    if any(
                        token in line
                        for token in (
                            "docker pull",
                            "docker image save",
                            "docker image inspect",
                            "docker run",
                            "${ALPINE_CANDIDATE_",
                        )
                    ):
                        continue
                    findings.append(
                        Finding(
                            path,
                            line_no,
                            "audit candidate digest must be referenced via ALPINE_CANDIDATE_* env vars",
                        )
                    )

        if current_job == ALPINE_HARDENED_JOB_NAME:
            if re.match(r"^      SYFT_IMAGE:", line):
                scanner_identities += 1
                match = re.match(r"^      SYFT_IMAGE:\s*(?P<ref>\S+)", line)
                if match:
                    hardened_syft_pin = match.group("ref")
                findings.extend(_validate_scanner_env_line(path, line_no, line, "SYFT_IMAGE"))
            elif re.match(r"^          SYFT_IMAGE:", line):
                findings.append(Finding(path, line_no, "step env must not override SYFT_IMAGE"))
            if re.match(r"^      TRIVY_IMAGE:", line):
                scanner_identities += 1
                match = re.match(r"^      TRIVY_IMAGE:\s*(?P<ref>\S+)", line)
                if match:
                    hardened_trivy_pin = match.group("ref")
                findings.extend(_validate_scanner_env_line(path, line_no, line, "TRIVY_IMAGE"))
            elif re.match(r"^          TRIVY_IMAGE:", line):
                findings.append(Finding(path, line_no, "step env must not override TRIVY_IMAGE"))
            if re.match(r"^      ALPINE_CANDIDATE_INDEX_REF:", line):
                hardened_candidate_env_count += 1
                findings.extend(
                    _validate_alpine_candidate_env_line(path, line_no, line, "ALPINE_CANDIDATE_INDEX_REF")
                )
            elif re.match(r"^          ALPINE_CANDIDATE_INDEX_REF:", line):
                findings.append(Finding(path, line_no, "step env must not override ALPINE_CANDIDATE_INDEX_REF"))
            if "docker push" in line:
                findings.append(Finding(path, line_no, "Alpine hardened job must not push images"))
            if "secrets." in line or "github.token" in line.lower():
                findings.append(Finding(path, line_no, "Alpine hardened job must not use secrets"))
            for candidate_ref in APPROVED_AUDIT_CANDIDATES:
                if candidate_ref not in line:
                    continue
                if re.match(r"^\s+ALPINE_CANDIDATE_INDEX_REF:", line):
                    continue
                if "Dockerfile.alpine-candidate" in line:
                    continue
                findings.append(
                    Finding(
                        path,
                        line_no,
                        "hardened candidate digest must be referenced via ALPINE_CANDIDATE_INDEX_REF or Dockerfile",
                    )
                )

        if in_scan_job and in_scanner_step and (
            "docker run" in line or '"${SYFT_IMAGE}"' in line or '"${TRIVY_IMAGE}"' in line
        ):
            for match in re.finditer(r"\$\{([A-Z0-9_]+)\}", line):
                var_name = match.group(1)
                if var_name not in ALLOWED_SCANNER_SHELL_VARS:
                    findings.append(
                        Finding(
                            path,
                            line_no,
                            "scanner execution must not use unapproved shell variable substitution",
                        )
                    )
            if '"${SYFT_IMAGE}"' in line:
                scanner_refs += 1
            if '"${TRIVY_IMAGE}"' in line:
                scanner_refs += 1

        for scanner_image in ALLOWED_SCANNER_IMAGES:
            if scanner_image in line and not in_scan_job:
                findings.append(
                    Finding(
                        path,
                        line_no,
                        "scanner image is only allowed in approved scan jobs",
                    )
                )

        for match in re.finditer(r"(?:docker\.io/)?(anchore/syft|aquasec/trivy):[^\s\"']+", line):
            candidate = match.group(0).removeprefix("docker.io/")
            if candidate not in ALLOWED_SCANNER_IMAGES:
                findings.append(
                    Finding(path, line_no, "unapproved scanner image reference in workflow")
                )
            elif in_scan_job and '"${SYFT_IMAGE}"' not in line and '"${TRIVY_IMAGE}"' not in line:
                if not re.match(r"^\s+(SYFT_IMAGE|TRIVY_IMAGE):", line):
                    findings.append(
                        Finding(
                            path,
                            line_no,
                            "scanner image digest must be referenced via SYFT_IMAGE or TRIVY_IMAGE env vars",
                        )
                    )

        for candidate_ref in APPROVED_AUDIT_CANDIDATES:
            if candidate_ref not in line:
                continue
            if current_job in {ALPINE_CANDIDATE_JOB_NAME, ALPINE_HARDENED_JOB_NAME}:
                continue
            findings.append(
                Finding(
                    path,
                    line_no,
                    "approved audit candidate image is only allowed in Alpine audit jobs or candidate Dockerfile",
                )
            )

        if re.match(r"^    services:\s*$", line):
            in_services = True
            continue

        if in_services and re.match(r"^    \S", line) and not re.match(r"^      ", line):
            in_services = False

        if not in_services:
            continue

        image_match = re.match(r"^        image:\s*(?P<ref>\S+)", line)
        if not image_match:
            continue

        ref = image_match.group("ref")
        if "${{" in ref:
            findings.append(
                Finding(path, line_no, "service image digest must be static and not use workflow interpolation")
            )
            continue
        if ref in ALLOWED_SCANNER_IMAGES:
            findings.append(Finding(path, line_no, "scanner image must not be used as a service container"))
            continue
        if ref in APPROVED_AUDIT_CANDIDATES:
            findings.append(Finding(path, line_no, "audit candidate image must not be used as a service container"))
            continue
        findings.extend(_validate_external_image(path, line_no, ref))
        external_refs.append((path, line_no, ref))

    if "containers:" in content:
        if containers_syft_pin is None or containers_trivy_pin is None:
            findings.append(Finding(path, 0, "containers job must define SYFT_IMAGE and TRIVY_IMAGE"))
        if (
            containers_syft_pin is not None
            and containers_trivy_pin is not None
            and containers_syft_pin == containers_trivy_pin
        ):
            findings.append(Finding(path, 0, "containers SYFT_IMAGE and TRIVY_IMAGE must be distinct"))
        findings.extend(_validate_trivy_scan_step(path, content))
        findings.extend(_validate_runtime_smoke_step(path, content))
        findings.extend(_validate_frontend_runtime_smoke_step(path, content))
        findings.extend(_validate_cleanup_step(path, content))

    if f"{ALPINE_CANDIDATE_JOB_NAME}:" in content:
        if alpine_syft_pin is None or alpine_trivy_pin is None:
            findings.append(Finding(path, 0, "Alpine candidate job must define SYFT_IMAGE and TRIVY_IMAGE"))
        if alpine_candidate_env_count != 3:
            findings.append(
                Finding(
                    path,
                    0,
                    f"expected 3 Alpine candidate env identities, found {alpine_candidate_env_count}",
                )
            )
        if "if: github.event_name == 'pull_request'" not in content:
            findings.append(Finding(path, 0, "Alpine candidate job must be pull_request gated"))
        findings.extend(_validate_alpine_trivy_step(path, content))
        findings.extend(_validate_alpine_step_order(path, content))
        findings.extend(_validate_alpine_wheel_steps(path, content))
        findings.extend(_validate_alpine_cleanup_step(path, content))
        findings.extend(_validate_alpine_artifact_upload(path, content))

    if f"{ALPINE_HARDENED_JOB_NAME}:" in content:
        if hardened_syft_pin is None or hardened_trivy_pin is None:
            findings.append(Finding(path, 0, "Alpine hardened job must define SYFT_IMAGE and TRIVY_IMAGE"))
        if hardened_candidate_env_count != 1:
            findings.append(
                Finding(
                    path,
                    0,
                    f"expected 1 Alpine hardened candidate env identity, found {hardened_candidate_env_count}",
                )
            )
        hardened_marker = f"{ALPINE_HARDENED_JOB_NAME}:"
        hardened_block = content.split(hardened_marker, 1)[1].split("\n  backend-", 1)[0]
        if "permissions:" in hardened_block and "contents: write" in hardened_block:
            findings.append(Finding(path, 0, "Alpine hardened job must not expand contents write permission"))
        findings.extend(_validate_alpine_hardened_trivy_step(path, content))
        findings.extend(_validate_alpine_hardened_step_order(path, content))
        findings.extend(_validate_alpine_hardened_smoke_step(path, content))
        findings.extend(_validate_alpine_hardened_arm64_step(path, content))
        findings.extend(_validate_alpine_hardened_build_actions(path, content))
        findings.extend(_validate_alpine_hardened_cleanup_step(path, content))
        findings.extend(_validate_alpine_hardened_artifact_upload(path, content))

    alpine_jobs_present = (
        "containers:" in content
        or f"{ALPINE_CANDIDATE_JOB_NAME}:" in content
        or f"{ALPINE_HARDENED_JOB_NAME}:" in content
    )
    if alpine_jobs_present and scanner_identities != EXPECTED_SCANNER_APPROVED_IDENTITY_COUNT:
        findings.append(
            Finding(
                path,
                0,
                (
                    "expected "
                    f"{EXPECTED_SCANNER_APPROVED_IDENTITY_COUNT} scanner approved identities, "
                    f"found {scanner_identities}"
                ),
            )
        )

    return findings, external_refs, 0, scanner_refs


def _scan_file(path: Path) -> tuple[list[Finding], list[tuple[Path, int, str]], int, int]:
    if not path.is_file():
        return [Finding(path, 0, "scan target is missing")], [], 0, 0

    content = path.read_text(encoding="utf-8")
    name = path.name.lower()

    if name.startswith("dockerfile"):
        findings, refs, internal = _scan_dockerfile(path, content)
        return findings, refs, internal, 0
    if name.startswith("docker-compose") and name.endswith((".yml", ".yaml")):
        findings, refs, internal = _scan_compose(path, content)
        return findings, refs, internal, 0
    if path.suffix in {".yml", ".yaml"} and "workflows" in path.parts:
        return _scan_workflow(path, content)

    return [Finding(path, 0, "unsupported scan target type")], [], 0, 0


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

    scanner_pinned_refs = 0

    for target in SCAN_TARGETS:
        file_findings, file_external_refs, file_internal_refs, file_scanner_refs = _scan_file(target)
        findings.extend(file_findings)
        if target.is_file():
            scanned_files += 1
            external_refs.extend(file_external_refs)
            internal_build_refs += file_internal_refs
            scanner_pinned_refs += file_scanner_refs

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
    if external_count != EXPECTED_RUNTIME_EXTERNAL_PINNED_REF_COUNT:
        findings.append(
            Finding(
                REPO_ROOT,
                0,
                (
                    "expected "
                    f"{EXPECTED_RUNTIME_EXTERNAL_PINNED_REF_COUNT} runtime external pinned references, "
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

    if scanner_pinned_refs != EXPECTED_SCANNER_PINNED_REF_COUNT:
        findings.append(
            Finding(
                REPO_ROOT,
                0,
                (
                    "expected "
                    f"{EXPECTED_SCANNER_PINNED_REF_COUNT} scanner pinned references, "
                    f"found {scanner_pinned_refs}"
                ),
            )
        )

    stats = InventoryStats(
        scanned_files=scanned_files,
        external_pinned_refs=external_count,
        internal_build_refs=internal_build_refs,
        scanner_pinned_refs=scanner_pinned_refs,
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
        f"{stats.external_pinned_refs} runtime external pinned references, "
        f"{stats.scanner_pinned_refs} scanner pinned references, "
        f"{stats.internal_build_refs} internal build references)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
