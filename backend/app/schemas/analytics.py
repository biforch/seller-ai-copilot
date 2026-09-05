from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import ApiResponse


class EventMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")
    registration_completed: int = Field(ge=0)
    audit_started: int = Field(ge=0)
    audit_completed: int = Field(ge=0)
    audit_failed: int = Field(ge=0)
    amazon_connect_started: int = Field(ge=0)
    amazon_connected: int = Field(ge=0)


class DailyEventMetrics(EventMetrics):
    date: str


class AnalyticsSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    days: int
    period_start: datetime
    period_end: datetime
    counts: EventMetrics
    unique_users: EventMetrics
    audit_success_rate: float | None
    daily: list[DailyEventMetrics]


AnalyticsSummaryApiResponse = ApiResponse[AnalyticsSummary]
