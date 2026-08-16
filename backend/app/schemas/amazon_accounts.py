"""Amazon account read API schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import ApiResponse


class AmazonAccountPublic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    region: str
    endpoint_mode: str
    status: str
    last_verified_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AmazonAccountListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[AmazonAccountPublic]
    total: int = Field(ge=0)


AmazonAccountListApiResponse = ApiResponse[AmazonAccountListResponse]
AmazonAccountDetailApiResponse = ApiResponse[AmazonAccountPublic]
