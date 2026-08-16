"""Amazon listing read and sync API schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import ApiResponse
from app.schemas.pagination import PaginationMeta


class AmazonListingPublic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    marketplace_id: str
    seller_sku: str
    asin: str | None
    product_id: uuid.UUID | None
    status_codes: list[str]
    product_type: str | None
    upstream_created_at: datetime | None
    upstream_last_updated_at: datetime | None
    is_active: bool
    first_seen_at: datetime
    last_seen_at: datetime
    created_at: datetime
    updated_at: datetime


class AmazonListingListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[AmazonListingPublic]
    pagination: PaginationMeta


class AmazonProductSyncResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_id: uuid.UUID
    marketplace_id: str
    sync_log_id: uuid.UUID
    items_seen: int = Field(ge=0)
    items_written: int = Field(ge=0)
    items_deactivated: int = Field(ge=0)
    pages_seen: int = Field(ge=0)


AmazonListingListApiResponse = ApiResponse[AmazonListingListResponse]
AmazonProductSyncApiResponse = ApiResponse[AmazonProductSyncResponse]
