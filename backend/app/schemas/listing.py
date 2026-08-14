"""Listing snapshot and review decision schemas for the version system."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.ai_output import ListingAIOutput
from app.schemas.common_fields import LISTING_BULLET_MAX, LISTING_BULLETS_COUNT

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
