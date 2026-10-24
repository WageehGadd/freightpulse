"""Celery boundary for T06 baseline forecast persistence."""
import asyncio
from celery import shared_task
from app.database import AsyncSessionLocal
from app.services.forecast_persistence import ForecastPersistenceService


async def _generate():
    async with AsyncSessionLocal() as session:
        result = await ForecastPersistenceService(session).generate_and_persist_all()
        return {"attempted": result.attempted, "generated": result.generated,
                "failed": result.failed, "status": result.status}


@shared_task(bind=True, max_retries=2, default_retry_delay=60)
def generate_forecasts(self):
    try:
        return asyncio.run(_generate())
    except Exception as exc:
        raise self.retry(exc=exc) from exc
