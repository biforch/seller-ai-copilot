# Vultr Internal RC Runbook

This adapter deploys the reviewed repository baseline to one Ubuntu 24.04 VPS.
It does not authorize a public Listing Audit launch, Amazon enablement, DNS
changes, or production-data acceptance.

## Release boundary

- Deploy only a clean, reviewed commit reachable from `origin/main`.
- Record the exact commit SHA before building. Never deploy from a dirty
  worktree or copy individual files from one.
- Keep `ANALYSIS_PUBLIC_ENABLED=false`, `LISTING_AUDIT_INTERNAL_ENABLED=false`,
  `LEGACY_GENERATION_ENABLED=false`, and both Amazon flags false.
- The first RC is infrastructure-only. Enabling the registered-user Listing
  Audit requires a later, explicit gate and matching backend/frontend flags.
- Keep the Docker edge bound to `127.0.0.1:8080`; only host nginx exposes 80/443.

## Minimum host preparation

Use a dedicated, non-root deployment user with access to Docker. Restrict SSH
to known administrator addresses, enable automatic Ubuntu security updates,
and allow inbound 80/443 only. A 1 GB instance may run the stack but can exhaust
memory while building; provision encrypted swap and build serially, or build
verified images in CI and pull them. Monitor memory throughout the first run.

Before accepting data, configure an encrypted backup destination outside this
VPS. A Docker volume is not a backup. Retain daily backups for 35 days and
monthly backups for 12 months, record SHA-256 checksums, and prove an isolated
restore.

## Secrets

Copy `.env.vultr.example` to `.env.vultr`, set mode `0600`, and replace every
placeholder locally on the VPS. Never print, upload, or commit it. Required
secret values are:

- `POSTGRES_PASSWORD`
- `DATABASE_URL`
- `JWT_SECRET_KEY`
- `MFA_ENCRYPTION_KEY`
- `OPENAI_API_KEY`

The migration validator prints one fixed failure message and never prints
values. Do not use shell tracing while loading this file.

## Configuration validation

Run from a clean release checkout:

```sh
docker compose --env-file .env.vultr -f docker-compose.vultr.yml config --quiet
docker compose --env-file .env.vultr -f docker-compose.vultr.yml run --rm migrate
```

The migration service must exit zero before backend starts. Confirm the single
Alembic head and record it with the release SHA. Do not use downgrade as a data
recovery mechanism.

## TLS and Cloudflare

Create one origin certificate covering `listnara.com`, `www.listnara.com`, and
`app.listnara.com`. The checked-in host nginx template expects the certificate
at `/etc/letsencrypt/live/listnara.com/`. Validate with `nginx -t` before reload.

For initial origin verification, use DNS-only records or a locally overridden
hostname. After the origin certificate is valid, Cloudflare SSL mode must be
**Full (strict)**. Do not use Flexible mode. HSTS is emitted at the host TLS
edge; verify it over the public hostname before enabling long-lived browser
traffic.

The checked-in adapter deliberately does not trust `CF-Connecting-IP`. With the
orange-cloud proxy enabled, IP-based nginx limits observe Cloudflare egress
addresses rather than proven client addresses. Do not claim per-client edge
rate limiting until Cloudflare proxy ranges are authenticated and a separately
reviewed real-IP configuration is installed. Session-scoped application limits
remain independent of this caveat.

Both host and container nginx have an exact OAuth callback location with access
logging disabled. Before any future Amazon enablement, prove that Cloudflare,
host nginx, container nginx, and application logs do not retain callback query
parameters.

## Start and smoke

Build serially on small hosts, then start only after migration succeeds:

```sh
docker compose --env-file .env.vultr -f docker-compose.vultr.yml build backend
docker compose --env-file .env.vultr -f docker-compose.vultr.yml build frontend
docker compose --env-file .env.vultr -f docker-compose.vultr.yml build edge
docker compose --env-file .env.vultr -f docker-compose.vultr.yml up -d
docker compose --env-file .env.vultr -f docker-compose.vultr.yml ps
curl --fail --silent --show-error https://app.listnara.com/health/ready
```

Verify Secure/HttpOnly session cookies, CSRF and Origin rejection, MFA login,
404 responses for docs/OpenAPI, tenant isolation, restart persistence, security
headers, and zero secret/callback-query log matches. Keep Amazon and public
Analysis disabled.

## Current `/api/v1/audits` incident

The observed VPS request made two successful OpenRouter calls and then returned
502. That sequence rules out provider transport failure; it places the failure
after provider output, in the experimental response validation, grounding,
isolation, entitlement, or persistence path.

More importantly, `/api/v1/audits` is not an endpoint in the reviewed
`main@6077bb8` contract. The reviewed B1 endpoint is
`/api/v1/analysis/listing-audit`. The VPS therefore contains unmerged B2/billing/
analytics work from the frozen dirty worktree. Do not patch that server in
place and do not replay the request until its source SHA is captured.

The browser 401 is a separate authentication result; the captured backend log
shows `/api/v1/auth/me` returning 200 before the audit. Identify the exact 401
request path in browser Network data without copying Cookie or CSRF values.
After any clean redeploy, sign in again because existing sessions need not be
portable across databases or secrets.

Recovery sequence:

1. Stop new audit submissions; keep the current containers available only long
   enough to collect redacted logs and the deployed image/source SHA.
2. Take and checksum an encrypted database backup; perform an isolated restore.
3. Deploy a clean reviewed main release with all analysis flags false.
4. Verify health, migration head, authentication, MFA, and tenant isolation.
5. Investigate the experimental `/audits` implementation in a separate branch.
   It must not be folded into this infrastructure adapter.

## Monitoring and rollback

Better Stack should probe `/health/ready` without credentials. Sentry must use
server/client DSNs supplied outside Git and must redact Cookie, Authorization,
CSRF, OAuth query values, request bodies, and user-entered listing text. Test an
alert before accepting traffic.

Rollback the application to the previously recorded image/SHA only after a
backup. Do not automatically downgrade the database. If a migration changes
data semantics, stop traffic and restore into an isolated database before a
go/no-go decision.
