"""Provider-neutral execution boundary for an internal Listing Audit."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from pydantic import ValidationError

from app.analysis.grounding import validate_evidence_grounding
from app.analysis.prompt import ListingAuditPrompt, render_listing_audit_prompt
from app.analysis.schemas import (
    ListingAuditInput,
    ListingAuditLLMOutput,
    ListingAuditReport,
    StrictModel,
)
from app.analysis.scoring import calculate_overall_score
from app.core.exceptions import ai_response_invalid_exception


class ListingAuditProviderResponse(StrictModel):
    """Raw provider result plus accounting metadata needed by the B1 executor."""

    output: Mapping[str, object]
    model: str
    input_tokens: int = 0
    output_tokens: int = 0


class ListingAuditProvider(Protocol):
    async def audit(
        self,
        prompt: ListingAuditPrompt,
        *,
        request_id: uuid.UUID,
    ) -> ListingAuditProviderResponse: ...


@dataclass(frozen=True)
class ListingAuditExecutionResult:
    report: ListingAuditReport
    model: str
    input_tokens: int
    output_tokens: int

    @property
    def tokens_used(self) -> int:
        return self.input_tokens + self.output_tokens


class ListingAuditService:
    """Validate, ground, and score one ephemeral registered-user audit.

    B1a deliberately has no HTTP route or persistence. Idempotency, quota
    reservation, and authenticated API wiring are added by the B1 executor in
    the next batch, without weakening this validation boundary.
    """

    def __init__(
        self,
        provider: ListingAuditProvider,
        *,
        now: Callable[[], datetime] | None = None,
        report_id_factory: Callable[[], uuid.UUID] | None = None,
    ) -> None:
        self._provider = provider
        self._now = now or (lambda: datetime.now(UTC))
        self._report_id_factory = report_id_factory or uuid.uuid4

    async def execute(
        self,
        audit_input: ListingAuditInput,
        *,
        request_id: uuid.UUID,
    ) -> ListingAuditExecutionResult:
        prompt = render_listing_audit_prompt(audit_input)
        provider_response = await self._provider.audit(prompt, request_id=request_id)

        try:
            response = ListingAuditProviderResponse.model_validate(provider_response)
            if not response.model.strip() or len(response.model) > 100:
                raise ValueError("provider model identifier is invalid")
            if response.input_tokens < 0 or response.output_tokens < 0:
                raise ValueError("provider token counts must be non-negative")

            output = ListingAuditLLMOutput.model_validate(response.output)
            validate_evidence_grounding(audit_input, output)
        except (ValidationError, ValueError, TypeError) as exc:
            raise ai_response_invalid_exception(exc) from exc

        report = ListingAuditReport(
            report_id=self._report_id_factory(),
            overall_score=calculate_overall_score(output.dimension_scores),
            result=output,
            created_at=self._now(),
        )
        return ListingAuditExecutionResult(
            report=report,
            model=response.model,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
        )
