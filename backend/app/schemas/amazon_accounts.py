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


class AmazonAccountDisconnectResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_id: uuid.UUID
    already_disconnected: bool
    disconnected_at: datetime | None


class AmazonCapabilitiesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    oauth_enabled: bool
    sp_api_enabled: bool


AmazonAccountListApiResponse = ApiResponse[AmazonAccountListResponse]
AmazonAccountDetailApiResponse = ApiResponse[AmazonAccountPublic]
AmazonAccountDisconnectApiResponse = ApiResponse[AmazonAccountDisconnectResponse]
AmazonCapabilitiesApiResponse = ApiResponse[AmazonCapabilitiesResponse]
