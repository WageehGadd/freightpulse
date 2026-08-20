import asyncio
import json
import uuid
import structlog
from app.celery_app import celery_app
from app.database import AsyncSessionLocal
from app.models.rate_trend import RateTrend
from app.models.freight_rate import FreightRate
from app.redis_client import get_redis
from app.ai.rate_outlook_narrator import RateOutlookNarrator
from app.ai.adapter import InsufficientDataError

logger = structlog.get_logger()


async def generate_rate_outlook_async(
    trend_id_str: str,
    session_factory=None,
    narrator_factory=None,
) -> dict:
    trend_uuid = uuid.UUID(trend_id_str)
    session_maker = session_factory or AsyncSessionLocal

    async with session_maker() as session:
        trend = await session.get(RateTrend, trend_uuid)
        if trend is None:
            raise ValueError(f"RateTrend '{trend_id_str}' not found")

        # 1. Check Redis Cache
        cache_key = f"rate_outlook:{trend.trade_lane}:{trend.computed_date.isoformat()}"
        cached_data = None
        try:
            redis = get_redis()
            cached_data = await redis.get(cache_key)
        except Exception as exc:
            logger.warning("redis_cache_get_failed", error=str(exc))

        if cached_data:
            try:
                cached_json = json.loads(cached_data)
                trend.outlook_text = cached_json.get("outlook_text")
                trend.recommendation = cached_json.get("recommendation")
                trend.confidence = cached_json.get("confidence")
                trend.status = "completed"
                trend.error_message = None
                await session.commit()
                return {"trend_id": str(trend_uuid), "status": "completed"}
            except Exception as exc:
                logger.warning("redis_cache_parse_failed", error=str(exc))

        # 2. Check for Insufficient Data
        if trend.avg_7d_usd is None:
            trend.status = "failed"
            trend.error_message = "Insufficient data to generate rate outlook"
            await session.commit()
            raise InsufficientDataError(f"Insufficient data for trade lane '{trend.trade_lane}'")

        # 3. Assemble Context & Call Narrator
        narrator = narrator_factory() if narrator_factory else RateOutlookNarrator()

        current_rate_str = f"${float(trend.avg_7d_usd):.2f}"
        hist_context = (
            f"7-day average: ${float(trend.avg_7d_usd):.2f}, "
            f"30-day average: ${float(trend.avg_30d_usd or trend.avg_7d_usd):.2f}, "
            f"7-day change: {trend.change_7d_pct}%, "
            f"Trend: {trend.trend or 'stable'}"
        )
        market_factors = (
            f"Slope per week: {trend.slope_per_week}, "
            f"Anomaly flag: {trend.anomaly_flag}"
        )

        try:
            output = await narrator.narrate(
                lane=trend.trade_lane,
                current_rate=current_rate_str,
                historical_context=hist_context,
                market_factors=market_factors,
            )

            trend.outlook_text = output.outlook_text
            trend.recommendation = output.recommendation
            trend.confidence = output.confidence
            trend.status = "completed"
            trend.error_message = None
            await session.commit()

            # 4. Cache in Redis
            try:
                redis = get_redis()
                payload = json.dumps({
                    "outlook_text": output.outlook_text,
                    "recommendation": output.recommendation,
                    "confidence": output.confidence,
                })
                await redis.setex(cache_key, 86400, payload)
            except Exception as cache_exc:
                logger.warning("redis_cache_set_failed", error=str(cache_exc))

            return {"trend_id": str(trend_uuid), "status": "completed"}

        except Exception as exc:
            trend.status = "failed"
            trend.error_message = str(exc)
            await session.commit()
            logger.exception("rate_outlook_generation_failed", trend_id=str(trend_uuid), error=str(exc))
            raise


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def generate_rate_outlook(self, trend_id: str):
    try:
        return asyncio.run(generate_rate_outlook_async(trend_id))
    except Exception as exc:
        raise self.retry(exc=exc) from exc
