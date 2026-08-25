"""Cross-field validation that JSON Schema alone cannot express."""

from __future__ import annotations

import re

from app.analysis.schemas import EvidenceSource, ListingAuditInput, ListingAuditLLMOutput


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def _source_values(source: EvidenceSource, audit_input: ListingAuditInput) -> list[str]:
    if source == EvidenceSource.TITLE:
        return [audit_input.listing.title]
    if source == EvidenceSource.DESCRIPTION:
        return [audit_input.listing.description]
    if source == EvidenceSource.COMPETITOR_LISTING:
        return [audit_input.competitor_listing] if audit_input.competitor_listing else []
    if source == EvidenceSource.CUSTOMER_REVIEW:
        return audit_input.customer_reviews
    if source.value.startswith("bullet_"):
        index = int(source.value.removeprefix("bullet_")) - 1
        if 0 <= index < len(audit_input.listing.bullets):
            return [audit_input.listing.bullets[index]]
    return []


def validate_evidence_grounding(
    audit_input: ListingAuditInput,
    output: ListingAuditLLMOutput,
) -> None:
    """Reject evidence quotes that are not present in their declared input source."""
    for issue in output.issues:
        for evidence in issue.evidence:
            quote = _normalize(evidence.quote)
            sources = (_normalize(value) for value in _source_values(evidence.source, audit_input))
            if not quote or not any(quote in source for source in sources):
                raise ValueError(
                    f"{issue.id} evidence quote is not grounded in {evidence.source.value}"
                )
