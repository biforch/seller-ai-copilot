"""Listing snapshot and review decision schemas for the version system."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.ai_output import ListingAIOutput
from app.schemas.common import ApiResponse
from app.schemas.common_fields import LISTING_BULLET_MAX, LISTING_BULLETS_COUNT
from app.schemas.pagination import PaginationMeta

LISTING_SNAPSHOT_TITLE_MIN = 1
LISTING_SNAPSHOT_TITLE_MAX = 500
LISTING_SNAPSHOT_BULLETS_COUNT = LISTING_BULLETS_COUNT
LISTING_SNAPSHOT_BULLET_MAX = LISTING_BULLET_MAX
LISTING_SNAPSHOT_DESCRIPTION_MAX = 10_000
LISTING_SNAPSHOT_KEYWORDS_MIN = 1
LISTING_SNAPSHOT_KEYWORDS_MAX = 20
LISTING_SNAPSHOT_KEYWORD_MAX = 100

FieldDecisionValue = Literal["accept", "reject", "pending"]
LISTING_FIELDS = ("title", "bullets", "description", "backend_keywords")


def _strip_non_empty(value: Any) -> str:
    if not isinstance(value, str):
        raise TypeError("string required")
    stripped = value.strip()
    if not stripped:
        raise ValueError("must not be blank")
    return stripped


def _normalize_keywords(values: list[str]) -> list[str]:
    seen: set[str] = set()
    normalized: list[str] = []
    for raw in values:
        if not isinstance(raw, str):
            raise TypeError("keyword must be a string")
        keyword = raw.strip()
        if not keyword:
            continue
        if len(keyword) > LISTING_SNAPSHOT_KEYWORD_MAX:
            raise ValueError(
                f"each keyword must be at most {LISTING_SNAPSHOT_KEYWORD_MAX} characters"
            )
        lowered = keyword.casefold()
        if lowered in seen:
            continue
        seen.add(lowered)
        normalized.append(keyword)
    return normalized


class ListingSnapshot(BaseModel):
    """Canonical immutable listing content for versions and proposals."""

    model_config = ConfigDict(extra="forbid")

    title: Annotated[str, Field(min_length=LISTING_SNAPSHOT_TITLE_MIN, max_length=LISTING_SNAPSHOT_TITLE_MAX)]
    bullets: list[str]
    description: Annotated[str, Field(min_length=1, max_length=LISTING_SNAPSHOT_DESCRIPTION_MAX)]
    backend_keywords: list[str]

    @field_validator("title", "description", mode="before")
    @classmethod
    def strip_required_strings(cls, value: Any) -> str:
        return _strip_non_empty(value)

    @field_validator("bullets", mode="before")
    @classmethod
    def validate_bullets(cls, value: Any) -> list[str]:
        if not isinstance(value, list):
            raise TypeError("bullets must be a list")
        if len(value) != LISTING_SNAPSHOT_BULLETS_COUNT:
            raise ValueError(f"bullets must contain exactly {LISTING_SNAPSHOT_BULLETS_COUNT} items")
        normalized: list[str] = []
        for item in value:
            if not isinstance(item, str):
                raise TypeError("each bullet must be a string")
            bullet = item.strip()
            if not bullet:
                raise ValueError("bullets must not contain blank entries")
            if len(bullet) > LISTING_SNAPSHOT_BULLET_MAX:
                raise ValueError(
                    f"each bullet must be at most {LISTING_SNAPSHOT_BULLET_MAX} characters"
                )
            normalized.append(bullet)
        return normalized

    @field_validator("backend_keywords", mode="before")
    @classmethod
    def validate_backend_keywords(cls, value: Any) -> list[str]:
        if not isinstance(value, list):
            raise TypeError("backend_keywords must be a list")
        normalized = _normalize_keywords(value)
        if len(normalized) < LISTING_SNAPSHOT_KEYWORDS_MIN:
            raise ValueError(
                f"backend_keywords must contain at least {LISTING_SNAPSHOT_KEYWORDS_MIN} item"
            )
        if len(normalized) > LISTING_SNAPSHOT_KEYWORDS_MAX:
            raise ValueError(
                f"backend_keywords must contain at most {LISTING_SNAPSHOT_KEYWORDS_MAX} items"
            )
        return normalized

    def canonical_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class FieldDecisions(BaseModel):
    """Per-field review decisions for a listing proposal."""

    model_config = ConfigDict(extra="forbid")

    title: FieldDecisionValue
    bullets: FieldDecisionValue
    description: FieldDecisionValue
    backend_keywords: FieldDecisionValue

    @model_validator(mode="after")
    def ensure_all_fields_present(self) -> FieldDecisions:
        for field_name in LISTING_FIELDS:
            if getattr(self, field_name) not in ("accept", "reject", "pending"):
                raise ValueError(f"{field_name} must be accept, reject, or pending")
        return self

    def to_json(self) -> dict[str, str]:
        return self.model_dump(mode="json")

    def has_pending(self) -> bool:
        return any(getattr(self, field_name) == "pending" for field_name in LISTING_FIELDS)


def default_pending_field_decisions() -> FieldDecisions:
    """Factory for fresh all-pending decisions (no shared mutable default)."""
    return FieldDecisions(
        title="pending",
        bullets="pending",
        description="pending",
        backend_keywords="pending",
    )


def listing_snapshot_from_dict(data: dict[str, Any]) -> ListingSnapshot:
    """Validate arbitrary JSON/dict into a ListingSnapshot."""
    return ListingSnapshot.model_validate(data)


def listing_snapshot_from_ai_output(output: ListingAIOutput) -> ListingSnapshot:
    """Convert validated ListingAIOutput into a ListingSnapshot."""
    return ListingSnapshot(
        title=output.title,
        bullets=output.bullets,
        description=output.description,
        backend_keywords=output.keywords,
    )


class ImportListingRequest(ListingSnapshot):
    """Request body for manual listing import; reuses ListingSnapshot validation."""


class ListingVersionResponse(BaseModel):
    """Public listing version fields exposed by the REST API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    product_id: uuid.UUID
    version_number: int
    source: str
    title: str
    bullets: list[str]
    description: str
    backend_keywords: list[str]
    marketplace: str
    language: str
    generation_id: uuid.UUID | None
    parent_version_id: uuid.UUID | None
    created_by: uuid.UUID | None
    created_at: datetime
    is_current: bool

    @classmethod
    def from_version(
        cls,
        version: Any,
        *,
        is_current: bool,
    ) -> ListingVersionResponse:
        return cls(
            id=version.id,
            product_id=version.product_id,
            version_number=version.version_number,
            source=version.source,
            title=version.title,
            bullets=version.bullets,
            description=version.description,
            backend_keywords=version.backend_keywords,
            marketplace=version.marketplace,
            language=version.language,
            generation_id=version.generation_id,
            parent_version_id=version.parent_version_id,
            created_by=version.created_by,
            created_at=version.created_at,
            is_current=is_current,
        )


class ListingScoreResponse(BaseModel):
    """Quality score dimensions for a listing version."""

    overall: int
    title_seo: int
    keyword_coverage: int
    benefit_clarity: int
    conversion_potential: int


class ImportListingResponse(BaseModel):
    version: ListingVersionResponse
    replay: bool
    is_first: bool


class CurrentListingResponse(BaseModel):
    version: ListingVersionResponse
    score: ListingScoreResponse | None


class ListingVersionPageResponse(BaseModel):
    items: list[ListingVersionResponse]
    pagination: PaginationMeta


ImportListingApiResponse = ApiResponse[ImportListingResponse]
CurrentListingApiResponse = ApiResponse[CurrentListingResponse]
ListingVersionPageApiResponse = ApiResponse[ListingVersionPageResponse]


class ListingProposalSummaryResponse(BaseModel):
    """Public proposal summary included in listing generation responses."""

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    status: str
    revision: int
    base_version_id: uuid.UUID | None


class ListingProposalResponse(BaseModel):
    """Public listing proposal fields exposed by the REST API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    product_id: uuid.UUID
    base_version_id: uuid.UUID | None
    candidate_snapshot: ListingSnapshot
    field_decisions: FieldDecisions
    status: str
    revision: int
    generation_request_id: uuid.UUID | None
    approved_version_id: uuid.UUID | None
    reviewed_by: uuid.UUID | None
    reviewed_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_proposal(cls, proposal: Any) -> ListingProposalResponse:
        return cls(
            id=proposal.id,
            product_id=proposal.product_id,
            base_version_id=proposal.base_version_id,
            candidate_snapshot=ListingSnapshot.model_validate(proposal.candidate_snapshot),
            field_decisions=FieldDecisions.model_validate(proposal.field_decisions),
            status=proposal.status,
            revision=proposal.revision,
            generation_request_id=proposal.generation_request_id,
            approved_version_id=proposal.approved_version_id,
            reviewed_by=proposal.reviewed_by,
            reviewed_at=proposal.reviewed_at,
            created_at=proposal.created_at,
            updated_at=proposal.updated_at,
        )


class ListingFieldDiffEntry(BaseModel):
    base: str | list[str] | None
    candidate: str | list[str]
    changed: bool


class ListingProposalDiffResponse(BaseModel):
    title: ListingFieldDiffEntry
    bullets: ListingFieldDiffEntry
    description: ListingFieldDiffEntry
    backend_keywords: ListingFieldDiffEntry

    @classmethod
    def from_diff(cls, diff: dict[str, dict[str, Any]]) -> ListingProposalDiffResponse:
        return cls.model_validate(diff)


class ListingProposalDetailResponse(BaseModel):
    proposal: ListingProposalResponse
    base_version: ListingVersionResponse | None
    approved_version: ListingVersionResponse | None
    diff: ListingProposalDiffResponse


class PatchProposalDecisionsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: Annotated[int, Field(ge=1)]
    decisions: FieldDecisions


class PatchProposalDecisionsResponse(BaseModel):
    proposal: ListingProposalResponse


class ApproveProposalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: Annotated[int, Field(ge=1)]
    decisions: FieldDecisions | None = None


class ApproveProposalResponse(BaseModel):
    proposal: ListingProposalResponse
    approved_version: ListingVersionResponse
    replay: bool


class RejectProposalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: Annotated[int, Field(ge=1)]


class RejectProposalResponse(BaseModel):
    proposal: ListingProposalResponse
    replay: bool


ListingProposalDetailApiResponse = ApiResponse[ListingProposalDetailResponse]
PatchProposalDecisionsApiResponse = ApiResponse[PatchProposalDecisionsResponse]
ApproveProposalApiResponse = ApiResponse[ApproveProposalResponse]
RejectProposalApiResponse = ApiResponse[RejectProposalResponse]


class ListingProposalListItemResponse(BaseModel):
    """Lightweight listing proposal fields for paginated list responses."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    product_id: uuid.UUID
    base_version_id: uuid.UUID | None
    approved_version_id: uuid.UUID | None
    status: str
    revision: int
    candidate_title: str
    generation_request_id: uuid.UUID | None
    reviewed_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_proposal(cls, proposal: Any) -> ListingProposalListItemResponse:
        snapshot = ListingSnapshot.model_validate(proposal.candidate_snapshot)
        return cls(
            id=proposal.id,
            product_id=proposal.product_id,
            base_version_id=proposal.base_version_id,
            approved_version_id=proposal.approved_version_id,
            status=proposal.status,
            revision=proposal.revision,
            candidate_title=snapshot.title,
            generation_request_id=proposal.generation_request_id,
            reviewed_at=proposal.reviewed_at,
            created_at=proposal.created_at,
            updated_at=proposal.updated_at,
        )


class ListingProposalPageResponse(BaseModel):
    items: list[ListingProposalListItemResponse]
    pagination: PaginationMeta


ListingProposalPageApiResponse = ApiResponse[ListingProposalPageResponse]
