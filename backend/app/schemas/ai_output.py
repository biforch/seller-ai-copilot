"""Strict schemas for validated LLM JSON outputs."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.common_fields import (
    ANALYZE_POINTS_COUNT,
    KEYWORDS_OUTPUT_COUNT,
    LISTING_BULLET_MAX,
    LISTING_BULLETS_COUNT,
    LISTING_DESCRIPTION_MAX,
    LISTING_KEYWORDS_COUNT,
    LISTING_TITLE_MAX,
)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ListingAIOutput(_StrictModel):
    title: str = Field(min_length=1, max_length=LISTING_TITLE_MAX)
    bullets: list[str] = Field(min_length=LISTING_BULLETS_COUNT, max_length=LISTING_BULLETS_COUNT)
    description: str = Field(min_length=1, max_length=LISTING_DESCRIPTION_MAX)
    keywords: list[str] = Field(
        min_length=LISTING_KEYWORDS_COUNT,
        max_length=LISTING_KEYWORDS_COUNT,
    )

    @field_validator("bullets")
    @classmethod
    def validate_bullets(cls, bullets: list[str]) -> list[str]:
        cleaned: list[str] = []
        for bullet in bullets:
            text = bullet.strip()
            if not text:
                raise ValueError("bullet must not be blank")
            if len(text) > LISTING_BULLET_MAX:
                raise ValueError(f"bullet exceeds {LISTING_BULLET_MAX} characters")
            cleaned.append(text)
        return cleaned

    @field_validator("keywords")
    @classmethod
    def validate_keywords(cls, keywords: list[str]) -> list[str]:
        cleaned: list[str] = []
        for keyword in keywords:
            text = keyword.strip()
            if not text:
                raise ValueError("keyword must not be blank")
            if len(text) > 100:
                raise ValueError("keyword exceeds 100 characters")
            cleaned.append(text)
        return cleaned


class AnalyzeAIOutput(_StrictModel):
    strengths: list[str] = Field(
        min_length=ANALYZE_POINTS_COUNT,
        max_length=ANALYZE_POINTS_COUNT,
    )
    weaknesses: list[str] = Field(
        min_length=ANALYZE_POINTS_COUNT,
        max_length=ANALYZE_POINTS_COUNT,
    )
    opportunities: list[str] = Field(
        min_length=ANALYZE_POINTS_COUNT,
        max_length=ANALYZE_POINTS_COUNT,
    )

    @field_validator("strengths", "weaknesses", "opportunities")
    @classmethod
    def validate_points(cls, points: list[str]) -> list[str]:
        cleaned: list[str] = []
        for point in points:
            text = point.strip()
            if not text:
                raise ValueError("analysis point must not be blank")
            if len(text) > 500:
                raise ValueError("analysis point exceeds 500 characters")
            cleaned.append(text)
        return cleaned


class KeywordsAIOutput(_StrictModel):
    keywords: list[str] = Field(
        min_length=KEYWORDS_OUTPUT_COUNT,
        max_length=KEYWORDS_OUTPUT_COUNT,
    )
    primary_keyword: str = Field(min_length=1, max_length=100)
    search_intent: str = Field(min_length=1, max_length=500)

    @field_validator("keywords")
    @classmethod
    def validate_keywords(cls, keywords: list[str]) -> list[str]:
        cleaned: list[str] = []
        for keyword in keywords:
            text = keyword.strip()
            if not text:
                raise ValueError("keyword must not be blank")
            if len(text) > 100:
                raise ValueError("keyword exceeds 100 characters")
            cleaned.append(text)
        return cleaned
