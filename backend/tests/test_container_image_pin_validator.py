"""Tests for container base image pin validator."""

from __future__ import annotations

import io
import os
import subprocess
import sys
import textwrap
from contextlib import redirect_stderr
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from scripts.validate_container_image_pins import (  # noqa: E402
    ALLOWED_SCANNER_IMAGES,
    APPROVED_AUDIT_CANDIDATES,
    EXPECTED_INTERNAL_BUILD_REF_COUNT,
    EXPECTED_RUNTIME_EXTERNAL_PINNED_REF_COUNT,
    EXPECTED_SCAN_FILE_COUNT,
    EXPECTED_SCANNER_APPROVED_IDENTITY_COUNT,
    EXPECTED_SCANNER_PINNED_REF_COUNT,
    INTERNAL_BUILD_IMAGES,
    POLICY_DOC,
    SCAN_TARGETS,
    SUCCESS_MESSAGE,
    _scan_compose,
    _scan_dockerfile,
    _scan_workflow,
    main,
    validate_container_image_pins,
)

SYFT_PIN = next(image for image in ALLOWED_SCANNER_IMAGES if image.startswith("anchore/syft"))
TRIVY_PIN = next(image for image in ALLOWED_SCANNER_IMAGES if image.startswith("aquasec/trivy"))

VALID_NODE = (
    "node:24-alpine@sha256:d32cdf619f63fe0471182d08996dd516c6275bb5fd31ae06e55a570bd9e1ad43"
)
VALID_POSTGRES = (
    "postgres:16-alpine@sha256:cf78e76683b9ca8c5733cbbdce6c9262b45b6767934dd0a95e671f9a0fc20685"
)
VALID_NGINX = (
    "nginx:1.30-alpine@sha256:97d490c12ba55b4946b01546d1c3ed324e8d41ab1c9fcb2a616aa470620e5b46"
)
SECRET_CANARY = "state-canary-secret-do-not-echo"


def test_valid_tag_at_digest_passes_dockerfile_scan() -> None:
    content = f"FROM {VALID_NODE} AS deps\nFROM deps AS builder\n"
    findings, external, _internal = _scan_dockerfile(Path("Dockerfile.prod"), content)
    assert findings == []
    assert len(external) == 1


def test_missing_digest_is_rejected() -> None:
    content = "FROM node:24-alpine\n"
    findings, _, _ = _scan_dockerfile(Path("Dockerfile"), content)
    assert len(findings) == 1
    assert "must pin digest" in findings[0].reason


def test_latest_tag_is_rejected_even_with_digest() -> None:
    content = (
        "FROM node:latest@sha256:d32cdf619f63fe0471182d08996dd516c6275bb5fd31ae06e55a570bd9e1ad43\n"
    )
    findings, _, _ = _scan_dockerfile(Path("Dockerfile"), content)
    assert any("latest" in finding.reason for finding in findings)


@pytest.mark.parametrize(
    "digest_suffix",
    [
        "sha256:ABC",
        "sha256:" + "a" * 63,
        "sha256:" + "g" * 64,
        "sha256:" + "A" * 64,
    ],
)
def test_invalid_digest_format_is_rejected(digest_suffix: str) -> None:
    content = f"FROM node:24-alpine@{digest_suffix}\n"
    findings, _, _ = _scan_dockerfile(Path("Dockerfile"), content)
    assert any("digest must be sha256" in finding.reason for finding in findings)


def test_digest_only_without_tag_is_rejected() -> None:
    content = "FROM sha256:d32cdf619f63fe0471182d08996dd516c6275bb5fd31ae06e55a570bd9e1ad43\n"
    findings, _, _ = _scan_dockerfile(Path("Dockerfile"), content)
    assert any("human-readable tag" in finding.reason for finding in findings)


def test_stage_alias_reference_is_allowed() -> None:
    content = (
        f"FROM {VALID_NODE} AS deps\n"
        "FROM deps AS builder\n"
        f"FROM {VALID_NODE} AS runner\n"
    )
    findings, _, _ = _scan_dockerfile(Path("Dockerfile.prod"), content)
    assert findings == []


def test_unknown_stage_alias_is_rejected() -> None:
    content = f"FROM {VALID_NODE} AS deps\nFROM unknown_alias AS builder\n"
    findings, _, _ = _scan_dockerfile(Path("Dockerfile.prod"), content)
    assert any("unknown stage alias" in finding.reason for finding in findings)


def test_inconsistent_digest_for_same_tag() -> None:
    refs = [
        (Path("a/Dockerfile"), 1, VALID_NODE),
        (
            Path("b/Dockerfile"),
            1,
            "node:24-alpine@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        ),
    ]
    findings: list = []
    from scripts.validate_container_image_pins import _check_consistent_digests

    _check_consistent_digests(findings, refs)
    assert any("inconsistent digest" in finding.reason for finding in findings)


def test_variable_image_reference_is_rejected() -> None:
    content = "FROM ${BASE_IMAGE}\n"
    findings, _, _ = _scan_dockerfile(Path("Dockerfile"), content)
    assert any("variable substitution" in finding.reason for finding in findings)


def test_unapproved_registry_is_rejected() -> None:
    content = (
        "FROM ghcr.io/example/node:24-alpine@sha256:"
        "d32cdf619f63fe0471182d08996dd516c6275bb5fd31ae06e55a570bd9e1ad43\n"
    )
    findings, _, _ = _scan_dockerfile(Path("Dockerfile"), content)
    assert any("registry is not approved" in finding.reason for finding in findings)


def test_compose_image_line_is_scanned() -> None:
    content = f"services:\n  postgres:\n    image: {VALID_POSTGRES}\n"
    findings, external, internal = _scan_compose(Path("docker-compose.rc.yml"), content)
    assert findings == []
    assert len(external) == 1
    assert internal == 0


def test_workflow_service_image_is_scanned() -> None:
    content = (
        "jobs:\n"
        "  backend:\n"
        "    services:\n"
        "      postgres:\n"
        f"        image: {VALID_POSTGRES}\n"
    )
    findings, external, _, _ = _scan_workflow(Path(".github/workflows/quality.yml"), content)
    assert findings == []
    assert len(external) == 1


def test_locally_built_image_without_build_is_rejected() -> None:
    content = textwrap.dedent(
        """
        services:
          backend:
            image: sellerai-backend-prod:rc
        """
    ).strip()
    findings, _, _ = _scan_compose(Path("docker-compose.rc.yml"), content)
    assert any("without build configuration" in finding.reason for finding in findings)


def test_locally_built_image_not_on_allowlist_is_rejected() -> None:
    content = textwrap.dedent(
        """
        services:
          backend:
            build:
              context: ./backend
            image: sellerai-backend-dev:rc
        """
    ).strip()
    findings, _, _ = _scan_compose(Path("docker-compose.rc.yml"), content)
    assert any("not on the internal allowlist" in finding.reason for finding in findings)


def test_external_image_with_build_must_remain_pinned() -> None:
    content = textwrap.dedent(
        """
        services:
          proxy:
            build:
              context: ./nginx
            image: nginx:1.30-alpine
        """
    ).strip()
    findings, _, _ = _scan_compose(Path("docker-compose.rc.yml"), content)
    assert any(
        "external image must remain digest-pinned" in finding.reason for finding in findings
    )


def test_internal_tag_with_registry_host_is_rejected() -> None:
    content = textwrap.dedent(
        """
        services:
          backend:
            build:
              context: ./backend
            image: docker.io/sellerai-backend-prod:rc
        """
    ).strip()
    findings, _, _ = _scan_compose(Path("docker-compose.rc.yml"), content)
    assert any("internal build image must not include registry hostname" in f.reason for f in findings)


def test_parser_counts_multistage_dockerfile_references() -> None:
    content = textwrap.dedent(
        f"""
        # builder
        FROM {VALID_NODE} AS deps
        FROM deps AS builder
        FROM {VALID_NODE} AS runner
        """
    ).strip() + "\n"
    findings, external, _ = _scan_dockerfile(Path("Dockerfile.prod"), content)
    assert findings == []
    assert len(external) == 2


def test_repository_real_configuration_passes() -> None:
    findings, stats = validate_container_image_pins()
    assert findings == [], findings
    assert stats.scanned_files == EXPECTED_SCAN_FILE_COUNT
    assert stats.external_pinned_refs == EXPECTED_RUNTIME_EXTERNAL_PINNED_REF_COUNT
    assert stats.internal_build_refs == EXPECTED_INTERNAL_BUILD_REF_COUNT
    assert stats.scanner_pinned_refs == EXPECTED_SCANNER_PINNED_REF_COUNT


def test_policy_document_digests_match_repository_configuration() -> None:
    findings, stats = validate_container_image_pins()
    assert stats.external_pinned_refs == EXPECTED_RUNTIME_EXTERNAL_PINNED_REF_COUNT
    assert not any("policy digest" in finding.reason for finding in findings)
    assert POLICY_DOC.is_file()


def test_validator_failure_does_not_echo_secret_canary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CANARY_SECRET", SECRET_CANARY)
    monkeypatch.setenv("POSTGRES_PASSWORD", SECRET_CANARY)

    bad_dockerfile = REPO_ROOT / "backend" / "Dockerfile"
    original = bad_dockerfile.read_text(encoding="utf-8")
    bad_dockerfile.write_text("FROM node:24-alpine\n", encoding="utf-8")
    try:
        stderr_buffer = io.StringIO()
        with redirect_stderr(stderr_buffer):
            exit_code = main()
        output = stderr_buffer.getvalue()
        assert exit_code == 1
        assert SECRET_CANARY not in output
        assert "POSTGRES_PASSWORD" not in output
    finally:
        bad_dockerfile.write_text(original, encoding="utf-8")


def test_scan_targets_do_not_include_unrelated_directories() -> None:
    for target in SCAN_TARGETS:
        rel = target.relative_to(REPO_ROOT)
        assert "node_modules" not in rel.parts
        assert ".git" not in rel.parts
        assert rel.name not in {"a3-amazon-account-design-review.md", "a4-product-sync-design-review.md"}


def test_missing_expected_scan_file_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    missing = REPO_ROOT / "backend" / "Dockerfile"
    backup = missing.read_text(encoding="utf-8")
    missing.unlink()
    monkeypatch.setattr(
        "scripts.validate_container_image_pins.SCAN_TARGETS",
        tuple(SCAN_TARGETS),
    )
    try:
        findings, stats = validate_container_image_pins()
        assert any("scan target is missing" in finding.reason for finding in findings)
        assert stats.scanned_files < EXPECTED_SCAN_FILE_COUNT
    finally:
        missing.write_text(backup, encoding="utf-8")


def test_reference_count_drop_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "scripts.validate_container_image_pins.EXPECTED_RUNTIME_EXTERNAL_PINNED_REF_COUNT",
        EXPECTED_RUNTIME_EXTERNAL_PINNED_REF_COUNT + 1,
    )
    findings, _stats = validate_container_image_pins()
    assert any("external pinned references" in finding.reason for finding in findings)


def test_internal_allowlist_is_explicit() -> None:
    assert INTERNAL_BUILD_IMAGES == {
        "sellerai-backend-prod:rc",
        "sellerai-frontend-prod:rc",
        "sellerai-nginx-prod:rc",
    }


def test_validator_script_runs_from_repo_root() -> None:
    result = subprocess.run(
        [sys.executable, str(BACKEND_ROOT / "scripts" / "validate_container_image_pins.py")],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={key: value for key, value in os.environ.items() if key != "CANARY_SECRET"},
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().startswith(SUCCESS_MESSAGE)
    assert "15 runtime external pinned references" not in result.stdout
    assert "17 runtime external pinned references" in result.stdout
    assert "14 scanner pinned references" in result.stdout


def test_scanner_allowlist_is_explicit() -> None:
    assert len(ALLOWED_SCANNER_IMAGES) == 2
    assert any("anchore/syft:v1.51.0@" in image for image in ALLOWED_SCANNER_IMAGES)
    assert any("aquasec/trivy:0.74.0@" in image for image in ALLOWED_SCANNER_IMAGES)


def _containers_workflow(*run_lines: str) -> str:
    run_body = "\n".join(f"          {line}" for line in run_lines)
    return textwrap.dedent(
        f"""
        jobs:
          containers:
            env:
              SYFT_IMAGE: {SYFT_PIN}
              TRIVY_IMAGE: {TRIVY_PIN}
            steps:
              - name: Generate CycloneDX SBOMs
                run: |
{run_body}
        """
    ).strip()


def test_scanner_env_must_not_use_workflow_interpolation() -> None:
    content = textwrap.dedent(
        f"""
        jobs:
          containers:
            env:
              SYFT_IMAGE: ${{{{ inputs.syft_image }}}}
              TRIVY_IMAGE: {TRIVY_PIN}
            steps:
              - name: Generate CycloneDX SBOMs
                run: |
                  docker run --rm "${{SYFT_IMAGE}}"
                  docker run --rm "${{SYFT_IMAGE}}"
                  docker run --rm "${{SYFT_IMAGE}}"
                  docker run --rm "${{TRIVY_IMAGE}}"
                  docker run --rm "${{TRIVY_IMAGE}}"
                  docker run --rm "${{TRIVY_IMAGE}}"
        """
    ).strip()
    findings, _, _, _ = _scan_workflow(Path(".github/workflows/quality.yml"), content)
    assert any("must not use workflow interpolation" in finding.reason for finding in findings)


def test_scanner_env_must_not_use_secrets() -> None:
    content = textwrap.dedent(
        f"""
        jobs:
          containers:
            env:
              SYFT_IMAGE: ${{{{ secrets.SYFT_IMAGE }}}}
              TRIVY_IMAGE: {TRIVY_PIN}
        """
    ).strip()
    findings, _, _, _ = _scan_workflow(Path(".github/workflows/quality.yml"), content)
    assert any("must not reference secrets" in finding.reason for finding in findings)


def test_scanner_step_env_override_is_rejected() -> None:
    content = textwrap.dedent(
        f"""
        jobs:
          containers:
            env:
              SYFT_IMAGE: {SYFT_PIN}
              TRIVY_IMAGE: {TRIVY_PIN}
            steps:
              - name: Generate CycloneDX SBOMs
                env:
                  SYFT_IMAGE: {SYFT_PIN}
                run: |
                  docker run --rm "${{SYFT_IMAGE}}"
        """
    ).strip()
    findings, _, _, _ = _scan_workflow(Path(".github/workflows/quality.yml"), content)
    assert any("step env must not override SYFT_IMAGE" in finding.reason for finding in findings)


def test_scanner_docker_run_rejects_arbitrary_variable() -> None:
    content = _containers_workflow('docker run --rm "${OTHER_IMAGE}"')
    findings, _, _, _ = _scan_workflow(Path(".github/workflows/quality.yml"), content)
    assert any("unapproved shell variable substitution" in finding.reason for finding in findings)


def test_scanner_same_tag_different_digest_is_rejected() -> None:
    wrong_digest = SYFT_PIN.replace(
        "678bfa565b60f747aac0f8e964fe5588a24445b8d0a480e91f6efd70020dfbb0",
        "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    )
    content = textwrap.dedent(
        f"""
        jobs:
          containers:
            env:
              SYFT_IMAGE: {wrong_digest}
              TRIVY_IMAGE: {TRIVY_PIN}
        """
    ).strip()
    findings, _, _, _ = _scan_workflow(Path(".github/workflows/quality.yml"), content)
    assert any("approved pinned scanner reference" in finding.reason for finding in findings)


def test_scanner_wrong_tag_with_valid_digest_pattern_is_rejected() -> None:
    wrong_tag = "anchore/syft:v9.9.9@sha256:678bfa565b60f747aac0f8e964fe5588a24445b8d0a480e91f6efd70020dfbb0"
    content = textwrap.dedent(
        f"""
        jobs:
          containers:
            env:
              SYFT_IMAGE: {wrong_tag}
              TRIVY_IMAGE: {TRIVY_PIN}
        """
    ).strip()
    findings, _, _, _ = _scan_workflow(Path(".github/workflows/quality.yml"), content)
    assert any("approved pinned scanner reference" in finding.reason for finding in findings)


def test_runtime_image_must_not_use_scanner_allowlist() -> None:
    content = f"FROM {SYFT_PIN}\n"
    findings, _, _ = _scan_dockerfile(Path("Dockerfile.prod"), content)
    assert any("must not be used as a runtime base image" in finding.reason for finding in findings)


def test_scanner_container_forbidden_mounts_are_rejected() -> None:
    content = _containers_workflow('docker run --rm -v /var/run/docker.sock:/var/run/docker.sock "${SYFT_IMAGE}"')
    findings, _, _, _ = _scan_workflow(Path(".github/workflows/quality.yml"), content)
    assert any("Docker socket" in finding.reason for finding in findings)


def test_scanner_approved_identity_count() -> None:
    assert EXPECTED_SCANNER_APPROVED_IDENTITY_COUNT == 6
    assert len(ALLOWED_SCANNER_IMAGES) == 2


def test_repository_scanner_identity_count() -> None:
    findings, stats = validate_container_image_pins()
    assert findings == []
    assert stats.scanner_pinned_refs == EXPECTED_SCANNER_PINNED_REF_COUNT


def test_trivy_step_requires_runner_uid_gid_and_cache_dir() -> None:
    content = Path(REPO_ROOT / ".github/workflows/quality.yml").read_text(encoding="utf-8")
    findings, _, _, _ = _scan_workflow(Path(".github/workflows/quality.yml"), content)
    assert findings == []


def _minimal_trivy_step(*extra_lines: str) -> str:
    runs = [
        'docker run --rm --user "${RUNNER_UID}:${RUNNER_GID}" '
        '-v "${SCAN_INPUT}:/input:ro" -v "${SCAN_OUTPUT}:/output:rw" '
        '-v "${TRIVY_CACHE_DIR}:/trivy-cache:rw" "${TRIVY_IMAGE}" '
        "image --cache-dir /trivy-cache --input /input/backend.tar",
        'docker run --rm --user "${RUNNER_UID}:${RUNNER_GID}" '
        '-v "${SCAN_INPUT}:/input:ro" -v "${SCAN_OUTPUT}:/output:rw" '
        '-v "${TRIVY_CACHE_DIR}:/trivy-cache:rw" "${TRIVY_IMAGE}" '
        "image --cache-dir /trivy-cache --input /input/frontend.tar",
        'docker run --rm --user "${RUNNER_UID}:${RUNNER_GID}" '
        '-v "${SCAN_INPUT}:/input:ro" -v "${SCAN_OUTPUT}:/output:rw" '
        '-v "${TRIVY_CACHE_DIR}:/trivy-cache:rw" "${TRIVY_IMAGE}" '
        "image --cache-dir /trivy-cache --input /input/nginx.tar",
    ]
    if extra_lines:
        runs = list(extra_lines)
    body = "\n".join(
        [
            "          set -euo pipefail",
            '          RUNNER_UID="$(id -u)"',
            '          RUNNER_GID="$(id -g)"',
            '          if ! [[ "${RUNNER_UID}" =~ ^[0-9]+$ && "${RUNNER_GID}" =~ ^[0-9]+$ ]]; then',
            "            exit 1",
            "          fi",
            "          echo scanner-user-validated",
            '          SCAN_INPUT="${RUNNER_TEMP}/sellerai-scan/input"',
            '          SCAN_OUTPUT="${RUNNER_TEMP}/sellerai-scan/output"',
            '          TRIVY_CACHE_DIR="${RUNNER_TEMP}/sellerai-scan/trivy-cache"',
            *[f"          {line}" for line in runs],
        ]
    )
    return textwrap.dedent(
        f"""
        jobs:
          containers:
            env:
              SYFT_IMAGE: {SYFT_PIN}
              TRIVY_IMAGE: {TRIVY_PIN}
            steps:
              - name: Generate Trivy vulnerability reports
                run: |
{body}
        """
    ).strip()


def test_trivy_step_rejects_root_cache_mount() -> None:
    content = _minimal_trivy_step(
        'docker run --rm -v "${TRIVY_CACHE_DIR}:/root/.cache/trivy:rw" "${TRIVY_IMAGE}" image --cache-dir /trivy-cache',
        'docker run --rm --user "${RUNNER_UID}:${RUNNER_GID}" -v "${SCAN_INPUT}:/input:ro" -v "${SCAN_OUTPUT}:/output:rw" -v "${TRIVY_CACHE_DIR}:/trivy-cache:rw" "${TRIVY_IMAGE}" image --cache-dir /trivy-cache',
        'docker run --rm --user "${RUNNER_UID}:${RUNNER_GID}" -v "${SCAN_INPUT}:/input:ro" -v "${SCAN_OUTPUT}:/output:rw" -v "${TRIVY_CACHE_DIR}:/trivy-cache:rw" "${TRIVY_IMAGE}" image --cache-dir /trivy-cache',
    )
    findings, _, _, _ = _scan_workflow(Path(".github/workflows/quality.yml"), content)
    assert any("root-owned default cache path" in finding.reason for finding in findings)


def test_cleanup_step_requires_fail_closed_target() -> None:
    content = _minimal_trivy_step()
    content += textwrap.dedent(
        """
              - name: Cleanup supply-chain scan workspace
                if: always()
                run: |
                  set -euo pipefail
                  rm -rf "${RUNNER_TEMP}/sellerai-scan"
        """
    )
    findings, _, _, _ = _scan_workflow(Path(".github/workflows/quality.yml"), content)
    assert any("fail closed when RUNNER_TEMP is unset" in finding.reason for finding in findings)


def test_audit_candidate_in_dockerfile_is_rejected() -> None:
    candidate = next(iter(APPROVED_AUDIT_CANDIDATES))
    content = f"FROM {candidate}\n"
    findings, _, _ = _scan_dockerfile(Path("Dockerfile.prod"), content)
    assert any("audit candidate" in finding.reason for finding in findings)


def test_audit_candidate_in_compose_is_rejected() -> None:
    candidate = next(iter(APPROVED_AUDIT_CANDIDATES))
    content = f"services:\n  backend:\n    image: {candidate}\n"
    findings, _, _ = _scan_compose(Path("docker-compose.rc.yml"), content)
    assert any("audit candidate" in finding.reason for finding in findings)


def test_audit_candidate_floating_tag_is_rejected() -> None:
    content = textwrap.dedent(
        """
        jobs:
          backend-alpine-candidate-audit:
            env:
              ALPINE_CANDIDATE_AMD64_REF: python:3.11-alpine3.24
        """
    ).strip()
    findings, _, _, _ = _scan_workflow(Path(".github/workflows/quality.yml"), content)
    assert any("approved audit candidate reference" in finding.reason for finding in findings)


def test_valid_nginx_digest_example_matches_policy() -> None:
    policy = POLICY_DOC.read_text(encoding="utf-8")
    assert "nginx:1.30-alpine" in policy
    assert VALID_NGINX.split("@", 1)[1] in policy
