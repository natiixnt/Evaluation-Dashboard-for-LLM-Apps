import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import Boolean, Date, DateTime, Float, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class RequestLog(Base):
    __tablename__ = "request_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    model: Mapped[str] = mapped_column(String, nullable=False, index=True)
    prompt_version: Mapped[str] = mapped_column(String, nullable=False, index=True)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    user_rating: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    error_code: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB, nullable=True)


# Materialized view mapping for convenience; columns mirror mv_daily_metrics.
class DailyMetrics(Base):
    __tablename__ = "mv_daily_metrics"
    __table_args__ = {"info": {"is_view": True}}

    model: Mapped[str] = mapped_column(String, primary_key=True)
    prompt_version: Mapped[str] = mapped_column(String, primary_key=True)
    date: Mapped[datetime] = mapped_column(Date, primary_key=True)
    total: Mapped[int] = mapped_column(Integer)
    success: Mapped[int] = mapped_column(Integer)
    avg_latency_ms: Mapped[Optional[float]] = mapped_column(Float)
    p50_latency: Mapped[Optional[float]] = mapped_column(Float)
    p95_latency: Mapped[Optional[float]] = mapped_column(Float)
