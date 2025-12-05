from datetime import date, datetime
from typing import Any, List, Optional
from pydantic import BaseModel, Field, field_validator


class RequestLogIn(BaseModel):
    model: str
    prompt_version: str = Field(..., alias="prompt_version")
    success: bool
    latency_ms: int
    user_rating: Optional[int] = Field(default=None, ge=1, le=5)
    error_code: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None

    @field_validator("latency_ms")
    @classmethod
    def positive_latency(cls, v: int) -> int:
        if v < 0:
            raise ValueError("latency_ms must be non-negative")
        return v


class ImportResult(BaseModel):
    inserted: int
    errors: List[str] = Field(default_factory=list)


class MetricsResponse(BaseModel):
    model: str
    prompt_version: str
    total: int
    success_rate: float
    p50_ms: int
    p95_ms: int


class RatingsResponse(BaseModel):
    model: str
    prompt_version: str
    rating_avg: float | None
    rating_count: int


class TimeSeriesPoint(BaseModel):
    date: date
    model: str
    prompt_version: str
    total: int
    success_rate: float
    avg_latency_ms: float | None
    p50_latency: float | None
    p95_latency: float | None
