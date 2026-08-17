import asyncio
import logging
import uuid
from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.celery_app import celery_app
from app.database import AsyncSessionLocal
from app.models import RateTrend, FreightRate, CarrierAdvisory
from app.ai.adapter import (
    RateOutlookNarratorAdapter,
    RateOutlookContext,
    TrendNotFoundError,
)
from app.ai.rate_outlook_narrator import RateOutlookNarrator
from app.ai.openai_client import FreightPulseAIClient

logger = logging.getLogger(__name__)


class InvalidTrendIdError(ValueError):
    pass


class TrendStateError(Exception):
    pass


class SQLAlchemyRateTrendRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_context(self, trend_id: uuid.UUID) -> RateOutlookContext | None:
        trend = await self.session.get(RateTrend, trend_id)
        if not trend:
            return None

        lane = trend.trade_lane

        latest_rate_stmt = (
            select(FreightRate)
            .where(FreightRate.trade_lane == lane)
            .order_by(FreightRate.rate_date.desc())
            .limit(1)
        )
        latest_rate = (await self.session.execute(latest_rate_stmt)).scalar_one_or_none()
        current_rate_str = f"{latest_rate.rate_usd} USD on {latest_rate.rate_date}" if latest_rate else "Unknown"

        historical_context_str = f"7-day avg: {trend.avg_7d_usd}, 30-day avg: {trend.avg_30d_usd}. "
        historical_context_str += f"Trend: {trend.trend}, Slope: {trend.slope_per_week}."

        advisories_stmt = (
            select(CarrierAdvisory)
            .where(CarrierAdvisory.affected_lanes.any(lane))
            .order_by(CarrierAdvisory.published_at.desc())
            .limit(3)
        )
        advisories = (await self.session.execute(advisories_stmt)).scalars().all()
        market_factors_str = "Recent Advisories: " + "; ".join(
            f"{adv.carrier}: {adv.summary}" for adv in advisories if adv.summary
        )

        return RateOutlookContext(
            trend=trend,
            current_rate=current_rate_str,
            historical_context=historical_context_str,
            market_factors=market_factors_str,
        )

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()


def _build_narrator() -> RateOutlookNarrator:
    return RateOutlookNarrator(ai_client=FreightPulseAIClient())


def _parse_trend_id(trend_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(trend_id)
    except (AttributeError, TypeError, ValueError) as exc:
        raise InvalidTrendIdError(f"Invalid trend UUID: {trend_id!r}") from exc


import json
from app.redis_client import get_redis

async def _mark_failed(session: AsyncSession, trend_id: uuid.UUID) -> None:
    trend = await session.get(RateTrend, trend_id)
    if trend is None:
        return
    trend.status = "failed"
    trend.error_message = "Rate outlook generation failed. Please try again later."
    await session.commit()


async def generate_rate_outlook_async(
    trend_id: str,
    *,
    session_factory: Callable[[], Any] = AsyncSessionLocal,
    narrator_factory: Callable[[], RateOutlookNarrator] = _build_narrator,
    allow_generating_retry: bool = False,
    mark_failed_on_error: bool = True,
) -> dict[str, str]:
    parsed_id = _parse_trend_id(trend_id)

    async with session_factory() as session:
        trend = await session.get(RateTrend, parsed_id)
        if trend is None:
            raise TrendNotFoundError(f"Trend {parsed_id} not found.")
        if trend.status == "completed":
            return {"trend_id": str(parsed_id), "status": "completed"}
        if trend.status != "pending" and not (allow_generating_retry and trend.status == "generating"):
            raise TrendStateError(f"Trend {parsed_id} is not pending.")

        cache_key = f"rate_outlook:{trend.trade_lane}:{trend.computed_date}"
        redis = get_redis()

        try:
            cached_data = await redis.get(cache_key)
            if cached_data:
                parsed_cache = json.loads(cached_data)
                trend.outlook_text = parsed_cache.get("outlook_text")
                trend.recommendation = parsed_cache.get("recommendation")
                trend.confidence = parsed_cache.get("confidence")
                trend.status = "completed"
                trend.error_message = None
                await session.commit()
                logger.info("rate_outlook_cache_hit", extra={"lane": trend.trade_lane, "date": str(trend.computed_date)})
                return {"trend_id": str(parsed_id), "status": "completed"}
            else:
                logger.info("rate_outlook_cache_miss", extra={"lane": trend.trade_lane, "date": str(trend.computed_date)})
        except Exception:
            logger.exception("rate_outlook_cache_failed", extra={"lane": trend.trade_lane, "date": str(trend.computed_date)})

        if trend.status == "pending":
            trend.status = "generating"
            trend.error_message = None
            await session.commit()

        adapter = RateOutlookNarratorAdapter(
            repository=SQLAlchemyRateTrendRepository(session),
            narrator=narrator_factory(),
        )

        try:
            logger.info("rate_outlook_started", extra={"lane": trend.trade_lane, "date": str(trend.computed_date)})
            output = await adapter.narrate_and_save(parsed_id)
            logger.info("rate_outlook_persisted", extra={"lane": trend.trade_lane, "date": str(trend.computed_date)})

            try:
                cache_payload = {
                    "outlook_text": output.outlook_text,
                    "recommendation": output.recommendation,
                    "confidence": output.confidence,
                }
                await redis.setex(cache_key, 86400, json.dumps(cache_payload))
            except Exception:
                logger.exception("rate_outlook_cache_set_failed", extra={"lane": trend.trade_lane, "date": str(trend.computed_date)})

            return {"trend_id": str(parsed_id), "status": "completed"}
        except Exception:
            logger.exception("rate_outlook_failed", extra={"lane": trend.trade_lane, "date": str(trend.computed_date)})
            if mark_failed_on_error:
                try:
                    await _mark_failed(session, parsed_id)
                except Exception:
                    await session.rollback()
                    logger.exception("rate_outlook_failure_status_update_failed", extra={"trend_id": str(parsed_id)})
            raise


@celery_app.task(bind=True, max_retries=2, default_retry_delay=30)
def generate_rate_outlook(self, trend_id: str) -> dict[str, str]:
    try:
        return asyncio.run(
            generate_rate_outlook_async(
                trend_id,
                allow_generating_retry=self.request.retries > 0,
                mark_failed_on_error=self.request.retries >= self.max_retries,
            )
        )
    except (InvalidTrendIdError, TrendNotFoundError, TrendStateError):
        raise
    except Exception as exc:
        raise self.retry(exc=exc) from exc
