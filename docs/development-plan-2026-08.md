# SellerAI Copilot Development Plan

**Plan version:** 2026-08-19
**Code baseline:** Draft PR #1 on `codex/amazon-mvp-hardening`; R2b verified at `a73a104`
**Current verdict:** Core Amazon MVP and deterministic production build are remotely verified. R2b security hardening is verified by Quality Gate run `32280189796`. Local RC acceptance, operational rehearsal, browser-session migration, and controlled real-Amazon acceptance remain open before public launch.
**Source of truth:** Current code, Alembic migrations, automated tests, and this plan. Earlier A3/A4 design reviews remain historical references and are not active delivery plans.

## 1. Product objective

Deliver a tenant-safe SellerAI workflow in which a seller can:

1. connect an Amazon seller account through OAuth;
2. discover eligible marketplaces;
3. synchronize seller listings without overwriting SellerAI-owned content;
4. explicitly link an Amazon listing to a SellerAI product;
5. enrich the listing with bounded Amazon catalog context;
6. generate an AI proposal;
7. review and approve the proposal through the existing immutable listing-version workflow.

Publishing content back to Amazon is **not** part of the current MVP. Human review remains mandatory.

## 2. Non-negotiable engineering rules

- Tenant ownership is checked in the database query, not only in the API layer.
- Cross-tenant missing and forbidden resources use the same tenant-safe `404` contract.
- Refresh tokens remain encrypted at rest; access tokens, OAuth codes, raw state tokens, page tokens, credentials, headers, and raw provider payloads are never persisted or logged.
- OAuth state is opaque, server-bound, single-use, time-limited, and fail-closed.
- External HTTP calls do not run inside long database transactions.
- Sync writes are fenced by lease ownership and finalize atomically.
- Amazon snapshots never overwrite `ListingVersion`, `ListingProposal`, or an existing `product_id` link.
- Amazon listing identity remains `(amazon_account_id, marketplace_id, seller_sku)`; ASIN is not globally unique.
- Production and RC deployment never read a repository `.env` implicitly.
- No release promotion occurs while a required quality, image-build, migration, readiness, or smoke gate is failed or skipped.

## 3. Current implementation status

### Complete

- Core project/product, generation quota, immutable listing versions, proposals, review UI, tenant isolation, pagination, and response contracts.
- Amazon SP-API transport, LWA refresh, typed Sellers/Listings/Catalog clients, response limits, retries, redaction, and mock/sandbox support.
- Encrypted Amazon accounts, seller ownership uniqueness, marketplace participation, sync logs, account-global leases, and stale-lease recovery.
- OAuth configuration, consent URL allowlist, authorization-code exchange, PostgreSQL state persistence, replay protection, connect/reauthorize orchestration, and callback/start APIs.
- Tenant-safe Amazon account reads, marketplace refresh, listing synchronization, listing reads, and manual REST triggers.
- Amazon listing-to-product linking, catalog snapshot/enrichment, Amazon workspace UI, and catalog-aware AI proposal generation.
- RC configuration validation, database readiness, production Dockerfiles, pinned GitHub Actions, backend/frontend quality jobs, Compose validation, and production-image build jobs.
- Official-registry lockfile enforcement, digest-pinned runtimes, four-image SBOM/Trivy policy, Alpine backend runtime hardening, Next.js 16 migration, ESLint 0/0 CI, and amd64/arm64 backend scan coverage.
- RC browser response headers, OAuth start/callback rate limiting, live-environment wildcard-CORS rejection, and production API-documentation suppression.

### Partial or deliberately deferred

- Account lifecycle: connect and reauthorize exist; disconnect/delete/ownership transfer do not.
- Post-connect orchestration: marketplace refresh is manual rather than automatic.
- Product linking UI only loads the first 100 products.
- Product synchronization aggregates at most 10,000 listings in memory; no checkpointed large-catalog mode exists.
- Stale sync-log recovery occurs on later lease acquisition; no scheduled recovery job exists.
- Encryption supports a key ring, but no bulk rotation/re-encryption operational workflow exists.
- Celery/Redis background execution is not wired into business code.
- Amazon online behavior for Listings and Catalog has not been revalidated against a controlled live seller account.
- GitHub backend, frontend, production image, SBOM, and vulnerability jobs pass remotely on Draft PR #1.
- A full disposable RC lifecycle (start, smoke, restart, backup/restore, rollback, and cleanup) has not yet been rehearsed locally.

### Out of scope until explicitly approved

- Automatic ASIN/SKU-to-product guessing.
- Direct mutation of an approved/current listing without the proposal workflow.
- Automatic Amazon publishing.
- Inventory, pricing, orders, advertising, or FBA workflows.
- Multi-region or multi-marketplace parallel sync that weakens the account-global lease.

## 4. Latest review findings

### Release blockers

1. **OAuth callback access-log exposure** — **Resolved in `ecbf770` (S1).**
   `state`, `spapi_oauth_code`, and `selling_partner_id` arrive in a GET query. Default nginx and Uvicorn access logs can retain the complete request target even though application logs are redacted. RC nginx now disables callback access logs; backend installs a Uvicorn access-log filter; runbook documents upstream ingress requirements.

2. **Amazon workspace request race** — **Resolved in `248687f` (S2).**
   Marketplace and listing requests could resolve out of order after rapid account/marketplace changes. The workspace now fences reads with per-resource request gates, synchronously invalidates dependent state on selection changes, and scopes action results to the active account/marketplace.

### Pre-staging security work

3. **Browser bearer-token storage** — **Partially mitigated in `a73a104` (R2b), not resolved.**
   The 24-hour JWT remains JavaScript-readable in `localStorage`. RC now emits a constrained CSP and other browser headers, but the policy retains narrowly documented inline allowances for Next.js and cannot protect a bearer token from every same-origin XSS or compromised dependency. S4 remains a public-launch gate.

4. **Mutable container bases** — **Resolved in `65fdc7f` (S3b).**
   Python, Node, nginx, and PostgreSQL release/CI/dev references now use reviewed `tag@sha256:digest` pins with an offline validator and documented lifecycle policy.

5. **Unapproved npm registry dependency** — **Resolved in `8b3f77d` (S3a).**
   The frontend lockfile now resolves all tarballs from `registry.npmjs.org`; `.npmrc`, CI, Docker, and static validators fail closed before `npm ci` when disallowed sources appear.

### Product usability debt

6. The Amazon product selector cannot reach products after the first 100.

## 5. Execution plan

Work advances by acceptance gate, not by calendar date. A later phase must not start while an earlier blocking gate remains open.

### S1 — OAuth callback log containment

**Priority:** Immediate release blocker
**Status:** Complete (`ecbf770`)
**Scope:** nginx, production backend startup/logging, security tests, RC runbook.

Deliverables:

- Add an exact nginx callback location whose access log is disabled or whose log format excludes query strings.
- Disable Uvicorn production access logging, or install a proven callback request-target redaction filter before any request is emitted.
- Preserve status/latency observability through safe fixed fields or proxy logs that omit query strings.
- Add canary tests proving state, code, seller ID, tokens, and query strings are absent from proxy/backend logs.
- Document that upstream ingress/CDN/load-balancer logs must also omit callback query strings.

Exit gate:

- Callback success, provider denial, invalid/replayed state, and unexpected-failure tests pass.
- Canary values do not appear in application, Uvicorn, nginx, or captured container logs.
- No change to fail-closed state consumption semantics.

### S2 — Amazon workspace concurrency correctness

**Priority:** Immediate correctness blocker
**Status:** Complete (`248687f`)
**Scope:** Amazon workspace request lifecycle and frontend tests.

Deliverables:

- Abort superseded marketplace/listing requests or use monotonic request generations.
- Before committing a response, verify the account and marketplace still match the active selection.
- Prevent stale requests from clearing the active request's loading state.
- Clear dependent marketplace/listing/catalog state synchronously when a parent selection changes.
- Cover rapid account switching, rapid marketplace switching, rejection after supersession, and unmount cancellation.

Exit gate:

- Deliberately reversed response order cannot show or act on stale account data.
- Existing sync, link, catalog, pagination, and error behavior remains intact.
- Frontend type-check and production build pass.

### S3 — Dependency and image supply-chain hardening

**Priority:** Required before staging
**Status:** Complete and remotely verified
**Scope:** lockfile, production Dockerfiles, Compose/CI image references, release tests.

#### S3a — Official npm registry

**Status:** Complete (`8b3f77d`)

Deliverables:

- Point frontend installs at `https://registry.npmjs.org/` via `.npmrc`.
- Normalize lockfile tarball sources to the official registry without changing dependency graph metadata.
- Add a static lockfile registry validator and node:test coverage.
- Run the validator in CI and production Docker deps stages before `npm ci`.

Exit gate:

- No `registry.npmmirror.com` URL remains in the tracked lockfile.
- Clean-cache `npm ci` succeeds from the official registry.
- Validator rejects spoofed hosts, non-HTTPS sources, ports, query strings, fragments, and userinfo.

#### S3b — Runtime lifecycle and image digest pinning

**Status:** Complete (`65fdc7f`)

Deliverables:

- Pin Python, Node, nginx, and PostgreSQL production/CI images to reviewed `tag@sha256:digest` references.
- Keep human-readable tags beside digests for maintainability.
- Add an explicit, reviewable update process for dependency/image digest changes.

Exit gate:

- Rebuilding the same commit resolves the same base image digests.

#### S3c — SBOM and vulnerability policy

**Status:** Complete and remotely verified

Deliverables:

- CycloneDX SBOM generation for backend, frontend, and nginx production images.
- Offline Trivy vulnerability scans from saved image tar (no Docker socket in scanner containers).
- Fail-closed policy evaluator (CRITICAL always blocks; HIGH blocks when fix exists).
- CI artifacts with 14-day retention; no `.trivyignore` in initial phase.

Exit gate (verification):

- Remote `containers` job completes build + SBOM + Trivy + policy evaluation with pinned scanner images.
- S3c may be marked **Verified** only after that remote proof — not after local fixture tests alone.

**S3 overall:** Complete. Production policy passes for backend amd64/arm64, frontend, and nginx with `blocked=0`; evidence is retained in the Quality Gate artifacts.

### S4 — Browser authentication hardening

**Priority:** Required before public staging
**Status:** Pending (not started; remains prerequisite for public staging)
**Scope:** authentication contract, frontend client, CSRF, CSP, migration compatibility.

This is an isolated architecture phase and must not be mixed with S1–S3.

Deliverables:

- Replace JavaScript-readable bearer persistence with `Secure; HttpOnly; SameSite` session/access cookies.
- Define explicit CSRF protection for every state-changing request (origin verification plus token strategy).
- Add login, refresh/expiry, logout/revocation, concurrent-tab, and unauthenticated contracts.
- Shorten access-token lifetime and document renewal behavior.
- Add a CSP compatible with the built Next.js application, including `frame-ancestors 'none'`, `object-src 'none'`, and `base-uri 'self'`; avoid `unsafe-inline` unless narrowly justified.
- Provide a controlled compatibility window or atomic frontend/backend deployment plan so old bearer clients do not fail unpredictably.

Exit gate:

- No authentication/session credential is stored in `localStorage` or `sessionStorage`.
- CSRF, XSS-oriented header, cookie-attribute, expiry, logout, and tenant tests pass.
- OAuth start/callback remains functional without exposing session credentials.

### R1 — Remote quality gate and deterministic build

**Status:** Complete
**Evidence:** Quality Gate run `32276998695` for the integrated baseline and run `32280189796` for R2b both passed backend, frontend, containers, SBOM, Trivy, and policy evaluation.

#### R1a — Remote supply-chain verification

**Status:** Complete

**R1a-1 local npm toolchain gate (complete):**

- Reclassified prior `@emnapi/runtime` extraneous finding as **`NPM_TOOLCHAIN_VERSION_MISMATCH`**, not lockfile graph defect.
- Pinned reproducible frontend toolchain: Node **24.19.0**, npm **11.17.0** (matches S3b `node:24-alpine` digest).
- npm **[PR #9221](https://github.com/npm/cli/pull/9221)** fix: lockfile inert optional entries stay; reifier bug fixed in npm **11.13.0+**.
- Added fail-closed `validate-node-toolchain` and `validate-installed-dependency-tree` gates in CI and Docker (pre/post `npm ci`).
- Lockfile dependency graph unchanged; only root `engines` metadata updated.
- **Prohibited:** deleting `@emnapi/runtime` lock entries, direct dependency workaround, extraneous allowlists.

Deliverables (completed):

- Push authorized branch and execute remote `containers` job on GitHub runners.
- Prove real build + `docker image save` + Syft SBOM + Trivy JSON + policy evaluator on all three production images.
- Collect CI artifacts (`sellerai-supply-chain-<sha>`) and record scan summary.
- If policy blocks on CRITICAL or fixable HIGH, report CVE/package/image summaries — do not add ignore rules in S3c.

Exit gate:

- Remote `containers` job passes with no skipped scan step. **Complete.**
- S3c is marked **Verified** only after that remote proof. **Complete.**

#### R1b — Full remote quality gate

**Status:** Complete
**Entry:** R1a complete.

Deliverables:

- Review local commits as a bounded branch/PR sequence.
- Push only after explicit authorization.
- Require backend, frontend, Compose, and production-image jobs to pass.
- Record exact commit, migration head, action SHAs, image digests, test totals, and build artifacts.

Exit gate: all required remote jobs pass with no skipped job and no secret-bearing logs/artifacts.

### R2 — Release-candidate and operational acceptance

**Status:** In progress

#### R2a — Final read-only readiness audit

**Status:** Complete (`R2A_READY_WITH_PRECONDITIONS`)

#### R2b — Browser edge and OAuth boundary hardening

**Status:** Complete (`a73a104`; remote run `32280189796`)

- OAuth start is limited by a one-way credential digest; callback is limited at the exact nginx path by source IP without logging its query.
- RC nginx emits CSP, referrer, MIME-sniffing, clickjacking, and Permissions-Policy headers.
- Staging/production reject wildcard CORS and disable FastAPI documentation/OpenAPI endpoints.
- HSTS remains the responsibility of the future approved HTTPS termination layer; the loopback HTTP RC does not emit false HSTS.

#### R2c — Operations contract and backup/restore rehearsal

**Status:** In progress

- Update this plan and the RC runbook to current evidence.
- Add a credential-free health probe suitable for an external scheduler.
- Define actionable alert thresholds, ownership, redaction, incident response, and artifact retention.
- Rehearse custom-format backup and restore into a fresh disposable database before release promotion.

#### R2d — Disposable local RC acceptance

**Entry:** R1b complete and Docker available.
**Deliverables:**

- Build backend/frontend/nginx production images.
- Start the disposable `_test` RC database and one-shot migration service.
- Verify `/health`, `/health/ready`, frontend login, disabled production docs, migration head, non-root users, and internal-only service ports.
- Run the documented non-LLM workflow: register, login, project/product, listing import/replay/history, proposal list, and tenant-safe error cases.
- Capture only redacted evidence; do not call real LLM or Amazon endpoints.

Exit gate: repeatable clean start, smoke pass, restart pass, rollback rehearsal, and label-verified RC cleanup.

#### R2e — Controlled Amazon acceptance

**Entry:** R2 complete; approved Amazon Developer Console configuration and disposable seller test scope available.
**Deliverables:**

- Verify exact OAuth redirect registration and Product Listing/Catalog roles.
- Execute one controlled OAuth connect/reauthorize flow.
- Refresh marketplaces, synchronize one marketplace, enrich representative listings, link a product, and create a proposal.
- Exercise provider denial, token invalidation, rate limiting, pagination, empty enumeration, and reauthorization-required behavior where safely possible.
- Confirm access logs and persisted records contain no OAuth code, token, state, page token, raw payload, or sensitive headers.

Exit gate: documented, redacted evidence of the complete seller-to-proposal flow and an explicit go/no-go decision for staging.

#### R2f — Review and merge decision

Only after R2c–R2e evidence is complete may Draft PR #1 be marked ready for human review. Merging PR #1, pushing `main`, and public deployment remain separate explicit authorization points.

### P1 — Product selector scalability

**Entry:** Security blockers closed; may run before or after R2e if it does not delay release validation.

- Replace fixed first-page loading with server-side search and paginated selection.
- Resolve already-linked products by ID even when outside the current result page.
- Preserve tenant filtering and abort stale searches.

### P2 — Account lifecycle design

Disconnect is not a trivial UI action. Define before implementing:

- whether disconnect deletes the account or clears ciphertext and marks it disabled;
- whether disabled accounts retain global seller ownership;
- behavior for listings, catalog snapshots, product links, sync logs, and active leases;
- re-connect and ownership-transfer semantics;
- audit requirements and irreversible-action confirmation.

No disconnect endpoint is added until these rules, migration impact, and concurrency tests are approved.

### P3 — Operational resilience

Implement only from measured need:

- scheduled stale-processing-log reconciliation;
- active encryption-key rotation/re-encryption workflow;
- checkpointed/chunked sync for sellers that exceed current page/item/time limits;
- async worker/Celery wrapper that preserves the same lease and idempotency contracts.

## 6. Required validation matrix

Every implementation phase runs its directed tests plus:

```bash
cd backend
env LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 pytest -q
ruff check app tests scripts
mypy app scripts

cd ../frontend
npx tsc --noEmit
npm run build

cd ..
docker compose --env-file .env.rc.example -f docker-compose.rc.yml config --quiet
git diff --check
```

For changes involving models or migrations, additionally require upgrade → downgrade → re-upgrade against the dedicated migration test database. For concurrency, lease, OAuth state, account ownership, or sync-finalization changes, require real PostgreSQL multi-session tests.

## 7. Commit and review policy

- One concern per commit; security, auth architecture, supply chain, and product behavior remain separate.
- Never commit `.env`, credentials, test seller identifiers, OAuth codes, raw state, tokens, database dumps, or captured provider payloads.
- Keep the two historical A3/A4 design-review files excluded unless a separate documentation decision explicitly includes them.
- Before each commit: inspect staged file list, run `git diff --cached --check`, and verify no unrelated user changes are staged.
- Do not push, deploy, call real Amazon, or perform destructive RC cleanup without explicit authorization and target confirmation.

## 8. Decision checkpoints

The next step is **R2c operations readiness**, followed by R2d disposable RC acceptance. Public launch remains blocked on S4 browser-session hardening, approved HTTPS/DNS and monitoring infrastructure, and R2e controlled Amazon acceptance.

Automatic Amazon publishing remains outside the plan until the read/sync/proposal workflow has production evidence, an explicit publishing threat model, rollback/reconciliation semantics, and separate user authorization.
