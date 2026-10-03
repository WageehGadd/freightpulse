"""Schedule only unambiguously resolved grounded artifacts; no forecast generation."""
import asyncio
from datetime import date, datetime, timezone
import logging
from celery import shared_task
from fastapi import HTTPException
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models import RateTrend
from app.services.rate_outlook import RateOutlookService
from app.tasks.rate_outlook_generation import generate_rate_outlook

logger = logging.getLogger(__name__)

async def _schedule(target_date, session_factory=AsyncSessionLocal):
    scheduled = skipped = 0
    async with session_factory() as session:
        ids = list((await session.execute(select(RateTrend.id).where(
            RateTrend.computed_date == target_date))).scalars().all())
        for trend_id in ids:
            try:
                row = await RateOutlookService(session).create(trend_id)
            except HTTPException:
                skipped += 1
                continue
            if row.status == "pending":
                try:
                    generate_rate_outlook.delay(str(row.id))
                    scheduled += 1
                except Exception:
                    await RateOutlookService(session).mark_enqueue_failed(row)
                    skipped += 1
    return {"lanes": scheduled, "skipped": skipped}

@shared_task
def schedule_rate_outlook(target_date: str = None):
    day = date.fromisoformat(target_date) if target_date else datetime.now(timezone.utc).date()
    return asyncio.run(_schedule(day))
