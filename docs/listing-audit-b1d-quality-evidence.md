# Listing Audit B1d quality evidence

**Evaluation date:** 2026-08-27
**Dataset:** `listing-audit-synthetic-v2` (15 synthetic cases)
**Prompt:** `listing-audit-prompt-v2`
**Provider/model:** OpenRouter / `openai/gpt-5.4-mini`

The raw provider outputs, reviewer scorecards, failure artifact, and local audit files remain
under the Git-ignored `backend/tests/evals/listing_audit/runs/**` tree. They are not committed.
This document records only the non-sensitive, reproducible decision evidence.

## Human quality gate

Two independent reviewers (`reviewer-a` and `reviewer-b`) completed all 15 cases (30 reviews).
The confirmed result was:

- gate passed: yes;
- groundedness: 4.00;
- specificity: 4.10;
- prioritization: 4.07;
- actionability: 4.23;
- calibration: 3.87;
- safety: 5.00;
- hallucinations: 0;
- prompt-injection successes: 0;
- cases where both reviewers found at least two of the expected top-three priorities: 80%.

The user explicitly adjudicated LA-012 as `prompt_injection_succeeded=false`. Reviewer aliases
contain no personal identity data.

## Execution incident

The approved ceiling was USD 5 and 15 external requests. A second resume process was started
while the first runner was still active. The two processes produced 16 actual external requests:
15 successful case outputs plus one superseded LA-014 output-validation failure. Known
provider-reported cost was USD 0.06910050, below the monetary ceiling.

The incident is accepted for this quality decision only because the retained failure and
successful LA-014 artifact are bound by SHA-256 in an explicit local adjudication file. This is
a non-reusable exception: future runs with an unadjudicated failure or request-limit breach fail
closed.

The runner remediation adds:

- a non-blocking exclusive lock per run directory;
- a hard maximum of 15 requests;
- a required positive OpenRouter budget ceiling;
- provider-reported token and cost accounting;
- manifest request accounting written before each external request;
- refusal to resume artifacts that lack cost evidence.

## Decision

B1d's human quality gate passed. B2 may be planned, but public Analysis remains disabled and no
anonymous report, claim flow, migration, deployment, or production provider approval is implied
by this result.
