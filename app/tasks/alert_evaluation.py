import asyncio
import structlog
from datetime import datetime, timezone, timedelta
from celery import shared_task
from sqlalchemy import select, and_, func
from sqlalchemy.dialects.postgresql import insert

from app.database import AsyncSessionLocal
from app.models.rate_alert import RateAlertRule, RateAlert
from app.models.rate_trend import RateTrend
from app.models.freight_rate import FreightRate

logger = structlog.get_logger()

async def _run_alert_evaluation(evaluation_date=None, session_factory=AsyncSessionLocal) -> dict:
    if evaluation_date is None:
        evaluation_date = datetime.now(timezone.utc).date()

    logger.info("evaluate_rate_alerts_started", evaluation_date=evaluation_date)
    triggered_count = 0

    async with session_factory() as session:
        # Get active rules
        rules = (await session.execute(
            select(RateAlertRule).where(RateAlertRule.is_active == True)
        )).scalars().all()

        for rule in rules:
            triggered = False
            message = ""
            actual_magnitude = None

            if rule.alert_type in ("rate_spike", "rate_drop"):
                # Evaluate against RateTrend
                trend = await session.scalar(
                    select(RateTrend).where(
                        RateTrend.trade_lane == rule.trade_lane,
                        RateTrend.computed_date == evaluation_date
                    )
                )
                if not trend:
                    logger.warning("missing_trend_data", rule_id=str(rule.id), evaluation_date=evaluation_date)
                    continue

                if trend.change_7d_pct is None:
                    continue

                if rule.alert_type == "rate_spike" and trend.change_7d_pct > rule.magnitude_pct:
                    triggered = True
                    actual_magnitude = trend.change_7d_pct
                    message = f"Rate spiked by {actual_magnitude}% on {rule.trade_lane}"
                elif rule.alert_type == "rate_drop" and trend.change_7d_pct < -rule.magnitude_pct:
                    triggered = True
                    actual_magnitude = trend.change_7d_pct
                    message = f"Rate dropped by {abs(actual_magnitude)}% on {rule.trade_lane}"

            elif rule.alert_type in ("threshold_above", "threshold_below"):
                # Evaluate against FreightRate
                latest_date_stmt = (
                    select(func.max(FreightRate.rate_date))
                    .where(FreightRate.trade_lane == rule.trade_lane, FreightRate.rate_date <= evaluation_date)
                )
                latest_date = await session.scalar(latest_date_stmt)

                if not latest_date:
                    logger.warning("missing_freight_rate", rule_id=str(rule.id), evaluation_date=evaluation_date)
                    continue

                # Freshness Guard: Do not evaluate if the latest rate is more than 48 hours old
                MAX_RATE_STALENESS_DAYS = 2
                if latest_date < evaluation_date - timedelta(days=MAX_RATE_STALENESS_DAYS):
                    logger.info(
                        "stale_threshold_data_skipped",
                        rule_id=str(rule.id),
                        evaluation_date=evaluation_date.isoformat(),
                        latest_date=latest_date.isoformat()
                    )
                    continue

                current_rate_stmt = (
                    select(func.avg(FreightRate.rate_usd))
                    .where(FreightRate.trade_lane == rule.trade_lane, FreightRate.rate_date == latest_date)
                )
                current_rate = float(await session.scalar(current_rate_stmt))

                if rule.alert_type == "threshold_above" and current_rate > float(rule.target_usd):
                    triggered = True
                    message = f"Rate on {rule.trade_lane} is above ${rule.target_usd}"
                elif rule.alert_type == "threshold_below" and current_rate < float(rule.target_usd):
                    triggered = True
                    message = f"Rate on {rule.trade_lane} is below ${rule.target_usd}"

            if triggered:
                # Idempotent insert
                stmt = insert(RateAlert).values(
                    rule_id=rule.id,
                    user_id=rule.user_id,
                    trade_lane=rule.trade_lane,
                    alert_type=rule.alert_type,
                    message=message,
                    magnitude_pct=actual_magnitude,
                    is_read=False,
                    evaluation_date=evaluation_date,
                )
                stmt = stmt.on_conflict_do_nothing(
                    index_elements=["rule_id", "evaluation_date"]
                )
                result = await session.execute(stmt)
                if result.rowcount > 0:
                    triggered_count += 1

        await session.commit()

    logger.info("evaluate_rate_alerts_completed", triggered=triggered_count)
    return {"triggered": triggered_count}


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def evaluate_rate_alerts(self, evaluation_date: str = None):
    try:
        if evaluation_date:
            from datetime import date
            dt = date.fromisoformat(evaluation_date)
            return asyncio.run(_run_alert_evaluation(evaluation_date=dt))
        return asyncio.run(_run_alert_evaluation())
    except Exception as exc:
        logger.exception("evaluate_rate_alerts_unexpected_error", error=str(exc))
        raise self.retry(exc=exc) from exc
