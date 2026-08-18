# Quota & Generation Billing Rules

This document describes MVP quota semantics for SellerAI Copilot generate flows.

## Billing unit

- **Monthly token allowance** (`users.monthly_tokens`)
- **Consumed** (`users.used_tokens`) increases only when a generation **successfully finalizes** (Tx2 commit)
- **Reserved** (`users.reserved_tokens`) holds an upper-bound estimate between Tx1 commit and finalize outcome

## Reservation (Tx1)

Before LLM call, `estimate_reserve_tokens()` reserves:

`rendered_prompt_input + max_output_tokens(type) + safety_margin`

## Successful finalize (Tx2)

`settle_reserved_to_consumed(reserved_amount, consumed_amount)`:

- Releases held reservation
- Adds **actual** `consumed_amount` to `used_tokens`
- If `consumed_amount > reserved_amount` (overage), result is still saved; a structured **warning** is logged

## Post-LLM failure — `GENERATION_FINALIZE_FAILED`

When LLM returns successfully but Tx2 fails (score, payload, product, generation insert, quota settle, commit):

1. Current session is rolled back
2. A **fresh session** reads the request’s committed state
3. If still `processing`, `_attempt_finalize_failure_fresh()` runs with **`bill_tokens=0`**
4. Reserved tokens are **released**; **`used_tokens` is not increased**
5. Request becomes `failed` with `error_code=GENERATION_FINALIZE_FAILED`
6. **No automatic LLM retry**; same idempotency key returns the failed state (409)

> **Rule:** Provider-reported tokens are never billed unless the generation record and Tx2 succeed.
> We do not fabricate usage on finalize failure even when `tokens_used` was returned by the LLM.

## LLM failure (before finalize)

`_finalize_failure(..., bill_tokens=0)` — reservation released, no usage billed.

## Overage & new requests

After overage, `used_tokens + reserved_tokens` may equal or exceed `monthly_tokens`.
The next `reserve_tokens()` call sees `available_tokens <= 0` and returns **`403 QUOTA_EXCEEDED`**.

## Billing period reset

When `reset_date` has passed:

- Reset runs **only if** `reserved_tokens == 0`
- Active processing reservations defer reset until reserved quota is cleared

## API / UI

- `GET /api/v1/user/usage` returns `remaining_tokens = max(0, monthly - used - reserved)`
- Frontend display must use `max(remaining, 0)` (see `frontend/lib/quota.ts`)
