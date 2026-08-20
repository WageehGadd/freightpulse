import asyncio
from datetime import date
import structlog
from celery import chain
from app.celery_app import celery_app
from app.redis_client import get_redis
from app.tasks.rate_ingestion import ingest_freight_rates
from app.tasks.trend_computation import compute_rate_trends
from app.tasks.alert_evaluation import evaluate_rate_alerts

logger = structlog.get_logger()


async def _acquire_pipeline_lock(target_date: str) -> bool:
    redis = get_redis()
    key = f"pipeline_lock:{target_date}"
    res = await redis.set(key, "1", nx=True, ex=86400)
    return bool(res)


async def _trigger_daily_pipeline() -> dict:
    target_date = date.today().isoformat()
    acquired = await _acquire_pipeline_lock(target_date)

    if not acquired:
        logger.info("daily_pipeline_skipped_lock_held", target_date=target_date)
        return {"status": "skipped", "reason": "lock_acquired", "target_date": target_date}

    pipeline = chain(
        ingest_freight_rates.s(),
        compute_rate_trends.s(),
        evaluate_rate_alerts.s(),
    )
    pipeline.apply_async()

    logger.info("daily_pipeline_dispatched", target_date=target_date)
    return {"status": "dispatched", "target_date": target_date}


@celery_app.task(bind=True, max_retries=1)
def trigger_daily_pipeline(self):
    try:
        return asyncio.run(_trigger_daily_pipeline())
    except Exception as exc:
        raise self.retry(exc=exc) from exc
