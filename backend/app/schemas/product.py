
from pydantic import BaseModel, Field, field_validator

from app.schemas.common_fields import (
    ADVANTAGE_ITEM_MAX,
    ADVANTAGES_MAX_COUNT,
    MarketField,
    NameField,
    OptionalCategoryField,
    PlatformField,
    ProjectIdField,
    TargetCustomerField,
)


class CreateProductRequest(BaseModel):
    project_id: ProjectIdField
    name: NameField
    category: OptionalCategoryField = None
    platform: PlatformField = "Amazon"
    market: MarketField = "USA"
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


class ProductResponse(BaseModel):
    id: str
    name: str
    category: str | None
    platform: str
    market: str
    project_id: str
    target_customer: str | None = None
    advantages: list[str] | None = None
    created_at: str


class GenerationRecord(BaseModel):
    id: str
    type: str
    input: dict
    output: dict
    tokens_used: int
    created_at: str


class ProductDetailResponse(ProductResponse):
    project: dict
    stats: dict
    score: dict | None = None
    next_actions: list[dict] = []
    generations: list[GenerationRecord] = []
