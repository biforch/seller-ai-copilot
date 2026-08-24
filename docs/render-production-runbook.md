# Render internal RC adapter (Amazon-off)

Status: isolated configuration review only. Do not sync `render.yaml`, connect a
repository, create a Render resource, configure a secret, change DNS, or deploy
until a later explicit authorization. Amazon remains disabled. LOG-02 is
unresolved. This adapter is not production-ready and is not Amazon-on approval.

## Scope

This branch adds a Render-specific edge/private-service Blueprint on top of the
audited production OCI images. It does not change application business code,
frontend dependencies, Alembic revisions, or vulnerability policy.

Nginx callback `access_log off` is not a substitute for platform log proof.
Until Render gives written confirmation that HTTP request logs, traces, support
diagnostics, and log streams never retain `/api/v1/amazon/oauth/callback` query
strings (or that retention can be excluded), Amazon OAuth ingress stays closed.

## Known Blueprint limitation

Render Blueprint deploys are not atomic across `listnara-edge`,
`listnara-frontend`, and `listnara-backend`. A failed `preDeployCommand` blocks
**that backend release**, but it does not freeze the other two services. Manual
operators must follow the order below and must never publish only the edge.

## Required publish order

1. PostgreSQL 16 and the external backup target are ready (encryption, retention,
   checksum, failure alert). Do not start application deploys first.
2. Deploy `listnara-backend` only after secrets are present in Render Secret
   Manager (`JWT_SECRET_KEY` and `OPENAI_API_KEY` are `sync: false`; never
   `generateValue`). The backend `preDeployCommand` runs the fail-closed
   environment validator and `alembic upgrade head`. A failed pre-deploy must
   stop that backend publish.
3. Confirm backend `/health` and `/health/ready`.
4. Deploy `listnara-frontend` and confirm its health check.
5. Deploy `listnara-edge` last. Never publish the public edge while backend or
   frontend is missing, migrating, or unhealthy.

Automatic deploys stay off. The Render-generated public subdomain stays disabled.

## TLS, cookies, and forwarding

The edge template overwrites `X-Forwarded-Proto` with `https` and emits HSTS.
It does not trust a client-supplied proto header. `SESSION_COOKIE_SECURE=true`
and CORS `https://app.listnara.com` are locked by the environment validator.

Cloudflare `CF-Connecting-IP` is forgeable until a trusted proxy chain is
proven (authenticated origin pulls or equivalent). This adapter therefore rate
limits and forwards identity using the TCP peer Render connected
(`$binary_remote_addr` / `$remote_addr`). If Cloudflare sits in front, that
peer is a Cloudflare edge address, so per-client throttling is coarser. Do not
switch to `CF-Connecting-IP` without a verified trust chain.

## Internal RC Amazon contract

- `AMAZON_SP_API_ENABLED=false`
- `AMAZON_OAUTH_ENABLED=false`
- `AMAZON_SP_API_ENDPOINT_MODE=mock`
- `OPENAI_AMAZON_DATA_ENABLED=false`

Do not place the production Seller Central redirect URI until LOG-02, TLS/HSTS
cookie verification, monitoring, backup restore, and a separate R2e
authorization are complete.

## Secret handling

Enter secret values only in Render Secret Manager. Chat, IDEs, commits, tickets,
screenshots, deploy logs, and shell history are not approved secret channels.
Confirm only that a named secret has been configured, never its value.
