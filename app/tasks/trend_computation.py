import asyncio
import structlog
from datetime import datetime, timedelta, timezone
from celery import shared_task
from sqlalchemy import select, func, distinct
from sqlalchemy.dialects.postgresql import insert

from app.database import AsyncSessionLocal
from app.models import FreightRate, RateTrend

logger = structlog.get_logger()

async def _run_trend_computation(computation_date=None, session_factory=AsyncSessionLocal) -> dict:
    if computation_date is None:
        computation_date = datetime.now(timezone.utc).date()

    logger.info("compute_rate_trends_started", computation_date=computation_date)

    upserted_count = 0

    async with session_factory() as session:
        lanes = (await session.execute(select(distinct(FreightRate.trade_lane)))).scalars().all()

        for lane in lanes:
            latest_date_stmt = (
                select(func.max(FreightRate.rate_date))
                .where(FreightRate.trade_lane == lane, FreightRate.rate_date <= computation_date)
            )
            latest_date = await session.scalar(latest_date_stmt)

            if not latest_date:
                stmt = insert(RateTrend).values(
                    trade_lane=lane,
                    computed_date=computation_date,
                    avg_7d_usd=None,
                    avg_30d_usd=None,
                    change_7d_pct=None,
                    change_30d_pct=None,
                    trend=None,
                    slope_per_week=None,
                    anomaly_flag=False,
                )
                stmt = stmt.on_conflict_do_update(
                    index_elements=["trade_lane", "computed_date"],
                    set_={
                        "avg_7d_usd": None,
                        "avg_30d_usd": None,
                        "change_7d_pct": None,
                        "change_30d_pct": None,
                        "trend": None,
                        "slope_per_week": None,
                        "anomaly_flag": False,
                    }
                )
                await session.execute(stmt)
                upserted_count += 1
                continue

            current_stmt = (
                select(func.avg(FreightRate.rate_usd))
                .where(FreightRate.trade_lane == lane, FreightRate.rate_date == latest_date)
            )
            current_rate = float(await session.scalar(current_stmt))

            cutoff_7d = computation_date - timedelta(days=7)
            avg_7d_stmt = (
                select(func.avg(FreightRate.rate_usd))
                .where(FreightRate.trade_lane == lane, FreightRate.rate_date >= cutoff_7d, FreightRate.rate_date <= computation_date)
            )
            avg_7d_val = await session.scalar(avg_7d_stmt)
            avg_7d_usd = float(avg_7d_val) if avg_7d_val is not None else None

            cutoff_30d = computation_date - timedelta(days=30)
            avg_30d_stmt = (
                select(func.avg(FreightRate.rate_usd))
                .where(FreightRate.trade_lane == lane, FreightRate.rate_date >= cutoff_30d, FreightRate.rate_date <= computation_date)
            )
            avg_30d_val = await session.scalar(avg_30d_stmt)
            avg_30d_usd = float(avg_30d_val) if avg_30d_val is not None else None

            def pct(current, base):
                if base is None or base == 0:
                    return None
                return round(((current - base) / base) * 100, 2)

            change_7d_pct = pct(current_rate, avg_7d_usd)
            change_30d_pct = pct(current_rate, avg_30d_usd)

            trend = None
            if change_7d_pct is not None:
                if change_7d_pct > 5:
                    trend = "rising"
                elif change_7d_pct < -5:
                    trend = "falling"
                else:
                    trend = "stable"

            anomaly_flag = False
            if change_7d_pct is not None and abs(change_7d_pct) > 12:
                anomaly_flag = True

            oldest_date_stmt = (
                select(func.min(FreightRate.rate_date))
                .where(FreightRate.trade_lane == lane, FreightRate.rate_date >= cutoff_7d, FreightRate.rate_date <= latest_date)
            )
            oldest_date = await session.scalar(oldest_date_stmt)

            slope_per_week = None
            if oldest_date and oldest_date < latest_date:
                days_elapsed = (latest_date - oldest_date).days
                if days_elapsed > 0:
                    historical_stmt = (
                        select(func.avg(FreightRate.rate_usd))
                        .where(FreightRate.trade_lane == lane, FreightRate.rate_date == oldest_date)
                    )
                    historical_rate = float(await session.scalar(historical_stmt))
                    slope = ((current_rate - historical_rate) / days_elapsed) * 7
                    slope_per_week = round(slope, 3)

            stmt = insert(RateTrend).values(
                trade_lane=lane,
                computed_date=computation_date,
                avg_7d_usd=round(avg_7d_usd, 2) if avg_7d_usd is not None else None,
                avg_30d_usd=round(avg_30d_usd, 2) if avg_30d_usd is not None else None,
                change_7d_pct=change_7d_pct,
                change_30d_pct=change_30d_pct,
                trend=trend,
                slope_per_week=slope_per_week,
                anomaly_flag=anomaly_flag,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["trade_lane", "computed_date"],
                set_={
                    "avg_7d_usd": round(avg_7d_usd, 2) if avg_7d_usd is not None else None,
                    "avg_30d_usd": round(avg_30d_usd, 2) if avg_30d_usd is not None else None,
                    "change_7d_pct": change_7d_pct,
                    "change_30d_pct": change_30d_pct,
                    "trend": trend,
                    "slope_per_week": slope_per_week,
                    "anomaly_flag": anomaly_flag,
                }
            )
            await session.execute(stmt)
            upserted_count += 1

        await session.commit()

    logger.info("compute_rate_trends_completed", upserted=upserted_count)
    return {"upserted": upserted_count}

@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def compute_rate_trends(self, computation_date: str = None):
    """
    Scheduled Celery task to aggregate live freight rates into RateTrend snapshots.
    Idempotent and safe to run repeatedly. AI state fields are strictly preserved.
    """
    try:
        if computation_date:
            from datetime import date
            dt = date.fromisoformat(computation_date)
            return asyncio.run(_run_trend_computation(computation_date=dt))
        return asyncio.run(_run_trend_computation())
    except Exception as exc:
        logger.exception("compute_rate_trends_unexpected_error", error=str(exc))
        raise self.retry(exc=exc) from exc
