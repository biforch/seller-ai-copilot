# PostgreSQL Backup and Restore Plan

## Scope and current state

Production runs on a Vultr VPS using Docker Compose (`docker-compose.vultr.yml`). The intended external backup target is the private Cloudflare R2 bucket `listnara-production-backups`.

**Current state (not yet fully verified in production):**

- The R2 bucket exists.
- Automated scheduled backup upload to R2 is **not yet confirmed enabled**.
- Manual backup copies may exist; final storage location and retention are **not yet fully confirmed**.
- Production Amazon connectivity is **disabled**, so production currently does not process Amazon seller information.

See also `amazon-backup-retention-policy.md` for Amazon-specific retention rules.

## Objectives

Approved targets once automated backups are enabled and verified:

- RPO: 24 hours or better.
- RTO: 8 hours or better for the initial production tier.
- Daily encrypted operational backups retained for **35 days**.
- Monthly archives retained for **12 months** only for backup sets that **exclude Amazon-derived data** (Scheme B). Until that pipeline exists, use Scheme A: no 12-month retention for full-database dumps that may contain Amazon-derived data.

## Required controls

- Create encrypted logical backups from the PostgreSQL container/volume.
- Upload privately to the R2 bucket with least-privileged credentials.
- Never expose the bucket publicly.
- Encrypt transport, avoid credentials in commands/logs, and record a checksum plus non-sensitive manifest for every backup.
- Failed or missed backups generate an alert to the configured operations email.
- Lifecycle rules remove expired objects according to the approved schedule (35-day ceiling for Amazon-bearing operational backups).

## Restore procedure

1. Select a backup by manifest and verify its checksum.
2. Restore into an isolated non-production database with separate credentials.
3. Validate schema migrations, row-count invariants and application health using sanitized checks.
4. Confirm tenant isolation and token ciphertext integrity without exposing decrypted values.
5. Re-apply disconnect/deletion records for users who requested erasure after the backup snapshot when required.
6. Destroy or securely expire the temporary restore environment after approval.
7. Record elapsed time, achieved recovery point, errors and follow-up actions.

## Evidence

`EVID-BKP-001` records scheduled backup success, checksum, retention and alert verification. `EVID-BKP-002` records the restore exercise and achieved RPO/RTO. Evidence must not contain backup contents, database URLs or credentials.
