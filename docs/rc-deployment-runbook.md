# SellerAI Copilot RC Deployment Runbook

Disposable local/staging rehearsal stack using production-style Docker images.
Development workflow (`docker-compose.yml`, dev Dockerfiles) is unchanged.

## 1. Prerequisites

- Docker Engine and Docker Compose v2.1+ (`docker compose version`)
- Repository checkout at a tagged RC commit
- **Do not** reuse production database credentials or real LLM API keys
- **Do not** commit `.env.rc` (copy from `.env.rc.example` locally only)
- Port `8080` (or your `RC_HTTP_PORT`) available on `127.0.0.1`
- The repository Quality Gate must pass: backend static/full tests, frontend
  TypeScript/production build, RC Compose validation, and production image builds.
  Do not promote a commit with a failed or skipped job.

## 2. Create local RC env file

```bash
cp .env.rc.example .env.rc
```

Edit `.env.rc` and replace **all** placeholders before starting:

- `POSTGRES_USER` (must match the username embedded in `DATABASE_URL`)
- `POSTGRES_PASSWORD`
- `DATABASE_URL` (username and password must match `POSTGRES_USER` / `POSTGRES_PASSWORD`; percent-encode reserved characters in the URL only)
- `JWT_SECRET_KEY` (at least 32 characters)

Amazon remains disabled in the default RC profile. Do not add Amazon secrets unless
you are intentionally running the capability-gated Amazon rehearsal in section 4.

Never commit this file.

## 3. Generate RC-only secrets

Generate strong random values at runtime (do not paste into Git or review artifacts):

```bash
# JWT (>= 32 chars for staging)
python -c "import secrets; print(secrets.token_urlsafe(48))"

# Database password — prefer URL-safe values to avoid DATABASE_URL encoding issues
python -c "import secrets; print(secrets.token_urlsafe(24))"
```

Set outputs in `.env.rc`:

- `JWT_SECRET_KEY` — first command (minimum 32 characters; validator rejects shorter values)
- `POSTGRES_PASSWORD` — second command
- `POSTGRES_USER` — keep `sellerai_rc` unless you change it consistently everywhere
- `DATABASE_URL` — username and decoded password must match `POSTGRES_USER` / `POSTGRES_PASSWORD`, e.g.
  `postgresql://sellerai_rc:<password>@postgres:5432/sellerai_rc_test`

If the password contains reserved URL characters (`@`, `:`, `/`, `%`, etc.), percent-encode it in `DATABASE_URL` only. The RC validator decodes the URL with `urllib.parse.unquote` before comparing to `POSTGRES_PASSWORD`.

Staging mode requires at least 32 characters for JWT and rejects known weak defaults.

## 4. Optional Amazon capability profile

Keep `AMAZON_SP_API_ENABLED=false` and `AMAZON_OAUTH_ENABLED=false` for the default
non-Amazon smoke test. To rehearse Amazon connectivity, set SP-API enabled with
`AMAZON_SP_API_ENDPOINT_MODE=production`, official LWA credentials, and runtime-generated
32-byte base64url values for `AMAZON_TOKEN_KEY_V1` and
`AMAZON_TOKEN_FINGERPRINT_PEPPER`. Never reuse production encryption material in RC.

OAuth additionally requires `AMAZON_OAUTH_ENABLED=true`, the Seller Partner application
ID, and externally reachable HTTPS redirect/success/error URLs. The localhost-only HTTP
nginx binding is not a valid Amazon OAuth callback. Place an approved HTTPS ingress in
front of RC and set `CORS_ORIGINS` to that exact origin before enabling OAuth.

The migration safety gate validates these requirements before Alembic runs. With Amazon
disabled, empty Amazon credentials remain valid and no Amazon network call is made.

## 5. Build images

```bash
docker compose -p sellerai_rc \
  --env-file .env.rc \
  -f docker-compose.rc.yml \
  build --pull
```

Images:

- `sellerai-backend-prod:rc` (from `backend/Dockerfile.prod`)
- `sellerai-frontend-prod:rc` (from `frontend/Dockerfile.prod`)

## 6. Validate Compose config

```bash
docker compose -p sellerai_rc \
  --env-file .env.rc \
  -f docker-compose.rc.yml \
  config --quiet
```

Confirm required variables resolve and services are `postgres`, `migrate`, `backend`, `frontend`, `nginx`.

## 7. Start stack

```bash
docker compose -p sellerai_rc \
  --env-file .env.rc \
  -f docker-compose.rc.yml \
  up -d
```

Project name `sellerai_rc` isolates containers, network, and volumes from dev `docker-compose.yml`.

## 8. Migration one-shot behavior and RC safety gate

The `migrate` service:

1. Waits for `postgres` healthy
2. Runs `python scripts/validate_rc_environment.py` (disposable RC safety gate)
3. On success only, runs `alembic upgrade head` using the backend production image
4. Exits successfully before `backend` starts (`depends_on: service_completed_successfully`)

If the safety gate fails, Alembic **never** runs and `migrate` exits non-zero; `backend` does not start.

This gate protects **only** the disposable RC Compose stack. It does **not** replace staging/production deployment approval, change application config validation, or alter pytest migration guards.

Migrations are **not** run inside each backend replica. Check logs:

```bash
docker compose -p sellerai_rc --env-file .env.rc -f docker-compose.rc.yml logs migrate
```

## 9. Health checks

| Target | Command / URL |
|--------|----------------|
| Nginx (public) | `curl -fsS http://127.0.0.1:8080/health` |
| Backend liveness | `curl -fsS http://127.0.0.1:8080/health` |
| Backend DB readiness | `curl -fsS http://127.0.0.1:8080/health/ready` |
| OpenAPI | Expected `404` in staging/production (`/docs`, `/redoc`, and `/openapi.json` are disabled) |
| Frontend login | `curl -fsS -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/login` |

Container health:

```bash
docker compose -p sellerai_rc --env-file .env.rc -f docker-compose.rc.yml ps
```

## 10. Non-LLM smoke test (manual)

Access via **nginx** at `http://127.0.0.1:8080` (browser same-origin; API base is `/api/v1`).

Suggested checks (no Generate / LLM calls):

1. Home / login page returns 200
2. Register a disposable test user
3. Login and obtain JWT
4. Create Project → Product
5. Paginated product/list endpoints
6. `GET .../listing/current` → 404 for new product
7. Import first listing version → 201
8. Replay → 200
9. Version history list
10. Proposal list
11. Unauthenticated protected API → **403** (FastAPI `HTTPBearer` missing-credentials behavior; RC1.1 does not change auth contract)
12. Invalid body → 422 with standard error shape

**Do not** invoke listing Generate in RC smoke (requires real LLM).

## 11. Logs

```bash
docker compose -p sellerai_rc --env-file .env.rc -f docker-compose.rc.yml logs -f nginx
docker compose -p sellerai_rc --env-file .env.rc -f docker-compose.rc.yml logs -f backend
docker compose -p sellerai_rc --env-file .env.rc -f docker-compose.rc.yml logs -f frontend
docker compose -p sellerai_rc --env-file .env.rc -f docker-compose.rc.yml logs migrate
```

Redact passwords and JWT before sharing logs.

### OAuth callback log isolation

Amazon OAuth callback uses `GET /api/v1/amazon/oauth/callback` with sensitive query
parameters (`state`, `spapi_oauth_code`, `selling_partner_id`, `error`,
`error_description`). These values must never appear in access logs.

RC nginx (`nginx/nginx.rc.conf`) defines an exact-match callback location with
`access_log off;` before the generic `/api/` proxy block. The request is still
proxied to `rc_backend` with the original query string; only the nginx access log
line is suppressed. The same exact location enforces a per-source-IP callback
rate limit before proxying. OAuth start has a separate authenticated application
limit keyed by a one-way digest of the bearer credential; neither limiter logs or
stores the credential or callback query.

The backend installs a Uvicorn `uvicorn.access` filter at startup
(`app/core/access_log_safety.py`) that drops access-log records for the exact
callback path. This protects non-RC deployments that run Uvicorn directly or
behind another ingress without the RC nginx rule.

Any external CDN, load balancer, or ingress in front of RC or production must
also be configured **not** to log the callback query string. Do not enable debug
logging that prints full request URLs for OAuth traffic.

Log acceptance for callback isolation must use fake canary values in tests only.
Never paste real OAuth codes, refresh tokens, raw state tokens, or seller IDs
into runbooks, tickets, or CI artifacts.

### Browser response hardening

The RC nginx edge adds CSP, clickjacking, MIME-sniffing, referrer, and browser
capability headers to all responses. The CSP intentionally permits inline scripts
and styles required by the current Next.js production output; it limits external
origins but does not eliminate the separate risk of keeping bearer tokens in
browser storage. Treat a future HttpOnly-cookie migration as a public-production
security gate, not as completed by these headers.

This stack listens on loopback HTTP only. It deliberately does not emit HSTS.
Any public deployment must terminate approved HTTPS before the application and
set HSTS at that HTTPS edge after domain/subdomain readiness is verified. The
external edge must preserve the callback access-log suppression and rate limit.

In staging and production, backend startup rejects wildcard `CORS_ORIGINS`, and
FastAPI does not expose `/docs`, `/redoc`, or `/openapi.json`. Use explicit HTTPS
origins in public environments.

## 12. Stop stack

```bash
docker compose -p sellerai_rc \
  --env-file .env.rc \
  -f docker-compose.rc.yml \
  down
```

Add `--volumes` only when you intend to destroy RC database data (see below).

## 13. Remove RC volumes only

With project `-p sellerai_rc` and volume key `postgres_data`, Docker Compose creates a project-scoped volume named **`sellerai_rc_postgres_data`**.

**Before** `down --volumes`, verify Compose labels on the exact volume name:

```bash
docker volume inspect sellerai_rc_postgres_data \
  --format '{{index .Labels "com.docker.compose.project"}} {{index .Labels "com.docker.compose.volume"}}'
```

Expected output:

```text
sellerai_rc postgres_data
```

Only proceed when **both** labels match:

- `com.docker.compose.project=sellerai_rc`
- `com.docker.compose.volume=postgres_data`

Then remove RC stack and its volumes:

```bash
docker compose -p sellerai_rc \
  --env-file .env.rc \
  -f docker-compose.rc.yml \
  down --volumes
```

This removes **only** volumes declared in `docker-compose.rc.yml` for project `sellerai_rc`. It does **not** remove dev `postgres_data`.

RC cleanup must use label-verified `docker compose ... down --volumes` only.

## 14. Forbidden cleanup

**Never** run `docker system prune` on shared machines — it can delete unrelated images, containers, and volumes.

## 15. Data backup principles

Before schema changes or RC teardown with data you might need:

```bash
docker compose -p sellerai_rc --env-file .env.rc -f docker-compose.rc.yml \
  exec -T postgres \
  sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' > rc-backup.sql
```

Store dumps outside the repo. **Do not** commit backup files. RC databases are disposable (`*_test` naming); production backups follow separate policy.

## 16. Migration rollback principles

1. **Backup first** (pg_dump or snapshot).
2. Alembic `downgrade` is risky if migrations drop columns/tables or rewrite data — review each revision's `downgrade()` before running.
3. **Prefer application rollback**: deploy previous image tag while keeping DB at current head if backward compatible.
4. Do not downgrade production DB casually to match an old app without a written plan.
5. RC uses the same migration chain as dev; migration guards for destructive tests are pytest-only — normal `alembic upgrade head` is unaffected.

## 17. Application image rollback

```bash
# Tag images before deploy, e.g. sellerai-backend-prod:rc-20250814
docker compose -p sellerai_rc --env-file .env.rc -f docker-compose.rc.yml build
docker tag sellerai-backend-prod:rc sellerai-backend-prod:rc-previous

# Roll back: rebuild from previous git tag or retag saved image, then:
docker compose -p sellerai_rc --env-file .env.rc -f docker-compose.rc.yml up -d --no-build
```

Database schema must remain compatible with the rolled-back application version.

## 18. Stale generation reconcile (manual)

There is no cron in RC. To list stale `processing` generation requests:

```bash
docker compose -p sellerai_rc --env-file .env.rc -f docker-compose.rc.yml \
  exec backend python scripts/reconcile_stale_generations.py
```

Or from host with matching `DATABASE_URL` pointed at RC Postgres (127.0.0.1 port only if temporarily exposed for debug).

This script **detects only** — it does not retry LLM calls.

## 19. Known limitations

| Area | RC behavior |
|------|-------------|
| LLM / Generate | Not exercised in RC smoke; placeholder `OPENAI_API_KEY` only satisfies config |
| Rate limiting | Post-login limits still keyed by client IP |
| Trusted proxy | RC nginx sets `X-Forwarded-For` from `$remote_addr` only; full trusted-proxy design pending staging |
| SP-API | Capability-gated and disabled by default; live rehearsal requires explicit secrets |
| Amazon publishing | Not enabled; generated content remains a review proposal |
| Redis | Not deployed — config default unused by current business code |
| Debug ports | Postgres/backend/frontend are not published; nginx binds `127.0.0.1:8080` only |

## 20. Security reminders

- Do **not** commit `.env.rc`
- Do **not** reuse RC credentials in staging/production
- Do **not** embed secrets in `NEXT_PUBLIC_*` build args
- Rotate JWT and DB password if `.env.rc` was ever exposed

## 21. Local debug (optional)

To attach a debugger to backend temporarily, publish backend on localhost only by adding under `backend` in a **local override file** (not committed):

```yaml
ports:
  - "127.0.0.1:8000:8000"
```

Remove after debugging.
