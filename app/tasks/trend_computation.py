import asyncio
from datetime import date, timedelta
import structlog
import pandas as pd
from sqlalchemy import select
from app.celery_app import celery_app
from app.database import AsyncSessionLocal
from app.models.freight_rate import FreightRate
from app.models.rate_trend import RateTrend

logger = structlog.get_logger()


async def _run_trend_computation(
    computation_date: date | None = None,
    session_factory=None,
) -> dict:
    target_date = computation_date or date.today()
    session_maker = session_factory or AsyncSessionLocal
    upserted = 0

    cutoff_30d = target_date - timedelta(days=30)
    cutoff_7d = target_date - timedelta(days=7)

    async with session_maker() as session:
        # Load all rates in the 30d window
        stmt = select(FreightRate).where(
            FreightRate.rate_date >= cutoff_30d,
            FreightRate.rate_date <= target_date,
        )
        rates = (await session.execute(stmt)).scalars().all()

        # Check all distinct trade lanes in the DB to handle future/empty data
        all_lanes_stmt = select(FreightRate.trade_lane).distinct()
        distinct_lanes = (await session.execute(all_lanes_stmt)).scalars().all()

        rates_by_lane = {}
        for r in rates:
            rates_by_lane.setdefault(r.trade_lane, []).append(r)

        for lane in distinct_lanes:
            lane_rates = rates_by_lane.get(lane, [])

            if not lane_rates:
                # Insufficient historical data within window
                trend_stmt = select(RateTrend).where(
                    RateTrend.trade_lane == str(lane),
                    RateTrend.computed_date == target_date,
                )
                existing_trend = (await session.execute(trend_stmt)).scalar_one_or_none()

                if existing_trend:
                    existing_trend.avg_7d_usd = None
                    existing_trend.avg_30d_usd = None
                    existing_trend.change_7d_pct = None
                    existing_trend.trend = None
                    existing_trend.slope_per_week = None
                    existing_trend.anomaly_flag = False
                else:
                    new_trend = RateTrend(
                        trade_lane=str(lane),
                        computed_date=target_date,
                        avg_7d_usd=None,
                        avg_30d_usd=None,
                        change_7d_pct=None,
                        trend=None,
                        slope_per_week=None,
                        anomaly_flag=False,
                    )
                    session.add(new_trend)
                upserted += 1
                continue

            rates_7d = [r for r in lane_rates if r.rate_date >= cutoff_7d]
            rates_30d = lane_rates

            avg_7d = round(sum([float(r.rate_usd) for r in rates_7d]) / len(rates_7d), 2) if rates_7d else None
            avg_30d = round(sum([float(r.rate_usd) for r in rates_30d]) / len(rates_30d), 2) if rates_30d else None

            # Calculate change_7d_pct and slope_per_week
            change_7d_pct = None
            slope_per_week = None
            trend_val = None
            anomaly_flag = False

            if avg_7d is not None and rates_7d:
                # Sort 7d rates chronologically
                rates_7d_sorted = sorted(rates_7d, key=lambda x: x.rate_date)
                latest_rate = float(rates_7d_sorted[-1].rate_usd)

                change_7d_pct = round(((latest_rate - avg_7d) / avg_7d) * 100.0, 2)

                if change_7d_pct > 5.0:
                    trend_val = "rising"
                elif change_7d_pct < -5.0:
                    trend_val = "falling"
                else:
                    trend_val = "stable"

                if abs(change_7d_pct) > 12.0:
                    anomaly_flag = True

                if len(rates_7d_sorted) >= 2:
                    first_pt = rates_7d_sorted[0]
                    last_pt = rates_7d_sorted[-1]
                    days_diff = (last_pt.rate_date - first_pt.rate_date).days
                    if days_diff > 0:
                        slope_per_week = round(
                            ((float(last_pt.rate_usd) - float(first_pt.rate_usd)) / days_diff) * 7.0,
                            2,
                        )
                    else:
                        slope_per_week = 0.0

            trend_stmt = select(RateTrend).where(
                RateTrend.trade_lane == str(lane),
                RateTrend.computed_date == target_date,
            )
            existing_trend = (await session.execute(trend_stmt)).scalar_one_or_none()

            if existing_trend:
                existing_trend.avg_7d_usd = avg_7d
                existing_trend.avg_30d_usd = avg_30d
                existing_trend.change_7d_pct = change_7d_pct
                existing_trend.trend = trend_val
                existing_trend.slope_per_week = slope_per_week
                existing_trend.anomaly_flag = anomaly_flag
            else:
                new_trend = RateTrend(
                    trade_lane=str(lane),
                    computed_date=target_date,
                    avg_7d_usd=avg_7d,
                    avg_30d_usd=avg_30d,
                    change_7d_pct=change_7d_pct,
                    trend=trend_val,
                    slope_per_week=slope_per_week,
                    anomaly_flag=anomaly_flag,
                )
                session.add(new_trend)
            upserted += 1

        await session.commit()

    logger.info("trend_computation_completed", upserted=upserted)
    return {"upserted": upserted}


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def compute_rate_trends(self):
    try:
        return asyncio.run(_run_trend_computation())
    except Exception as exc:
        raise self.retry(exc=exc) from exc
