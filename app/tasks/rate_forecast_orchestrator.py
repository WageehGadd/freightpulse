"""
Authoritative Celery task for generating and persisting T06 forecasts.
Ensures that fresh required source data and exact series produce available persisted
forecasts before dependent T07 grounded rate outlooks are scheduled.
"""
import asyncio
import logging
from typing import Optional, Dict, Any
from celery import shared_task

logger = logging.getLogger(__name__)


async def _generate_rate_forecasts(target_date: Optional[str] = None) -> Dict[str, Any]:
    """
    Generate and persist baseline rate forecasts for all profiled series.
    Reports attempted, generated, and failed counts honestly per handoff specifications.
    Distinguishes successful series from failed ones without claiming all series are ready
    on partial success.
    """
    try:
        from app.database import AsyncSessionLocal
        from app.services.forecast_persistence import ForecastPersistenceService
    except ImportError as err:
        logger.warning(
            "forecast_persistence_unavailable",
            extra={"error": str(err), "target_date": target_date},
        )
        return {
            "status": "unavailable",
            "message": "ForecastPersistenceService not available on current environment",
            "attempted": 0,
            "generated": 0,
            "failed": 0,
            "target_date": target_date,
        }

    async with AsyncSessionLocal() as session:
        service = ForecastPersistenceService(session)
        result = await service.generate_and_persist_all()

        total_generated = len(result.forecasts)
        if result.failed == 0 and total_generated > 0:
            status_str = "success"
        elif total_generated > 0 and result.failed > 0:
            status_str = "partial_success"
        else:
            status_str = "failed"

        logger.info(
            "rate_forecasts_generation_completed",
            extra={
                "status": status_str,
                "attempted": result.attempted,
                "generated": total_generated,
                "failed": result.failed,
                "target_date": target_date,
            },
        )

        return {
            "status": status_str,
            "attempted": result.attempted,
            "generated": total_generated,
            "failed": result.failed,
            "target_date": target_date,
        }


@shared_task(bind=True, max_retries=2, default_retry_delay=60)
def generate_rate_forecasts(self, target_date: Optional[str] = None):
    """
    Celery task that executes T06 forecast generation.
    Must be chained prior to schedule_rate_outlook.
    """
    try:
        return asyncio.run(_generate_rate_forecasts(target_date))
    except Exception as exc:
        logger.exception("generate_rate_forecasts_task_error", extra={"error": str(exc)})
        raise self.retry(exc=exc) from exc
