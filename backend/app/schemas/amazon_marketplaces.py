"""Amazon marketplace read and refresh API schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import ApiResponse


class AmazonMarketplacePublic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    marketplace_id: str
    marketplace_name: str
    country_code: str
    default_currency_code: str | None
    default_language_code: str | None
    domain_name: str | None
    participating: bool
    suspended_listings: bool
    is_active: bool
    sync_eligible: bool
    last_seen_at: datetime
    created_at: datetime
    updated_at: datetime


class AmazonMarketplaceListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[AmazonMarketplacePublic]
    total: int = Field(ge=0)


class AmazonMarketplaceRefreshResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_id: uuid.UUID
    sync_log_id: uuid.UUID
    items_seen: int = Field(ge=0)
    items_written: int = Field(ge=0)
    items_deactivated: int = Field(ge=0)


AmazonMarketplaceListApiResponse = ApiResponse[AmazonMarketplaceListResponse]
AmazonMarketplaceRefreshApiResponse = ApiResponse[AmazonMarketplaceRefreshResponse]
