from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Query, HTTPException, status
from sqlalchemy import case, func, select, insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_ingest_token
from app.db.session import get_session
from app.models import RequestLog, DailyMetrics
from app.schemas import ImportResult, MetricsResponse, RatingsResponse, RequestLogIn, TimeSeriesPoint

router = APIRouter()


def _resolve_time_range(start: datetime | None, end: datetime | None, default_days: int = 7) -> tuple[datetime, datetime]:
    now = datetime.now(timezone.utc)
    start_dt = start if start else now - timedelta(days=default_days)
    end_dt = end if end else now
    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=timezone.utc)
    if end_dt.tzinfo is None:
        end_dt = end_dt.replace(tzinfo=timezone.utc)
    if start_dt >= end_dt:
        raise ValueError("start must be earlier than end")
    return start_dt, end_dt


@router.get("/metrics/requests", response_model=list[MetricsResponse])
async def request_metrics(
    model: Annotated[str | None, Query()] = None,
    prompt_version: Annotated[str | None, Query(alias="prompt")] = None,
    start: Annotated[datetime | None, Query()] = None,
    end: Annotated[datetime | None, Query()] = None,
    session: AsyncSession = Depends(get_session),
):
    try:
        start_dt, end_dt = _resolve_time_range(start, end, default_days=7)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    stmt = (
        select(
            RequestLog.model,
            RequestLog.prompt_version,
            func.count().label("total"),
            func.sum(case((RequestLog.success.is_(True), 1), else_=0)).label("success"),
            func.percentile_cont(0.5).within_group(RequestLog.latency_ms).label("p50"),
            func.percentile_cont(0.95).within_group(RequestLog.latency_ms).label("p95"),
        )
        .where(RequestLog.created_at >= start_dt, RequestLog.created_at < end_dt)
        .group_by(RequestLog.model, RequestLog.prompt_version)
    )
    if model:
        stmt = stmt.where(RequestLog.model == model)
    if prompt_version:
        stmt = stmt.where(RequestLog.prompt_version == prompt_version)

    rows = (await session.execute(stmt)).all()

    return [
        MetricsResponse(
            model=r.model,
            prompt_version=r.prompt_version,
            total=r.total,
            success_rate=round((r.success or 0) / r.total, 3) if r.total else 0,
            p50_ms=int(r.p50 or 0),
            p95_ms=int(r.p95 or 0),
        )
        for r in rows
    ]


@router.get("/metrics/ratings", response_model=list[RatingsResponse])
async def ratings_metrics(
    model: Annotated[str | None, Query()] = None,
    prompt_version: Annotated[str | None, Query(alias="prompt")] = None,
    start: Annotated[datetime | None, Query()] = None,
    end: Annotated[datetime | None, Query()] = None,
    session: AsyncSession = Depends(get_session),
):
    try:
        start_dt, end_dt = _resolve_time_range(start, end, default_days=30)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    stmt = (
        select(
            RequestLog.model,
            RequestLog.prompt_version,
            func.avg(RequestLog.user_rating).label("rating_avg"),
            func.count(RequestLog.user_rating).label("rating_count"),
        )
        .where(
            RequestLog.created_at >= start_dt,
            RequestLog.created_at < end_dt,
            RequestLog.user_rating.isnot(None),
        )
        .group_by(RequestLog.model, RequestLog.prompt_version)
    )
    if model:
        stmt = stmt.where(RequestLog.model == model)
    if prompt_version:
        stmt = stmt.where(RequestLog.prompt_version == prompt_version)

    rows = (await session.execute(stmt)).all()
    return [
        RatingsResponse(
            model=r.model,
            prompt_version=r.prompt_version,
            rating_avg=float(r.rating_avg) if r.rating_avg is not None else None,
            rating_count=r.rating_count,
        )
        for r in rows
    ]


@router.get("/metrics/timeseries", response_model=list[TimeSeriesPoint])
async def timeseries_metrics(
    model: Annotated[str | None, Query()] = None,
    prompt_version: Annotated[str | None, Query(alias="prompt")] = None,
    start: Annotated[datetime | None, Query()] = None,
    end: Annotated[datetime | None, Query()] = None,
    session: AsyncSession = Depends(get_session),
):
    try:
        start_dt, end_dt = _resolve_time_range(start, end, default_days=30)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    # Favor materialized view for daily rollups when available.
    stmt = select(
        DailyMetrics.model,
        DailyMetrics.prompt_version,
        DailyMetrics.date,
        DailyMetrics.total,
        DailyMetrics.success,
        DailyMetrics.avg_latency_ms,
        DailyMetrics.p50_latency,
        DailyMetrics.p95_latency,
    ).where(DailyMetrics.date >= start_dt.date(), DailyMetrics.date < end_dt.date())

    if model:
        stmt = stmt.where(DailyMetrics.model == model)
    if prompt_version:
        stmt = stmt.where(DailyMetrics.prompt_version == prompt_version)

    stmt = stmt.order_by(DailyMetrics.model, DailyMetrics.prompt_version, DailyMetrics.date)

    rows = (await session.execute(stmt)).all()
    results = [
        TimeSeriesPoint(
            date=r.date,
            model=r.model,
            prompt_version=r.prompt_version,
            total=r.total,
            success_rate=round((r.success or 0) / r.total, 3) if r.total else 0,
            avg_latency_ms=r.avg_latency_ms,
            p50_latency=r.p50_latency,
            p95_latency=r.p95_latency,
        )
        for r in rows
    ]
    if results:
        return results

    # Fallback to live aggregation if the materialized view has not been refreshed yet.
    dt_stmt = (
        select(
            RequestLog.model,
            RequestLog.prompt_version,
            func.date_trunc("day", RequestLog.created_at).label("date"),
            func.count().label("total"),
            func.sum(case((RequestLog.success.is_(True), 1), else_=0)).label("success"),
            func.avg(RequestLog.latency_ms).label("avg_latency_ms"),
            func.percentile_cont(0.5).within_group(RequestLog.latency_ms).label("p50"),
            func.percentile_cont(0.95).within_group(RequestLog.latency_ms).label("p95"),
        )
        .where(RequestLog.created_at >= start_dt, RequestLog.created_at < end_dt)
        .group_by(RequestLog.model, RequestLog.prompt_version, func.date_trunc("day", RequestLog.created_at))
        .order_by(RequestLog.model, RequestLog.prompt_version, func.date_trunc("day", RequestLog.created_at))
    )
    if model:
        dt_stmt = dt_stmt.where(RequestLog.model == model)
    if prompt_version:
        dt_stmt = dt_stmt.where(RequestLog.prompt_version == prompt_version)

    dt_rows = (await session.execute(dt_stmt)).all()
    return [
        TimeSeriesPoint(
            date=r.date.date(),
            model=r.model,
            prompt_version=r.prompt_version,
            total=r.total,
            success_rate=round((r.success or 0) / r.total, 3) if r.total else 0,
            avg_latency_ms=float(r.avg_latency_ms) if r.avg_latency_ms is not None else None,
            p50_latency=r.p50,
            p95_latency=r.p95,
        )
        for r in dt_rows
    ]


@router.post("/metrics/import", response_model=ImportResult, status_code=status.HTTP_201_CREATED)
async def import_metrics(
    payload: list[RequestLogIn],
    session: AsyncSession = Depends(get_session),
    _: None = Depends(require_ingest_token),
):
    if not payload:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Payload cannot be empty")

    now = datetime.now(timezone.utc)
    rows = [
        {
            "created_at": now,
            "model": item.model,
            "prompt_version": item.prompt_version,
            "success": item.success,
            "latency_ms": item.latency_ms,
            "user_rating": item.user_rating,
            "error_code": item.error_code,
            "metadata": item.metadata or {},
        }
        for item in payload
    ]

    try:
        await session.execute(insert(RequestLog).values(rows))
        await session.commit()
        return ImportResult(inserted=len(rows), errors=[])
    except Exception as exc:  # pragma: no cover - defensive
        await session.rollback()
        return ImportResult(inserted=0, errors=[str(exc)])
