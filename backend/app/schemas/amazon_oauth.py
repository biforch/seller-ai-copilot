"""Amazon OAuth HTTP request/response schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class AmazonOAuthStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    marketplace_code: str = Field(min_length=1, max_length=8)
    intent: str = Field(min_length=1, max_length=32)
    target_account_id: uuid.UUID | None = None


class AmazonOAuthStartResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    authorization_url: str
    marketplace_code: str
    region: str
    expires_at: datetime
