
from pydantic import BaseModel

from app.schemas.common_fields import (
    DescriptionField,
    MarketField,
    NameField,
    PlatformField,
)


class CreateProjectRequest(BaseModel):
    name: NameField
    description: DescriptionField = None
    platform: PlatformField = "Amazon"
    market: MarketField = "USA"


class ProjectResponse(BaseModel):
    id: str
    name: str
    description: str | None
    platform: str
    market: str
    status: str
    product_count: int = 0
    created_at: str


class ProjectDetailResponse(ProjectResponse):
    products: list[dict] = []
