import asyncio
import structlog
from datetime import datetime
from zoneinfo import ZoneInfo
from celery import shared_task, chain
from redis.asyncio import Redis

from app.redis_client import get_redis
from app.tasks.rate_ingestion import ingest_freight_rates
from app.tasks.trend_computation import compute_rate_trends
from app.tasks.alert_evaluation import evaluate_rate_alerts
from app.tasks.rate_outlook_orchestrator import schedule_rate_outlook

logger = structlog.get_logger()

async def _acquire_pipeline_lock(target_date: str) -> bool:
    redis_client = get_redis()
    lock_key = f"pipeline_lock:{target_date}"
    # Use SETNX with a 24-hour expiration to prevent concurrent executions for the same logical date.
    # The expiration is set atomically during acquisition.
    acquired = await redis_client.set(lock_key, "1", nx=True, ex=86400)
    return bool(acquired)

async def _trigger_daily_pipeline() -> dict:
    # Use Cairo timezone to determine the logical target date, ensuring consistency
    # regardless of when exactly the cron triggers or crosses UTC boundaries.
    tz = ZoneInfo("Africa/Cairo")
    target_date = datetime.now(tz).date().isoformat()

    acquired = await _acquire_pipeline_lock(target_date)
    if not acquired:
        logger.warning("pipeline_already_triggered", target_date=target_date)
        return {"status": "skipped", "reason": "lock_acquired"}

    # Dispatch the pipeline using Celery Chain with immutable signatures (.si())
    # Ingestion runs naturally (it scrapes the latest live data).
    # Downstream tasks receive the explicit target_date to maintain logical consistency.
    pipeline = chain(
        ingest_freight_rates.si(),
        compute_rate_trends.si(computation_date=target_date),
        evaluate_rate_alerts.si(evaluation_date=target_date),
        schedule_rate_outlook.si(target_date=target_date)
    )

    # We use apply_async to fire and forget. The Celery workers handle retry propagation.
    pipeline.apply_async()

    logger.info("daily_pipeline_dispatched", target_date=target_date)
    return {"status": "dispatched", "target_date": target_date}

@shared_task(bind=True)
def trigger_daily_pipeline(self):
    """
    Authoritative trigger for the daily FreightPulse pipeline.
    Ensures safe dependency orchestration and prevents concurrent daily runs.
    """
    try:
        return asyncio.run(_trigger_daily_pipeline())
    except Exception as exc:
        logger.exception("trigger_daily_pipeline_error", error=str(exc))
        raise self.retry(exc=exc) from exc
