import asyncio
from datetime import date, timedelta
# pyrefly: ignore [missing-import]
import structlog
from sqlalchemy import select
from app.celery_app import celery_app
from app.database import AsyncSessionLocal
from app.models.rate_alert import RateAlertRule, RateAlert
from app.models.rate_trend import RateTrend
from app.models.freight_rate import FreightRate
from app.alert_publisher import publish_alert

logger = structlog.get_logger()


async def _run_alert_evaluation(
    evaluation_date: date | None = None,
    session_factory=None,
) -> dict:
    target_date = evaluation_date or date.today()
    session_maker = session_factory or AsyncSessionLocal
    triggered = 0
    new_alerts = []

    async with session_maker() as session:
        rules_stmt = select(RateAlertRule).where(RateAlertRule.is_active == True)  # noqa: E712
        rules = (await session.execute(rules_stmt)).scalars().all()

        for rule in rules:
            # 1. Rate Spike / Rate Drop rules
            if rule.alert_type in ("rate_spike", "rate_drop"):
                trend_stmt = select(RateTrend).where(
                    RateTrend.trade_lane == rule.trade_lane,
                    RateTrend.computed_date == target_date,
                )
                trend = (await session.execute(trend_stmt)).scalar_one_or_none()
                if not trend or trend.change_7d_pct is None:
                    continue

                is_triggered = False
                msg = ""
                if rule.alert_type == "rate_spike" and trend.change_7d_pct >= (rule.magnitude_pct or 0.0):
                    is_triggered = True
                    msg = f"Freight rates spiked by {trend.change_7d_pct:.1f}% on {rule.trade_lane} exceeding {rule.magnitude_pct}% rule."
                elif rule.alert_type == "rate_drop" and trend.change_7d_pct <= -(rule.magnitude_pct or 0.0):
                    is_triggered = True
                    msg = f"Freight rates dropped by {abs(trend.change_7d_pct):.1f}% on {rule.trade_lane} exceeding {rule.magnitude_pct}% rule."

                if is_triggered:
                    # Idempotency check: did we already trigger this rule/event for today?
                    existing_alert_stmt = select(RateAlert).where(
                        RateAlert.user_id == rule.user_id,
                        RateAlert.trade_lane == rule.trade_lane,
                        RateAlert.alert_type == rule.alert_type,
                        RateAlert.last_event_date == target_date,
                    )
                    existing_alert = (await session.execute(existing_alert_stmt)).scalar_one_or_none()
                    if existing_alert:
                        continue

                    alert = RateAlert(
                        user_id=rule.user_id,
                        trade_lane=rule.trade_lane,
                        alert_type=rule.alert_type,
                        message=msg,
                        magnitude_pct=trend.change_7d_pct,
                        direction="up" if trend.change_7d_pct > 0 else "down",
                        latest_rate=float(trend.avg_7d_usd) if trend.avg_7d_usd else None,
                        mean_30d=float(trend.avg_30d_usd) if trend.avg_30d_usd else None,
                        pattern_type="one_day",
                        duration_days=1,
                        last_event_date=target_date,
                    )
                    session.add(alert)
                    new_alerts.append(alert)
                    triggered += 1

            # 2. Threshold Above / Below rules
            elif rule.alert_type in ("threshold_above", "threshold_below"):
                rate_stmt = (
                    select(FreightRate)
                    .where(
                        FreightRate.trade_lane == rule.trade_lane,
                        FreightRate.rate_date <= target_date,
                    )
                    .order_by(FreightRate.rate_date.desc())
                    .limit(1)
                )
                rate = (await session.execute(rate_stmt)).scalar_one_or_none()
                if not rate:
                    continue

                # 48-hour freshness guard (must be within 2 days of evaluation date)
                freshness_limit = target_date - timedelta(days=2)
                if rate.rate_date < freshness_limit:
                    continue

                rate_val = float(rate.rate_usd)
                target_val = float(rule.target_usd or 0.0)
                is_triggered = False
                msg = ""

                if rule.alert_type == "threshold_above" and rate_val >= target_val:
                    is_triggered = True
                    msg = f"Rate of ${rate_val:.2f} is above threshold target of ${target_val:.2f} on {rule.trade_lane}."
                elif rule.alert_type == "threshold_below" and rate_val <= target_val:
                    is_triggered = True
                    msg = f"Rate of ${rate_val:.2f} is below threshold target of ${target_val:.2f} on {rule.trade_lane}."

                if is_triggered:
                    existing_alert_stmt = select(RateAlert).where(
                        RateAlert.user_id == rule.user_id,
                        RateAlert.trade_lane == rule.trade_lane,
                        RateAlert.alert_type == rule.alert_type,
                        RateAlert.last_event_date == target_date,
                    )
                    existing_alert = (await session.execute(existing_alert_stmt)).scalar_one_or_none()
                    if existing_alert:
                        continue

                    alert = RateAlert(
                        user_id=rule.user_id,
                        trade_lane=rule.trade_lane,
                        alert_type=rule.alert_type,
                        message=msg,
                        latest_rate=rate_val,
                        pattern_type="one_day",
                        duration_days=1,
                        last_event_date=target_date,
                    )
                    session.add(alert)
                    new_alerts.append(alert)
                    triggered += 1

        await session.commit()

        # Publish triggered alerts to Redis Pub/Sub for real-time WebSocket distribution
        for alert in new_alerts:
            await publish_alert(alert)

    logger.info("alert_evaluation_completed", triggered=triggered)
    return {"triggered": triggered}


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def evaluate_rate_alerts(self):
    try:
        return asyncio.run(_run_alert_evaluation())
    except Exception as exc:
        raise self.retry(exc=exc) from exc
