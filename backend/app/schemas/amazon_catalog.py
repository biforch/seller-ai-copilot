"""Public schemas for bounded Amazon catalog summaries."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.schemas.common import ApiResponse


class AmazonCatalogSnapshotPublic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    listing_id: uuid.UUID
    asin: str
    marketplace_id: str
    item_name: str | None
    brand: str | None
    manufacturer: str | None
    color: str | None
    size: str | None
    style: str | None
    model_number: str | None
    part_number: str | None
    product_type: str | None
    fetched_at: datetime
    expires_at: datetime
    cache_hit: bool | None = None


AmazonCatalogSnapshotApiResponse = ApiResponse[AmazonCatalogSnapshotPublic | None]
