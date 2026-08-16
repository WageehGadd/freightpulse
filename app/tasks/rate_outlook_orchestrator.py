# app/tasks/rate_outlook_orchestrator.py
"""Celery task to orchestrate AI Rate Outlook generation for all RateTrend rows of a given date.

It fetches the IDs of RateTrend records for the target date and dispatches a Celery group
of `generate_rate_outlook_async` tasks, each receiving a `trend_id`.

The task is deliberately lightweight: it contains no AI or Redis logic – those are
handled by the existing `generate_rate_outlook_async` task.
"""

import asyncio
import structlog
from datetime import datetime, timezone
from celery import shared_task, group
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.rate_trend import RateTrend
from app.tasks.rate_outlook_generation import generate_rate_outlook_async

logger = structlog.get_logger()

@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def schedule_rate_outlook(self, target_date: str = None) -> dict:
    """Dispatch AI Rate Outlook generation for every trend of the given date.

    Args:
        target_date: ISO‑format date string (e.g. "2026-08-15"). If omitted, the current UTC date is used.

    Returns:
        A dict containing the number of dispatched outlook jobs.
    """
    try:
        if target_date:
            date_str = target_date
        else:
            date_str = datetime.now(timezone.utc).date().isoformat()

        logger.info("schedule_rate_outlook_start", date=date_str)

        async def _fetch_trend_ids():
            async with AsyncSessionLocal() as session:
                stmt = select(RateTrend.id).where(RateTrend.computed_date == date_str)
                result = await session.execute(stmt)
                return [str(row[0]) for row in result.scalars().all()]

        trend_ids = asyncio.run(_fetch_trend_ids())
        if not trend_ids:
            logger.warning("schedule_rate_outlook_no_trends", date=date_str)
            return {"lanes": 0}

        # Build a Celery group of Outlook tasks – each receives a trend_id.
        outlook_jobs = group(
            generate_rate_outlook_async.s(trend_id) for trend_id in trend_ids
        )
        outlook_jobs.apply_async()

        logger.info("schedule_rate_outlook_dispatched", date=date_str, lanes=len(trend_ids))
        return {"lanes": len(trend_ids)}
    except Exception as exc:
        logger.exception("schedule_rate_outlook_unexpected_error", error=str(exc))
        raise self.retry(exc=exc) from exc
