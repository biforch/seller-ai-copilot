# SellerAI Copilot Operations Readiness Contract

This document defines the minimum observable and recoverable operating contract for an
RC or production release. It does not provision a monitoring vendor, DNS, TLS, backup
storage, or on-call routing. Those external integrations must be selected and tested
before a public launch.

## Health monitoring

Run the credential-free probe from outside the application host or cluster:

```bash
cd backend
python scripts/check_service_health.py https://seller.example
```

The probe calls only `/health` and `/health/ready`, rejects redirects and credentialed
URLs, limits response size, validates the public JSON contract, and prints only a fixed
success or failure token. It never accepts a bearer token or database credential.

Minimum schedule and alerts:

| Signal | Trigger | Initial response |
|---|---|---|
| External liveness | 2 consecutive failures at 60-second intervals | Page the service owner; verify edge and frontend/backend container health |
| Database readiness | 2 consecutive failures at 60-second intervals | Page the service and database owners; stop deploys and Amazon sync triggers |
| HTTP 5xx ratio | >2% for 5 minutes or >20 responses in 5 minutes | Inspect fixed-field application logs; roll back the application if correlated with a deploy |
| OAuth callback 429 | Sustained for 5 minutes | Check abuse/traffic source without recording query strings; do not disable the limiter |
| OAuth callback 5xx | Any sustained burst or 3 failures in 5 minutes | Stop OAuth promotion; verify redirect config, LWA reachability, and state persistence |
| Amazon sync failures | 5 failures for one account in 15 minutes | Pause manual retries; inspect stable error codes and lease ownership |
| Stale processing log | Older than the documented lease/recovery threshold | Run the read-only reconciliation check; do not clear another worker's lease manually |
| PostgreSQL capacity | Disk >80%, connections >80%, or backup failure | Page database owner; stop deploys before capacity exhaustion |
| Certificate expiry | <30 days warning, <14 days page | Renew at the approved HTTPS edge; do not bypass TLS validation |

Every alert must have a named owner, primary and backup notification route, and a tested
acknowledgement path. Until those values are configured in an external monitoring
system, public-production readiness remains blocked.

## Log and privacy contract

- Do not record request/response bodies, Authorization headers, cookies, OAuth query
  strings, raw state, codes, seller IDs, refresh/access tokens, page tokens, or provider
  payloads.
- Keep the exact OAuth callback access-log suppression at every CDN, load balancer,
  ingress, nginx, and Uvicorn layer.
- Alert only on fixed categories, stable error codes, status classes, counts, durations,
  and opaque internal IDs already approved by the application logging contract.
- Restrict log access by role. Record administrative access and define retention in the
  selected platform before public deployment.

## Backup and restore acceptance

The RC runbook defines the executable custom-format PostgreSQL rehearsal. A release is
not recoverable merely because `pg_dump` exited successfully. Acceptance requires:

1. a custom-format dump created from the exact target database;
2. a cryptographic checksum stored separately from the dump;
3. `pg_restore --list` validation;
4. restore into a fresh, explicitly named disposable database;
5. Alembic head, schema, and representative row-count verification;
6. application readiness against the restored copy in an isolated rehearsal;
7. recorded recovery point objective (RPO) and recovery time objective (RTO).

Production defaults pending infrastructure approval:

- daily encrypted backups retained for 35 days;
- monthly encrypted backups retained for 12 months;
- separate account/project or immutable storage boundary from the application runtime;
- quarterly restore rehearsal and after every destructive migration class;
- RPO <=24 hours and RTO <=4 hours for the initial launch.

These are minimum policy targets, not proof that backup infrastructure exists. Public
deployment remains blocked until encryption, retention, access control, deletion, and a
successful restore are evidenced in the chosen platform.

## Migration and rollback

- Take and validate a backup before migration.
- Run Alembic once as a deployment job before application replicas start.
- Prefer rolling the application image back while retaining a forward-compatible schema.
- Do not use destructive Alembic downgrade as a production data-recovery mechanism.
- If schema rollback would destroy or rewrite data, restore the verified database backup
  into an isolated target and perform a controlled cutover.

## Incident response

1. Declare severity and assign an incident commander.
2. Freeze deploys and preserve logs/artifacts without copying secrets into chat or tickets.
3. Contain: disable the affected capability through existing configuration only when the
   action is understood (for example, Amazon OAuth/SP-API capability flags).
4. Diagnose with stable error codes, health results, deployment SHA, migration head, and
   supply-chain artifact—not raw credentials or provider payloads.
5. Recover using the last verified image and, when required, the tested restore procedure.
6. Rotate exposed credentials and encryption material through an approved key-rotation
   plan; do not edit ciphertext manually.
7. Complete a blameless review with timeline, impact, corrective actions, and evidence that
   alerting now detects the failure mode.

## Release evidence record

For each promoted SHA, retain:

- PR and immutable commit SHA;
- Quality Gate run and exact nine-file supply-chain artifact identity;
- production image tag/digest inventory;
- Alembic head;
- backup checksum and restore-rehearsal timestamp (never the dump in Git);
- health/smoke results with secrets removed;
- approver and rollback image reference.

Do not attach `.env`, database dumps, SBOMs containing prohibited host data, Trivy caches,
OAuth callbacks, or real provider responses to the repository.
