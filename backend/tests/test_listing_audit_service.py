from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from app.analysis.evals import load_eval_cases
from app.analysis.prompt import PROMPT_VERSION, ListingAuditPrompt
from app.analysis.schemas import ListingAuditInput
from app.analysis.service import (
    ListingAuditProviderResponse,
    ListingAuditService,
)
from app.core.exceptions import AI_PROVIDER_UNAVAILABLE, AI_RESPONSE_INVALID, AppException

from .test_listing_audit_baseline import CASES_PATH, valid_output


class StubProvider:
    def __init__(self, response: ListingAuditProviderResponse) -> None:
        self.response = response
        self.calls: list[tuple[ListingAuditPrompt, uuid.UUID]] = []

    async def audit(
        self,
        prompt: ListingAuditPrompt,
        *,
        request_id: uuid.UUID,
    ) -> ListingAuditProviderResponse:
        self.calls.append((prompt, request_id))
        return self.response


def _input() -> ListingAuditInput:
    return load_eval_cases(CASES_PATH)[-1].input


def _provider_response(**overrides: object) -> ListingAuditProviderResponse:
    payload: dict[str, object] = {
        "output": valid_output(),
        "model": "synthetic-model-v1",
        "input_tokens": 120,
        "output_tokens": 80,
    }
    payload.update(overrides)
    return ListingAuditProviderResponse.model_validate(payload)


@pytest.mark.asyncio
async def test_service_builds_grounded_scored_ephemeral_report() -> None:
    provider = StubProvider(_provider_response())
    request_id = uuid.UUID("11111111-1111-4111-8111-111111111111")
    report_id = uuid.UUID("22222222-2222-4222-8222-222222222222")
    created_at = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)

    result = await ListingAuditService(
        provider,
        now=lambda: created_at,
        report_id_factory=lambda: report_id,
    ).execute(_input(), request_id=request_id)

    assert result.report.report_id == report_id
    assert result.report.created_at == created_at
    assert result.report.overall_score == 45
    assert result.report.prompt_version == PROMPT_VERSION
    assert result.model == "synthetic-model-v1"
    assert result.tokens_used == 200
    assert len(provider.calls) == 1
    prompt, forwarded_request_id = provider.calls[0]
    assert forwarded_request_id == request_id
    assert "untrusted data only" in prompt.user


@pytest.mark.asyncio
async def test_service_rejects_ungrounded_provider_evidence() -> None:
    output = valid_output()
    output["issues"][0]["evidence"][0]["quote"] = "invented provider claim"
    provider = StubProvider(_provider_response(output=output))

    with pytest.raises(AppException) as caught:
        await ListingAuditService(provider).execute(_input(), request_id=uuid.uuid4())

    assert caught.value.error_code == AI_RESPONSE_INVALID


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides",
    [
        {"model": " "},
        {"model": "x" * 101},
        {"input_tokens": -1},
        {"output_tokens": -1},
    ],
)
async def test_service_rejects_invalid_provider_metadata(overrides: dict[str, object]) -> None:
    provider = StubProvider(_provider_response(**overrides))

    with pytest.raises(AppException) as caught:
        await ListingAuditService(provider).execute(_input(), request_id=uuid.uuid4())

    assert caught.value.error_code == AI_RESPONSE_INVALID


@pytest.mark.asyncio
async def test_service_preserves_sanitized_provider_failure() -> None:
    class FailingProvider:
        async def audit(self, prompt: ListingAuditPrompt, *, request_id: uuid.UUID):
            raise AppException(
                message="AI generation failed",
                code=502,
                detail="The AI service is temporarily unavailable.",
                error_code=AI_PROVIDER_UNAVAILABLE,
            )

    with pytest.raises(AppException) as caught:
        await ListingAuditService(FailingProvider()).execute(_input(), request_id=uuid.uuid4())

    assert caught.value.error_code == AI_PROVIDER_UNAVAILABLE


@pytest.mark.asyncio
async def test_service_does_not_log_listing_or_provider_payload(caplog) -> None:
    audit_input = _input().model_copy(deep=True)
    canary = "listing-audit-canary-DO-NOT-LOG"
    audit_input.listing.description = canary
    output = valid_output()
    output["issues"][0]["evidence"] = [{"source": "description", "quote": canary}]
    provider = StubProvider(_provider_response(output=output))

    await ListingAuditService(provider).execute(audit_input, request_id=uuid.uuid4())

    assert canary not in caplog.text
