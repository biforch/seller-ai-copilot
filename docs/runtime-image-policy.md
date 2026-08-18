# Runtime and Base Image Policy

This document records the audited container base images for SellerAI Copilot release, CI, RC, and development paths. It covers **base-image identity pinning** only. Pinning a digest fixes the upstream base image manifest; it does **not** make the final built image bit-for-bit reproducible because Dockerfiles still run mutable steps such as `apt-get update/install`, unpinned pip installs, and npm dependency resolution at build time.

Vulnerability scanning, SBOM generation, and supply-chain enforcement are documented in **`docs/supply-chain-security-policy.md`** (S3c). This file covers **application runtime base-image identity pinning** only.

**Policy access date:** 2026-08-18
**Digest resolution date:** 2026-08-18

---

## 1. Image inventory

Expected external pinned references: **12** (validated by `validate_container_image_pins.py`).

| File | Line | Repository | Tag | Environment | Architectures required |
| --- | --- | --- | --- | --- | --- |
| `backend/Dockerfile.prod` | 2 | `python` | `3.11-slim-trixie` | RC / production | linux/amd64; linux/arm64 |
| `backend/Dockerfile` | 1 | `python` | `3.11-slim-trixie` | development | linux/amd64; linux/arm64 |
| `frontend/Dockerfile.prod` | 2, 11, 26 | `node` | `24-alpine` | RC / production | linux/amd64; linux/arm64 |
| `frontend/Dockerfile` | 1 | `node` | `24-alpine` | development | linux/amd64; linux/arm64 |
| `nginx/Dockerfile.rc` | 1 | `nginx` | `1.30-alpine` | RC / production | linux/amd64; linux/arm64 |
| `docker-compose.rc.yml` | 7 | `postgres` | `16-alpine` | RC | linux/amd64; linux/arm64 |
| `docker-compose.yml` | 3 | `postgres` | `16-alpine` | development | linux/amd64; linux/arm64 |
| `docker-compose.yml` | 21 | `redis` | `7-alpine` | development only | linux/amd64; linux/arm64 |
| `docker-compose.yml` | 87 | `nginx` | `1.30-alpine` | development | linux/amd64; linux/arm64 |
| `.github/workflows/quality.yml` | 21 | `postgres` | `16-alpine` | CI service | linux/amd64 |

**Not pinned (by design):** RC compose locally built application images (`sellerai-backend-prod:rc`, `sellerai-frontend-prod:rc`, `sellerai-nginx-prod:rc`) — **4 internal build references** on the validator allowlist.

**Redis retention (dev only):** Redis remains in `docker-compose.yml` because the backend references `REDIS_URL` and the dev stack models the intended cache/queue sidecar even though production business paths do not depend on Redis today. It is pinned for dev parity; no production lifecycle commitment is made for Redis in S3b.

---

## 2. Lifecycle sources, exact dates, and decisions

Access date for all checks below: **2026-08-18**.

### Node.js

| Item | Value |
| --- | --- |
| Node 20 (Iron) EOL | **2026-04-30** |
| Node 24 (Krypton) initial release | **2025-05-06** |
| Node 24 Active LTS start | **2025-10-28** |
| Node 24 Maintenance LTS start | **2026-10-20** |
| Node 24 EOL | **2028-04-30** |
| Official source | https://github.com/nodejs/release/blob/main/README.md |
| Also | https://nodejs.org/en/about/previous-releases |
| Decision | **Upgrade** all frontend runtime references from Node 20 to **Node 24** |
| Next mandatory review | **2026-10-20** (Node 24 enters Maintenance LTS) or earlier if Node 24 status changes |

Repository runtime contract: `frontend/.nvmrc` = `24.19.0`, `package.json` `engines.node` = `>=24.19.0 <25`, `engines.npm` = `>=11.17.0 <12`, `packageManager` = `npm@11.17.0`, lockfile root mirrors `engines`, `.npmrc` `engine-strict=true`, CI `node-version: "24.19.0"`. The explicit toolchain validator pins **exact** Node **v24.19.0** and npm **11.17.0** for reproducible gates; `engines` expresses compatible ranges only.

### npm optional dependency reifier (R1a)

| Item | Value |
| --- | --- |
| Issue class | `NPM_TOOLCHAIN_VERSION_MISMATCH` (not lockfile graph defect) |
| npm CLI bug | npm **11.6.0–11.12.1** incorrectly reifies inert optional shared deps such as `@emnapi/runtime` |
| Fix | npm **[PR #9221](https://github.com/npm/cli/pull/9221)** in **11.13.0+**; bundled npm in pinned Node **24.19.0** image is **11.17.0** |
| Lockfile | Inert optional `@emnapi/runtime` / `@img/sharp-wasm32` entries remain **legal** and must not be deleted |
| Prohibited workarounds | direct `@emnapi/runtime` dependency, extraneous allowlists, lock entry deletion, `omit=optional`, npm prune/dedupe for masking |

### Python

| Item | Value |
| --- | --- |
| Python 3.11 status (2026-08-18) | security |
| Python 3.11 security support ends | **2027-10** (official schedule granularity: month) |
| Official source | https://devguide.python.org/versions/ |
| Also | https://peps.python.org/pep-0664/ |
| Decision | **Retain Python 3.11-slim-trixie** (explicit Debian trixie suite) |
| Next mandatory review | **2027-07-01** (three months before scheduled security end) |

### PostgreSQL

| Item | Value |
| --- | --- |
| PostgreSQL 16 final release (support end) | **2028-11-09** |
| Current minor (2026-08-13 advisory page) | 16.15 |
| Official source | https://www.postgresql.org/support/versioning/ |
| Decision | **Retain PostgreSQL 16-alpine** |
| Next mandatory review | **2028-08-01** (three months before final release) |

### nginx

| Item | Value |
| --- | --- |
| Current stable branch (2026-08-18) | **1.30.x** |
| nginx 1.30.0 stable release | **2026-04-14** |
| Latest stable point release referenced | **1.30.4** (**2026-07-15**) |
| Legacy stable branch | 1.28.x (last point release **1.28.3** on **2026-03-24**) |
| Current mainline branch | 1.31.x (not used for RC/prod base images) |
| Official sources | https://nginx.org/en/CHANGES-1.30 , https://nginx.org/news.html , https://nginx.org/en/download.html |
| Docker Official Image tag | `nginx:1.30-alpine` — https://hub.docker.com/_/nginx |
| Decision | **Upgrade** from interim `1.28-alpine` selection to **`nginx:1.30-alpine`** (current stable) |
| Next mandatory review | **2026-10-01** or when nginx.org publishes a new stable branch |

### Redis (dev only)

| Item | Value |
| --- | --- |
| Tag | `redis:7-alpine` |
| Official image | https://hub.docker.com/_/redis |
| Decision | **Retain and pin** for dev compose only |
| Production lifecycle commitment | **None** — dev-only sidecar |
| Next mandatory review | When Redis is added to RC/production paths, or **2027-01-01** dev stack audit |

---

## 3. Pinned base images

All digests below are **OCI image index / Docker manifest list** digests (multi-arch), not single-platform child manifests, config digests, or layer digests.

**Digest resolution date:** 2026-08-18 (re-verified for S3d4b)

**Python 3.11-slim-trixie evidence (2026-08-18):**

| Field | Value |
| --- | --- |
| Tag | `python:3.11-slim-trixie` |
| Multi-arch index digest | `sha256:9c900dea9e8fb7e16277c179b555cc72d29a352dbc33cff48ad5a0412fd5bfc7` |
| Media type | `application/vnd.oci.image.index.v1+json` |
| Tag last pushed | 2026-08-16T23:07:07Z |
| official-images GitCommit | `fe89472bda6128fef7e964d1f1991534e32dcfb7` |
| Python patch | 3.11.16 |
| Debian suite | trixie (from `debian:trixie-slim`) |
| linux/amd64 child digest | `sha256:ff05d1a05204fb9f7444c435db8e8ec104e587a413280dc9ffc27a4797554182` |
| linux/arm64 child digest | `sha256:c3030eb5af86633f87e538de534dd455ca0cf2b4eceee87069b713f33d2d03f6` |
| Hub vs Registry | Registry v2 HEAD unavailable from audit host (connection reset); Hub tag API digest matches prior dual-source pin |

**Backend OS security pins (DSA-6442 / CVE-2026-53615):** production `backend/Dockerfile.prod` pins util-linux source `2.41.5-0+deb13u1` binary versions from `deb.debian.org` trixie-security Packages indexes (amd64/arm64 identical). Validated at build and CI by `validate_backend_os_packages.py`. Perl-base CRITICAL findings remain outside this scope.

| Image reference | Multi-arch digest | Platforms verified (linux) | Digest sources |
| --- | --- | --- | --- |
| `node:24-alpine` | `sha256:d32cdf619f63fe0471182d08996dd516c6275bb5fd31ae06e55a570bd9e1ad43` | amd64, arm64 | Hub tag API + Registry `Docker-Content-Digest` |
| `python:3.11-slim-trixie` | `sha256:9c900dea9e8fb7e16277c179b555cc72d29a352dbc33cff48ad5a0412fd5bfc7` | amd64, arm64 | Hub tag API + official-images GitCommit `fe89472bda6128fef7e964d1f1991534e32dcfb7` |
| `postgres:16-alpine` | `sha256:cf78e76683b9ca8c5733cbbdce6c9262b45b6767934dd0a95e671f9a0fc20685` | amd64, arm64 | Hub tag API + Registry `Docker-Content-Digest` |
| `nginx:1.30-alpine` | `sha256:97d490c12ba55b4946b01546d1c3ed324e8d41ab1c9fcb2a616aa470620e5b46` | amd64, arm64 | Hub tag API + Registry `Docker-Content-Digest` |
| `redis:7-alpine` | `sha256:e7723ff73d963f5cc6d9c4643ea3d989527a402a319239054e9472a7fb9219a2` | amd64, arm64 | Hub tag API + Registry `Docker-Content-Digest` |

**Canonical pin format:**

```text
<repository>:<tag>@sha256:<64-lowercase-hex>
```

The same `repository:tag` must map to the same digest in every tracked file.

**Tag drift policy:** If an upstream tag moves to a new digest, do **not** auto-update. Re-run dual-source verification, update all files and this document together in a reviewed change.

---

## 4. Static enforcement

| Component | Path |
| --- | --- |
| Validator script | `backend/scripts/validate_container_image_pins.py` |
| Validator tests | `backend/tests/test_container_image_pin_validator.py` |
| CI — backend static checks | validator before Ruff/Mypy |
| CI — containers job | validator before Compose validation and Docker builds |
| CI — postgres service | pinned digest in workflow file (services start before steps) |

Validator inventory contract (2026-08-18):

- **8** scanned files
- **12** runtime external pinned references (S3d4b: prod Dockerfile shares one python-base pin)
- **6** scanner pinned references (3× Syft + 3× Trivy in `containers` job)
- **4** internal build references

---

## 5. Supply-chain scanner images (S3c, not runtime)

Scanner images are pinned for CI only. They are **not** application runtime bases.

Cross-verified on **2026-08-18**:

| Image reference | Multi-arch digest | Platforms | Release |
| --- | --- | --- | --- |
| `anchore/syft:v1.51.0` | `sha256:678bfa565b60f747aac0f8e964fe5588a24445b8d0a480e91f6efd70020dfbb0` | linux/amd64, linux/arm64 | https://github.com/anchore/syft/releases/tag/v1.51.0 |
| `aquasec/trivy:0.74.0` | `sha256:62b1e65e8869bc4b4c6aa4fa2b21595256c7c2f6018a9d9ad61caf87187c1969` | linux/amd64, linux/arm64 | https://github.com/aquasecurity/trivy/releases/tag/v0.74.0 |

**Upgrade procedure:** See `docs/supply-chain-security-policy.md` section 9.

**Vulnerability DB:** Trivy DB is a scan-time snapshot and is intentionally **not** pinned. Scanner binary/image pins do not imply bit-for-bit reproducible vulnerability results across dates.

**Remote execution:** S3c scan steps are implemented in CI but require a successful remote `containers` job run to prove end-to-end SBOM + vulnerability evaluation on built images. Scanner digest changes require the same review process as runtime pins.

---

## 6. Update procedure

1. Check official lifecycle pages for EOL or support-window changes.
2. Choose a supported tag (never `:latest`).
3. Resolve the multi-arch manifest list digest; cross-verify Hub tag `digest` and Registry `Docker-Content-Digest`.
4. Confirm required platforms (`linux/amd64`, and `linux/arm64` when Apple Silicon dev matters).
5. Update all allowlisted files to the same `tag@sha256:digest`.
6. Update this document (inventory, dates, digests, review dates).
7. Run validator, backend/frontend verification suites, and RC compose config validation.
8. Rebuild RC/production images in CI.

---

## 7. Rollback principles

- Roll back by reverting the git commit that changed pins and policy together.
- If a pinned digest fails CI builds but the tag moved, re-resolve digest from registry; do not remove the pin.
- Do **not** roll back to EOL runtimes (e.g. Node 20) for convenience.
- Do **not** roll back from current nginx stable to legacy stable without explicit review.

---

## 8. Known limitations

- **Base-image identity only:** apt, pip, and npm install steps can change between builds even with a fixed base digest.
- **Tag drift:** Tags such as `24-alpine` can point to new digests upstream; refresh pins deliberately after review.
- **Redis:** Dev-only; no production lifecycle commitment in this policy.
- **Internal RC tags:** Local build tags are outside external pin scope but validated against an internal allowlist.
- **S3c scope:** Runtime pinning does not claim images are vulnerability-free. SBOM/scan policy lives in `docs/supply-chain-security-policy.md`. Remote CI scan proof is pending for S3c completion.
