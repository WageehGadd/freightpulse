import redis.asyncio as aioredis
from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import CarrierAdvisory, FreightRate, PortCongestion

router = APIRouter()


@router.get("/health")
async def health_check(db: AsyncSession = Depends(get_db)):
    db_status = "connected"
    redis_status = "connected"

    try:
        await db.execute(select(1))
    except Exception:
        db_status = "disconnected"

    try:
        redis = aioredis.from_url(settings.REDIS_URL)
        await redis.ping()
        await redis.aclose()
    except Exception:
        redis_status = "disconnected"

    last_scfi = await db.scalar(
        select(func.max(FreightRate.created_at)).where(FreightRate.source == "SCFI")
    )
    last_fbx = await db.scalar(
        select(func.max(FreightRate.created_at)).where(FreightRate.source == "FBX")
    )
    last_port = await db.scalar(select(func.max(PortCongestion.created_at)))
    last_carrier = await db.scalar(select(func.max(CarrierAdvisory.created_at)))

    return {
        "status": "healthy" if db_status == "connected" and redis_status == "connected" else "degraded",
        "database": db_status,
        "redis": redis_status,
        "last_scrape": {
            "scfi": last_scfi.isoformat() if last_scfi else None,
            "fbx": last_fbx.isoformat() if last_fbx else None,
            "port_advisories": last_port.isoformat() if last_port else None,
            "carrier_advisories": last_carrier.isoformat() if last_carrier else None,
        },
    }