from fastapi import APIRouter, Depends, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_ingest_token
from app.db.session import get_session

router = APIRouter()


@router.post("/admin/refresh-materialized", status_code=status.HTTP_202_ACCEPTED)
async def refresh_materialized(_: None = Depends(require_ingest_token), session: AsyncSession = Depends(get_session)):
    await session.execute(text("REFRESH MATERIALIZED VIEW CONCURRENTLY mv_daily_metrics"))
    await session.commit()
    return {"status": "ok"}
