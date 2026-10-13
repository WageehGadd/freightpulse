from datetime import datetime, timezone
import structlog
from celery import chain, shared_task
from app.redis_client import get_redis
from app.tasks.rate_ingestion import ingest_freight_rates
from app.tasks.trend_computation import compute_rate_trends
from app.tasks.alert_evaluation import evaluate_rate_alerts
from app.tasks.rate_forecast_orchestrator import generate_rate_forecasts

try:
    from app.tasks.rate_outlook_orchestrator import schedule_rate_outlook
except ImportError:
    @shared_task
    def schedule_rate_outlook(target_date: str = None):
        return {"status": "skipped", "reason": "rate_outlook_orchestrator_not_available"}

logger = structlog.get_logger()


async def _acquire_pipeline_lock(target_date: str) -> bool:
    redis = get_redis()
    key = f"pipeline_lock:{target_date}"
    res = await redis.set(key, "1", nx=True, ex=86400)
    return bool(res)


async def _trigger_daily_pipeline() -> dict:
    # Deterministic target date
    target_date = datetime.now(timezone.utc).date().isoformat()
    acquired = await _acquire_pipeline_lock(target_date)

    if not acquired:
        logger.info("daily_pipeline_skipped_lock_held", target_date=target_date)
        return {"status": "skipped", "reason": "lock_acquired", "target_date": target_date}

    # Authoritative orchestration sequence:
    # 1. Fresh source ingestion
    # 2. Exact series trend computation
    # 3. T06 forecast generation & persistence
    # 4. Rate alert evaluation
    # 5. Dependent T07 grounded outlook generation
    pipeline = chain(
        ingest_freight_rates.si(),
        compute_rate_trends.si(computation_date=target_date),
        generate_rate_forecasts.si(target_date=target_date),
        evaluate_rate_alerts.si(evaluation_date=target_date),
        schedule_rate_outlook.si(target_date=target_date),
    )
    pipeline.apply_async()

    logger.info("daily_pipeline_dispatched", target_date=target_date)
    return {"status": "dispatched", "target_date": target_date}


@shared_task(bind=True, max_retries=1)
def trigger_daily_pipeline(self):
    """
    Authoritative trigger for the daily FreightPulse pipeline.
    Ensures dependency sequence: ingestion -> trends -> T06 forecasts -> alerts -> T07 outlooks.
    """
    try:
        return asyncio.run(_trigger_daily_pipeline())
    except Exception as exc:
        logger.exception("trigger_daily_pipeline_error", error=str(exc))
        raise self.retry(exc=exc) from exc

