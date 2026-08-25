"""Strict contracts for the Listing Audit quality baseline."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Marketplace(StrEnum):
    US = "US"
    CA = "CA"
    MX = "MX"
    UK = "UK"
    DE = "DE"
    FR = "FR"
    IT = "IT"
    ES = "ES"
    JP = "JP"
    AU = "AU"


class ListingText(StrictModel):
    title: str = Field(min_length=1, max_length=300)
    bullets: list[str] = Field(min_length=1, max_length=5)
    description: str = Field(min_length=1, max_length=5_000)

    @field_validator("bullets")
    @classmethod
    def validate_bullets(cls, bullets: list[str]) -> list[str]:
        cleaned: list[str] = []
        for bullet in bullets:
            text = bullet.strip()
            if not text:
                raise ValueError("bullet must not be blank")
            if len(text) > 1_000:
                raise ValueError("bullet exceeds 1000 characters")
            cleaned.append(text)
        return cleaned


class ListingAuditInput(StrictModel):
    product_id: uuid.UUID | None = None
    marketplace: Marketplace = Marketplace.US
    language: str = Field(default="en-US", min_length=2, max_length=20, pattern=r"^[A-Za-z]{2,3}(?:-[A-Za-z]{2,4})?$")
    listing: ListingText
    competitor_listing: str | None = Field(default=None, max_length=8_000)
    customer_reviews: list[str] = Field(default_factory=list, max_length=30)

    @field_validator("competitor_listing")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        return text or None

    @field_validator("customer_reviews")
    @classmethod
    def validate_reviews(cls, reviews: list[str]) -> list[str]:
        cleaned: list[str] = []
        for review in reviews:
            text = review.strip()
            if not text:
                raise ValueError("customer review must not be blank")
            if len(text) > 2_000:
                raise ValueError("customer review exceeds 2000 characters")
            cleaned.append(text)
        return cleaned


class DimensionName(StrEnum):
    POSITIONING = "positioning"
    BUYER_CLARITY = "buyer_clarity"
    INFORMATION_QUALITY = "information_quality"
    CONVERSION_READINESS = "conversion_readiness"
    DISCOVERABILITY = "discoverability"


class IssueCategory(StrEnum):
    POSITIONING = "positioning"
    BUYER_CLARITY = "buyer_clarity"
    INFORMATION_QUALITY = "information_quality"
    CONVERSION = "conversion"
    DISCOVERABILITY = "discoverability"
    COMPLIANCE_RISK = "compliance_risk"


class Severity(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Effort(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class EvidenceSource(StrEnum):
    TITLE = "title"
    BULLET_1 = "bullet_1"
    BULLET_2 = "bullet_2"
    BULLET_3 = "bullet_3"
    BULLET_4 = "bullet_4"
    BULLET_5 = "bullet_5"
    DESCRIPTION = "description"
    COMPETITOR_LISTING = "competitor_listing"
    CUSTOMER_REVIEW = "customer_review"


class Evidence(StrictModel):
    source: EvidenceSource
    quote: str = Field(min_length=1, max_length=240)


class DimensionScore(StrictModel):
    score: int = Field(ge=0, le=100)
    rationale: str = Field(min_length=1, max_length=400)


class DimensionScores(StrictModel):
    positioning: DimensionScore
    buyer_clarity: DimensionScore
    information_quality: DimensionScore
    conversion_readiness: DimensionScore
    discoverability: DimensionScore


class AuditIssue(StrictModel):
    id: str = Field(pattern=r"^ISSUE-[1-8]$")
    category: IssueCategory
    severity: Severity
    problem: str = Field(min_length=1, max_length=220)
    reason: str = Field(min_length=1, max_length=400)
    impact: str = Field(min_length=1, max_length=400)
    evidence: list[Evidence] = Field(min_length=1, max_length=3)


class PriorityAction(StrictModel):
    rank: int = Field(ge=1, le=3)
    issue_ids: list[str] = Field(min_length=1, max_length=3)
    action: str = Field(min_length=1, max_length=400)
    why_now: str = Field(min_length=1, max_length=300)
    expected_effect: str = Field(min_length=1, max_length=300)
    effort: Effort

    @field_validator("issue_ids")
    @classmethod
    def validate_issue_ids(cls, issue_ids: list[str]) -> list[str]:
        if len(issue_ids) != len(set(issue_ids)):
            raise ValueError("issue_ids must be unique")
        for issue_id in issue_ids:
            if not issue_id.startswith("ISSUE-") or not issue_id[6:].isdigit():
                raise ValueError("issue_ids must use ISSUE-N format")
        return issue_ids


class ListingAuditLLMOutput(StrictModel):
    dimension_scores: DimensionScores
    issues: list[AuditIssue] = Field(min_length=1, max_length=8)
    priority_actions: list[PriorityAction] = Field(min_length=1, max_length=3)
    limitations: list[str] = Field(max_length=5)

    @field_validator("limitations")
    @classmethod
    def validate_limitations(cls, limitations: list[str]) -> list[str]:
        for limitation in limitations:
            if not limitation.strip():
                raise ValueError("limitation must not be blank")
            if len(limitation) > 300:
                raise ValueError("limitation exceeds 300 characters")
        return limitations

    @model_validator(mode="after")
    def validate_references(self) -> ListingAuditLLMOutput:
        issue_ids = [issue.id for issue in self.issues]
        if len(issue_ids) != len(set(issue_ids)):
            raise ValueError("issue ids must be unique")

        expected_ranks = list(range(1, len(self.priority_actions) + 1))
        actual_ranks = [action.rank for action in self.priority_actions]
        if actual_ranks != expected_ranks:
            raise ValueError("priority action ranks must be consecutive and ordered")

        known = set(issue_ids)
        referenced: set[str] = set()
        for action in self.priority_actions:
            unknown = set(action.issue_ids) - known
            if unknown:
                raise ValueError(f"priority action references unknown issues: {sorted(unknown)}")
            referenced.update(action.issue_ids)
        if not referenced:
            raise ValueError("priority actions must reference at least one issue")
        return self


class ListingAuditReport(StrictModel):
    report_id: uuid.UUID
    report_type: str = Field(default="listing_audit", pattern=r"^listing_audit$")
    schema_version: str = Field(default="listing-audit-schema-v1", pattern=r"^listing-audit-schema-v1$")
    prompt_version: str = Field(default="listing-audit-prompt-v2", pattern=r"^listing-audit-prompt-v2$")
    overall_score: int = Field(ge=0, le=100)
    result: ListingAuditLLMOutput
    created_at: datetime
