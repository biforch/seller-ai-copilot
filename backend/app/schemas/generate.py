
from pydantic import BaseModel, Field, field_validator

from app.schemas.common_fields import (
    ADVANTAGE_ITEM_MAX,
    ADVANTAGES_MAX_COUNT,
    AnalyzeDescriptionField,
    CategoryField,
    ListingTitleField,
    MarketField,
    NameField,
    PlatformField,
    ProductIdField,
    ProjectIdField,
    TargetCustomerField,
)


class GenerateListingRequest(BaseModel):
    project_id: ProjectIdField
    product_id: ProductIdField | None = None
    name: NameField
    category: CategoryField
    market: MarketField = "USA"
    platform: PlatformField = "Amazon"
    target_customer: TargetCustomerField = None
    advantages: list[str] | None = Field(default=None, max_length=ADVANTAGES_MAX_COUNT)

    @field_validator("advantages")
    @classmethod
    def validate_advantages(cls, advantages: list[str] | None) -> list[str] | None:
        if advantages is None:
            return None
        cleaned: list[str] = []
        for item in advantages:
            text = item.strip()
            if not text:
                raise ValueError("advantage must not be blank")
            if len(text) > ADVANTAGE_ITEM_MAX:
                raise ValueError(f"advantage exceeds {ADVANTAGE_ITEM_MAX} characters")
            cleaned.append(text)
        return cleaned


class GenerateListingResponse(BaseModel):
    project_id: str
    product_id: str
    title: str
    bullets: list[str]
    description: str
    keywords: list[str]
    tokens_used: int


class AnalyzeRequest(BaseModel):
    project_id: ProjectIdField
    title: ListingTitleField
    reviews: int = Field(ge=0, le=50_000_000)
    rating: float = Field(ge=0.0, le=5.0)
    description: AnalyzeDescriptionField


class AnalyzeResponse(BaseModel):
    project_id: str
    strengths: list[str]
    weaknesses: list[str]
    opportunities: list[str]
    tokens_used: int


class GenerationHistoryItem(BaseModel):
    id: str
    type: str
    project_id: str | None = None
    product_id: str | None = None
    input: dict
    output: dict
    tokens_used: int
    created_at: str
