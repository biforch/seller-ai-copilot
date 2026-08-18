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
EXPECTED_RUNTIME_EXTERNAL_PINNED_REF_COUNT = 13
EXPECTED_INTERNAL_BUILD_REF_COUNT = 4
EXPECTED_SCANNER_PINNED_REF_COUNT = 6
EXPECTED_SCANNER_APPROVED_IDENTITY_COUNT = 2

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
    }
)

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
CLEANUP_STEP_NAME = "Cleanup supply-chain scan workspace"
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


def _scan_workflow(path: Path, content: str) -> tuple[list[Finding], list[tuple[Path, int, str]], int, int]:
    findings: list[Finding] = []
    external_refs: list[tuple[Path, int, str]] = []
    scanner_refs = 0
    scanner_identities = 0
    syft_env_pin: str | None = None
    trivy_env_pin: str | None = None
    in_services = False
    in_containers_job = False
    in_scanner_step = False

    for line_no, line in enumerate(content.splitlines(), start=1):
        if re.match(r"^  containers:\s*$", line):
            in_containers_job = True
            continue
        if in_containers_job and re.match(r"^  [a-zA-Z].+:\s*$", line) and not line.startswith("    "):
            in_containers_job = False
            in_scanner_step = False

        if in_containers_job and re.match(
            r"^      - name: (Generate CycloneDX SBOMs|Generate Trivy vulnerability reports)\s*$",
            line,
        ):
            in_scanner_step = True
            continue
        if in_containers_job and re.match(r"^      - name:", line):
            in_scanner_step = False

        if in_containers_job and in_scanner_step:
            for pattern, reason in SCANNER_FORBIDDEN_WORKFLOW_PATTERNS:
                if pattern.search(line):
                    findings.append(Finding(path, line_no, reason))
            if SCANNER_FORBIDDEN_CREDENTIAL_ENV.search(line):
                findings.append(
                    Finding(path, line_no, "scanner containers must not receive credential env vars")
                )

        if in_containers_job:
            if re.match(r"^      SYFT_IMAGE:", line):
                scanner_identities += 1
                syft_env_match = re.match(r"^      SYFT_IMAGE:\s*(?P<ref>\S+)", line)
                if syft_env_match:
                    syft_env_pin = syft_env_match.group("ref")
                findings.extend(_validate_scanner_env_line(path, line_no, line, "SYFT_IMAGE"))
            elif re.match(r"^          SYFT_IMAGE:", line):
                findings.append(Finding(path, line_no, "step env must not override SYFT_IMAGE"))

            if re.match(r"^      TRIVY_IMAGE:", line):
                scanner_identities += 1
                trivy_env_match = re.match(r"^      TRIVY_IMAGE:\s*(?P<ref>\S+)", line)
                if trivy_env_match:
                    trivy_env_pin = trivy_env_match.group("ref")
                findings.extend(_validate_scanner_env_line(path, line_no, line, "TRIVY_IMAGE"))
            elif re.match(r"^          TRIVY_IMAGE:", line):
                findings.append(Finding(path, line_no, "step env must not override TRIVY_IMAGE"))

            if in_scanner_step and (
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

            if in_scanner_step and ('"${SYFT_IMAGE}"' in line or '"${TRIVY_IMAGE}"' in line):
                if '"${SYFT_IMAGE}"' in line:
                    scanner_refs += 1
                if '"${TRIVY_IMAGE}"' in line:
                    scanner_refs += 1

        for scanner_image in ALLOWED_SCANNER_IMAGES:
            if scanner_image in line and not in_containers_job:
                findings.append(
                    Finding(
                        path,
                        line_no,
                        "scanner image is only allowed in the containers job scan steps",
                    )
                )

        for match in re.finditer(r"(?:docker\.io/)?(anchore/syft|aquasec/trivy):[^\s\"']+", line):
            candidate = match.group(0).removeprefix("docker.io/")
            if candidate not in ALLOWED_SCANNER_IMAGES:
                findings.append(
                    Finding(path, line_no, "unapproved scanner image reference in workflow")
                )
            elif in_containers_job and '"${SYFT_IMAGE}"' not in line and '"${TRIVY_IMAGE}"' not in line:
                if not re.match(r"^\s+(SYFT_IMAGE|TRIVY_IMAGE):", line):
                    findings.append(
                        Finding(
                            path,
                            line_no,
                            "scanner image digest must be referenced via SYFT_IMAGE or TRIVY_IMAGE env vars",
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
        findings.extend(_validate_external_image(path, line_no, ref))
        external_refs.append((path, line_no, ref))

    if "containers:" in content:
        if syft_env_pin is None:
            findings.append(Finding(path, 0, "containers job must define SYFT_IMAGE with a pinned scanner reference"))
        if trivy_env_pin is None:
            findings.append(Finding(path, 0, "containers job must define TRIVY_IMAGE with a pinned scanner reference"))
        if syft_env_pin is not None and trivy_env_pin is not None and syft_env_pin == trivy_env_pin:
            findings.append(Finding(path, 0, "SYFT_IMAGE and TRIVY_IMAGE must reference distinct scanner identities"))
        if scanner_identities != EXPECTED_SCANNER_APPROVED_IDENTITY_COUNT:
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
        findings.extend(_validate_trivy_scan_step(path, content))
        findings.extend(_validate_runtime_smoke_step(path, content))
        findings.extend(_validate_frontend_runtime_smoke_step(path, content))
        findings.extend(_validate_cleanup_step(path, content))

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
