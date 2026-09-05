# Amazon-Derived Data and Backup Retention Policy

## Current production state

- `AMAZON_OAUTH_ENABLED=false`
- `AMAZON_SP_API_ENABLED=false`
- Listnara does **not** currently process production Amazon seller information in the live environment.

Before production Amazon connectivity is enabled, operational backup retention and deletion controls for Amazon-derived data must be activated and verified.

## Active systems vs encrypted backups

| Layer | Definition | User-facing deletion |
|---|---|---|
| Active application systems | PostgreSQL primary database and running application containers | Disconnect and account deletion remove data here immediately |
| Encrypted operational backups | pg_dump or provider snapshots stored privately (target: Cloudflare R2 bucket `listnara-production-backups`) | Not queryable for normal business use; expire by retention rotation |

Automated upload to R2 is a **target** control and is **not yet confirmed enabled** in production. Manual backup copies may exist; their final location and retention are not yet fully confirmed.

## Selected approach: Scheme A (recommended)

Listnara uses **Scheme A** because full-database PostgreSQL backups are the most reliable restore path for a single-database deployment.

**Scheme A — unified operational backup retention for Amazon-bearing dumps**

- Any encrypted operational backup that may contain Amazon refresh-token ciphertext, `amazon_*` tables, Amazon-linked audit snapshots, or Amazon-linked listing-audit generations is retained for **at most 35 days**.
- Daily backups follow the 35-day retention target.
- **No 12-month monthly archive** is kept for full-database dumps while those dumps may contain Amazon-derived data.
- R2 lifecycle rules, when enabled, must enforce the 35-day ceiling for these operational objects.

### Why not Scheme B for now

**Scheme B — long-term archives excluding Amazon tables** would require a separate backup job or restore-time exclusion list for:

- refresh-token columns
- `amazon_accounts`, `amazon_listings`, `amazon_marketplace_participations`, `amazon_catalog_snapshots`, `amazon_sync_logs`, `amazon_oauth_states`
- `listing_audit_snapshots` where `source='amazon'` or `amazon_listing_id IS NOT NULL`
- `generations` linked to those snapshots

Scheme B is feasible later but increases restore complexity and failure risk. Until an excluded archive pipeline is implemented **and restore-tested**, Listnara will not claim 12-month retention for backups that contain Amazon-derived data.

## Controls required before enabling production Amazon connectivity

1. Refresh tokens must not be recoverable after disconnect/account deletion except within the operational backup window, and token encryption keys must support destruction/rotation without retaining usable refresh tokens in long-term archives.
2. Amazon-derived listing data must not enter any 12-month archive.
3. Operational backups that may contain Amazon-derived data must rotate within **35 days**.
4. Disconnect removes Amazon connection, token, and imported data from active systems immediately.
5. Deleted active-system data may persist in encrypted operational backups until the backup object expires.
6. Backups are not used for normal business queries.
7. Disaster recovery must re-apply disconnect/deletion records after restore when required.

## Privacy alignment

Public Privacy Policy language must reflect:

- current disabled production Amazon integration;
- immediate active-system deletion on disconnect/account deletion;
- possible residual presence in encrypted operational backups until rotation;
- absence of automated long-term Amazon archives until Scheme B is implemented and verified.
