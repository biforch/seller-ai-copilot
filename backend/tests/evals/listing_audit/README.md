# Listing Audit Sprint 0.5 baseline

This directory contains synthetic evaluation data only. Do not add credentials,
private seller data, or production Listing content.

## Gate order

1. Validate all 15 inputs locally.
2. Run all cases against one exact model at temperature 0.1 or 0.2, unless a
   documented model-compatibility exception requires omitting temperature.
3. Have two reviewers independently score every output.
4. Iterate the Prompt version if the gate fails, then create a new run directory.
5. Summarize the completed run. Business API work remains blocked until the summary passes.

## Local contract validation

```bash
cd backend
PYTHONPATH=. python3 scripts/run_listing_audit_baseline.py --validate-only
python3 -m pytest tests/test_listing_audit_baseline.py -q
```

## Approved-model run

Configure the API credential outside chat in the approved secret environment.
Do not paste it into the repository, terminal transcript, Cursor, or a run artifact.

```bash
cd backend
PYTHONPATH=. python3 scripts/run_listing_audit_baseline.py \
  --model '<exact-approved-model-id>' \
  --temperature 0.2 \
  --confirm-external-call B1D-15-SYNTHETIC-CASES \
  --max-requests 15 \
  --max-budget-usd '<approved-positive-budget>' \
  --output-dir 'tests/evals/listing_audit/runs/<prompt-model-run-id>'
```

The runner deliberately has no user-supplied base URL or fallback-model option.
OpenAI mode uses the SDK default endpoint, Structured Outputs, and `store=false`.

For a provider-neutral OpenRouter baseline, configure `OPENROUTER_API_KEY`
outside chat and use an exact OpenRouter `provider/model` slug:

```bash
cd backend
PYTHONPATH=. python3 scripts/run_listing_audit_baseline.py \
  --provider openrouter \
  --model '<exact-openrouter-model-id>' \
  --temperature null \
  --confirm-external-call B1D-15-SYNTHETIC-CASES \
  --max-requests 15 \
  --max-budget-usd '<approved-positive-budget>' \
  --output-dir 'tests/evals/listing_audit/runs/<provider-model-run-id>'
```

Online OpenRouter runs must also provide `--max-requests` (at most 15) and a positive
`--max-budget-usd`. The runner exclusively locks each run directory and requires
provider-reported cost accounting; concurrent writers, unbounded spend, and resumes without
usage evidence fail closed.

OpenRouter mode uses its fixed official API URL and sends `store=false`,
`zdr=true`, `data_collection=deny`, `require_parameters=true`, and
`allow_fallbacks=false`. Artifacts record the gateway provider, requested exact
model ID, and response model ID. This quality baseline is not a production
provider or model approval.

For `openai/gpt-5.5`, `--temperature null` omits the unsupported request
parameter and records `temperature=null` with
`temperature_mode=model_compatibility_exception` in every artifact and the
manifest. All routing and privacy constraints remain enabled.

Runs are safely resumable. An existing case artifact is skipped only after its
run metadata, schema, grounded evidence, and deterministic score have been
validated. Invalid or incompatible artifacts are never overwritten. Schema or
grounding failures write only non-content failure metadata (including a response
hash and character count); the rejected response text is not retained.

The confirmation value is deliberately non-secret and prevents accidental calls;
use it only after the exact provider/model and a maximum spend have been approved.
The SDK timeout is fixed at 120 seconds with automatic retries disabled, so one
invocation can make at most one provider request for each of the 15 synthetic
cases. Output is restricted to the ignored `runs/` tree with directory mode 0700
and JSON artifact mode 0600. Existing failure evidence is never overwritten.

The manifest and every successful artifact also record the synthetic evaluation
dataset version and exact cases-file SHA-256 digest. A changed case set therefore
cannot be resumed into an older run. Instruction-overriding behavior is tested
with benign score/output-format manipulation in LA-012. Sensitive-exfiltration
inducements belong in a separate refusal/safety suite and are not used as the
Structured Output conformance case.

## Human review

Copy the object from `human_review_template.json` twice into each case
artifact's `human_scores` array. Use reviewer aliases. Reviewers must not see
each other's scores until both reviews are recorded.

The six 1–5 dimensions are groundedness, specificity, prioritization,
actionability, calibration, and safety. Record whether any hallucination or
successful prompt injection occurred, and count how many of the expected Top 3
priorities were covered.

## Gate summary

```bash
cd backend
PYTHONPATH=. python3 scripts/summarize_listing_audit_baseline.py \
  'tests/evals/listing_audit/runs/<prompt-model-run-id>' \
  --output 'tests/evals/listing_audit/runs/<prompt-model-run-id>/summary.json'
```

Exit code 0 means the confirmed gate passed. Any other result blocks business
API implementation and requires review or a new Prompt version. The entire
`runs/` tree is local evidence, is ignored by Git, and must never be committed.
Transfer approved evidence only through a separately authorized, access-controlled
artifact channel; never copy provider outputs into source-control documentation.
