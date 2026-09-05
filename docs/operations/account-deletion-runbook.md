# Account Deletion Runbook

## Scope

This runbook covers verified account-deletion requests sent to `support@listnara.com`. Listnara does not currently expose a self-service account-deletion API. Deletions are performed manually by an operator using the administrative CLI after identity verification.

## SLA

- Delete user-owned data from **active application systems** within **30 days** of a verified request.
- Record the request date, completion date, and non-sensitive outcome in the operator ticket.

## Preconditions

- Request received from the account email address, or identity verified through an equivalent approved process.
- Operator has shell access to the production backend environment.
- Production database credentials are available through `.env.vultr` on the host; never paste secrets into tickets or chat.

## Procedure

1. Record the support ticket ID and request date in the operator log.
2. Identify the account by email or user UUID from the internal admin/support tooling or database lookup by email only.
3. Run a dry run:

```bash
docker compose -p listnara_prod -f docker-compose.vultr.yml exec backend \
  python scripts/admin_delete_user_account.py \
  --email "user@example.com" \
  --request-reference "support-ticket-id" \
  --request-date "2026-09-05" \
  --dry-run
```

4. Confirm the dry-run output shows the expected `user_id` and `amazon_accounts_removed` count.
5. Execute the deletion:

```bash
docker compose -p listnara_prod -f docker-compose.vultr.yml exec backend \
  python scripts/admin_delete_user_account.py \
  --email "user@example.com" \
  --request-reference "support-ticket-id" \
  --request-date "2026-09-05" \
  --confirm DELETE
```

6. Capture the single-line `user_account_deletion_result` output in the ticket. This line intentionally excludes tokens, listing content, and refresh-token material.
7. If the user had connected Amazon accounts, remind them to revoke Listnara in Seller Central if they had previously authorized access.

## What the command deletes from active systems

- User row and cascaded owned records (projects, products, sessions, audits, subscriptions, analytics events, and related rows).
- Amazon connections through the same disconnect path used by the product API: refresh tokens, imported marketplace/listing/catalog data, Amazon-linked audit snapshots, and linked listing-audit generations.

## What it does not do

- It does not purge encrypted operational backup objects. See `docs/security/amazon-backup-retention-policy.md`.
- It does not revoke Amazon Seller Central authorization; the user must do that separately.

## Local verification (repeatable)

From the repository root with the test database running:

```bash
cd backend
python -m pytest tests/test_user_account_deletion_service.py -q
```

## Rollback

Account deletion is intentionally irreversible in active systems. Recovery is limited to disaster-recovery restore from an encrypted backup, followed by re-applying deletion records for any users who requested erasure after the backup snapshot.
