# Supply Chain Security Policy (S3c)

This document defines SBOM generation, container vulnerability scanning, CI fail-closed rules, artifact retention, and time-bounded exception requirements for SellerAI Copilot production images.

**Policy access date:** 2026-08-18

**Status:** Production `containers` job performs fail-closed SBOM + Trivy + policy evaluation on four scan targets (backend amd64, backend arm64, frontend, nginx). Temporary Alpine candidate audit jobs were retired in S3d5. Do not promote a release until the matching remote `containers` job for that commit reports `blocked=0`.

---

## 1. Scope

| Image | CI tag | SBOM artifact | Vulnerability report |
| --- | --- | --- | --- |
| Backend production amd64 | `sellerai-backend-ci:<commit-sha>` | `backend.cdx.json` | `backend.trivy.json` |
| Backend production arm64 | `sellerai-backend-ci:<commit-sha>-arm64` | `backend-arm64.cdx.json` | `backend-arm64.trivy.json` |
| Frontend production | `sellerai-frontend-ci:<commit-sha>` | `frontend.cdx.json` | `frontend.trivy.json` |
| RC nginx | `sellerai-nginx-ci:<commit-sha>` | `nginx.cdx.json` | `nginx.trivy.json` |

Scanner images are **not** application runtime images. They are pinned supply-chain tools used only in the `containers` CI job.

This policy does **not** claim images are vulnerability-free.

---

## 2. Pinned scanner toolchain

Cross-verified on **2026-08-18** using official GitHub releases and Docker Hub / Registry v2 manifest list digests.

| Tool | Version | Image reference | Multi-arch digest | Official sources |
| --- | --- | --- | --- | --- |
| Syft | v1.51.0 | `anchore/syft:v1.51.0` | `sha256:678bfa565b60f747aac0f8e964fe5588a24445b8d0a480e91f6efd70020dfbb0` | https://github.com/anchore/syft/releases/tag/v1.51.0 (commit `2293641e3bd628a01bb37639318d62c0ebe89b39`); Docker Hub `anchore/syft` |
| Trivy | v0.74.0 | `aquasec/trivy:0.74.0` | `sha256:62b1e65e8869bc4b4c6aa4fa2b21595256c7c2f6018a9d9ad61caf87187c1969` | https://github.com/aquasecurity/trivy/releases/tag/v0.74.0 (commit `e1fd17a0ea4a8cf24bc4b4dd7e2cfbf4bb31b994`); Docker Hub `aquasec/trivy` |

Platforms verified: **linux/amd64**, **linux/arm64**.

CI artifact upload action:

| Action | Tag | Commit SHA | Official source |
| --- | --- | --- | --- |
| `actions/upload-artifact` | v7.0.1 | `043fb46d1a93c77aae656e7c1c64a875d1fc6a0a` | https://github.com/actions/upload-artifact/releases/tag/v7.0.1 |

Scanner env contract in CI:

- Job-level `SYFT_IMAGE` / `TRIVY_IMAGE` only — static `tag@sha256:digest` values
- No `${{ }}` interpolation, secrets, inputs, repository variables, or step-level overrides
- Docker run steps reference only `"${SYFT_IMAGE}"` or `"${TRIVY_IMAGE}"` (eight explicit invocations: four Syft + four Trivy)

---

## 3. Scan architecture (no Docker socket)

1. Build production images on the CI runner (backend amd64, backend arm64 via buildx/QEMU, frontend, nginx).
2. `docker image save` each scanned image to `$RUNNER_TEMP/sellerai-scan/input/*.tar` (never uploaded).
3. Run **Syft** (`SYFT_CHECK_FOR_APP_UPDATE=false`) with read-only input mount; write CycloneDX JSON.
4. Validate SBOM artifacts with `validate_sbom_artifacts.py`.
5. Run **Trivy** with read-only input mount and dedicated `$RUNNER_TEMP/sellerai-scan/trivy-cache`; write JSON (`--exit-code 0`; policy enforced separately). Scanner command failures fail the job.
6. Evaluate policy with `evaluate_vulnerability_report.py` (writes `scan-summary.json` even when blocked). Missing any of the four Trivy reports fails closed. The same CRITICAL / HIGH+fix rules apply to every architecture; findings are not deduplicated across amd64/arm64.
7. Upload approved JSON artifacts only (`if: always()` on upload; upload does not mask job failure).
8. Cleanup deletes only `$RUNNER_TEMP/sellerai-scan` after upload.

**Strictly prohibited in scanner steps:**

- `/var/run/docker.sock`, `--privileged`, host network, workspace/repository root mounts, user home mounts
- `--env-file`, credential env vars, GitHub token / registry auth propagation
- Uploading image tar, build context, `.env`, scanner cache, logs, or source maps
- Mutable `latest` tags, floating `@v*` GitHub Action tags, or unapproved scanner forks

`containers` job timeout: **45 minutes** (build + save + eight scanner runs + DB download + validation + upload).

---

## 4. SBOM contract

Each SBOM file must be CycloneDX JSON with:

- `bomFormat == "CycloneDX"`
- `specVersion` in allowlist: **1.4**, **1.5**, **1.6**
- Bounded recursive structure (metadata, components, properties, evidence, externalReferences, nested components)
- Each component requires `name`; optional `version` / `purl` with correct types
- No credentials, host workspace paths (runner checkout, macOS `/Users/...`, Windows workspace), URL userinfo, or control characters
- OCI/rootfs absolute paths inside scanned images (for example `/usr/...`, `/etc/...`, `/app/...`, container user homes such as `/home/node/...`) are allowed when they do not match host-workspace patterns
- Scanner mount metadata paths (`/input/*.tar`, `/output/*.cdx.json`) are allowed only as fixed scanner-internal references, not expanded runner temp paths

Validator: `backend/scripts/validate_sbom_artifacts.py` (regular files only; symlinks rejected).

SBOMs may reveal sensitive software inventory. Artifacts are **CI-internal only** — not public, not committed to the repository.

---

## 5. Vulnerability blocking policy (default: no exceptions)

Evaluator: `backend/scripts/evaluate_vulnerability_report.py`

| Severity | Block CI? |
| --- | --- |
| **CRITICAL** | **Always** — including when no fixed version exists |
| **HIGH** | **Block only when `FixedVersion` is a non-blank string** |
| **MEDIUM / LOW / UNKNOWN** | Count and report; do not block in S3c initial phase |
| Unsupported / missing severity, malformed schema, scanner error, missing report | **Fail closed** |

Trivy JSON artifact security (pre-upload): no host paths, runner workspace paths, credentials, URL userinfo, or control characters.

**This phase does not fix discovered dependency vulnerabilities.** Do not add `.trivyignore` or silent ignores.

---

## 6. Exception policy (future use only)

**Default: no vulnerability exceptions.**

Future exceptions require: exact CVE/advisory ID, affected image and package, risk analysis, compensating control, owner, `approved_by`, `created_at`, `expires_at` (max **30 days**), linked issue, exact version range.

- Expired exceptions **fail closed**
- Wildcard CVE/package and permanent exceptions forbidden
- Scanner/DB failures **cannot** be excepted
- **CRITICAL** exceptions require separate security approval

S3c ships **zero** approved exceptions.

---

## 7. Trivy vulnerability database (not pinned)

- Scanner **binary/image** is pinned (section 2).
- Trivy **vulnerability DB** is a scan-time snapshot; results may change for the same commit on different dates.
- **Do not pin a stale DB** for false stability.
- DB download / scanner execution failure **blocks** the pipeline.

---

## 8. CI artifacts

| Setting | Value |
| --- | --- |
| Name | `sellerai-supply-chain-<commit-sha>` |
| Retention | **14 days** |
| `if-no-files-found` | **error** |
| Exact paths | `backend.cdx.json`, `backend-arm64.cdx.json`, `frontend.cdx.json`, `nginx.cdx.json`, `nginx-render.cdx.json`, `backend.trivy.json`, `backend-arm64.trivy.json`, `frontend.trivy.json`, `nginx.trivy.json`, `nginx-render.trivy.json`, `scan-summary.json` (11 JSON files) |
| Excluded | Image tar, scanner cache, logs, source, env files, hidden files |

Access: GitHub Actions artifacts with repository-scoped permissions (`contents: read`, `actions: write`). Not published externally.

### 8.1 Historical Alpine candidate audit (completed, S3d5)

S3d5 deleted the temporary PR-only jobs `backend-alpine-candidate-audit` and `backend-alpine-hardened-candidate`. Production images **are Alpine-based** (`backend/Dockerfile.prod` on `python:3.11-alpine3.24`). The designed raw-candidate failure was **not** a production policy failure: production uninstalls `jaraco.context` / `wheel` / `setuptools` from the runtime image.

This subsection is an evidence archive only. Implementation scripts and candidate jobs are gone; GitHub Actions run history and artifacts remain.

| Item | Value |
| --- | --- |
| Raw index digest | `python:3.11-alpine3.24@sha256:6857d2dae63e052057f2db389a7061188ac9a92a3fa8d402bde68f36df6fada1` |
| Retired amd64 child digest | `sha256:cc19a3e1085aba7d26690cf0725d9a3e083cbea0feec34ba8133d40a8ac1d399` |
| Retired arm64 child digest | `sha256:df8376721de6f98515643fca8e7aac56e6a39bc178697a1d8c020ffa050b655e` |
| Wheel audit | **60** wheels, **0** sdist, **0** missing |
| Raw blocker | HIGH+fix on unmodified official image `wheel` and `jaraco.context` |
| Hardened candidate | `Dockerfile.prod`; policy blocked=0 |
| Historical artifact names | `sellerai-alpine-candidate-<commit-sha>`, `sellerai-alpine-hardened-<commit-sha>` (14-day retention; not regenerated) |
| Wheel audit / raw designed-fail Run | [32272275793](https://github.com/biforch/seller-ai-copilot/actions/runs/32272275793) job `96131809593` |
| Hardened candidate verification Run | [32272275793](https://github.com/biforch/seller-ai-copilot/actions/runs/32272275793) job `96131809397` |
| Production Alpine migration Run | [32243262386](https://github.com/biforch/seller-ai-copilot/actions/runs/32243262386) @ `bd36fd3` |
| Last pre-S3d5 production blocked=0 (3 images) | [32272275793](https://github.com/biforch/seller-ai-copilot/actions/runs/32272275793) containers job `96131809502` |

Candidate jobs were archived and deleted in S3d5. Do not reintroduce a permanently failing raw-candidate job to preserve history.

---

## 9. Scanner upgrade procedure

1. Review official Syft/Trivy release notes.
2. Choose exact version tag (never `latest`).
3. Resolve multi-arch digest; cross-verify Hub + Registry.
4. Update workflow env pins, validator allowlist, docs, and tests in one reviewed change.
5. Prove on remote CI before marking S3c **Verified**.

---

## 10. Enforcement references

| Component | Path |
| --- | --- |
| Image pin validator (runtime + scanner) | `backend/scripts/validate_container_image_pins.py` |
| SBOM validator | `backend/scripts/validate_sbom_artifacts.py` |
| Vulnerability policy evaluator | `backend/scripts/evaluate_vulnerability_report.py` |
| CI workflow | `.github/workflows/quality.yml` (`backend`, `frontend`, `containers`) |
| Runtime base image policy | `docs/runtime-image-policy.md` |
