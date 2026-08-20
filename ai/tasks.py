from datetime import date, datetime, timedelta

import pandas as pd
from celery import shared_task
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ai.database import FreightRate, RateAlert, RateTrend, SessionLocal
from ai.logging import get_logger
from ai.modules.rate_anomaly_detector import detect_anomalies
from ai.modules.rate_trend_computer import compute_trend
from ai.schemas.ai_outputs import RateAnomalySchema, RateTrendSchema

logger = get_logger(__name__)

# --- Configuration constants (no magic numbers) -------------------------------
TREND_WINDOW_DAYS = 30
ANOMALY_THRESHOLD = 2.5
RETRY_COUNTDOWN_SECONDS = 60
EVENT_CONTINUATION_WINDOW_DAYS = 7  # window to treat a new anomaly as continuation


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
def _load_recent_rates(db: Session, days: int = TREND_WINDOW_DAYS) -> pd.DataFrame:
    """Load last `days` of freight rates in ONE query (avoids N+1)."""
    cutoff = date.today() - timedelta(days=days)
    query = db.query(
        FreightRate.trade_lane,
        FreightRate.rate_date,
        FreightRate.rate_usd,
    ).filter(FreightRate.rate_date >= cutoff)
    rows = query.all()
    df = pd.DataFrame(
        [
            {
                "trade_lane": r.trade_lane,
                "rate_date": r.rate_date,
                "rate_usd": float(r.rate_usd) if r.rate_usd is not None else 0.0,
            }
            for r in rows
        ]
    )
    if df.empty:
        df = pd.DataFrame(columns=["trade_lane", "rate_date", "rate_usd"])
    return df



# ---------------------------------------------------------------------------
# Persistence helpers — AI-1 (trends)
# ---------------------------------------------------------------------------
def _upsert_trend(db: Session, trend: RateTrendSchema) -> None:
    """Insert or update the trend row for (trade_lane, computed_date)."""
    values = {
        "avg_7d_usd": trend.avg_7d_usd,
        "avg_30d_usd": trend.avg_30d_usd,
        "change_7d_pct": trend.change_7d_pct,
        "change_30d_pct": trend.change_30d_pct,
        "trend": trend.trend,
        "slope_per_week": trend.slope_per_week,
        "r_squared": trend.r_squared,
    }
    existing = (
        db.query(RateTrend)
        .filter_by(trade_lane=trend.trade_lane, computed_date=trend.computed_date)
        .first()
    )
    if existing:
        for key, value in values.items():
            setattr(existing, key, value)
    else:
        db.add(
            RateTrend(
                trade_lane=trend.trade_lane,
                computed_date=trend.computed_date,
                **values,
            )
        )
    db.commit()


# ---------------------------------------------------------------------------
# Persistence helpers — AI-2 (alerts & multi-day events)
# ---------------------------------------------------------------------------
def _find_active_event(db: Session, trade_lane: str, alert_type: str) -> RateAlert | None:
    """Latest unread alert of same type/lane within the continuation window."""
    cutoff = datetime.utcnow() - timedelta(days=EVENT_CONTINUATION_WINDOW_DAYS)
    return (
        db.query(RateAlert)
        .filter(
            RateAlert.trade_lane == trade_lane,
            RateAlert.alert_type == alert_type,
            RateAlert.is_read.is_(False),
            RateAlert.created_at >= cutoff,
        )
        .order_by(RateAlert.created_at.desc())
        .first()
    )


def _persist_alert(db: Session, result: RateAnomalySchema) -> None:
    """Insert a new rate_alerts row from the detector output."""
    payload = result.model_dump()
    db.add(
        RateAlert(
            user_id=payload.get("user_id"),
            trade_lane=payload["trade_lane"],
            alert_type=payload["alert_type"],
            message=payload["message"],
            magnitude_pct=payload.get("magnitude_pct"),
            direction=payload.get("direction"),
            z_score=payload.get("z_score"),
            latest_rate=payload.get("latest_rate"),
            mean_30d=payload.get("mean_30d"),
            pattern_type=payload.get("pattern_type", "one_day"),
            duration_days=payload.get("duration_days", 1),
            cumulative_magnitude_pct=payload.get("cumulative_magnitude_pct"),
            last_event_date=date.today(),
        )
    )


def _extend_event(db: Session, alert: RateAlert, result: RateAnomalySchema) -> None:
    """Extend an existing alert with a new day of a sustained event (P3 #3)."""
    alert.duration_days = (alert.duration_days or 1) + 1
    alert.pattern_type = "sustained"
    alert.magnitude_pct = result.magnitude_pct
    alert.cumulative_magnitude_pct = result.cumulative_magnitude_pct
    alert.z_score = result.z_score
    alert.latest_rate = result.latest_rate
    alert.message = result.message
    alert.last_event_date = date.today()
    alert.updated_at = datetime.utcnow()


def _set_anomaly_flag(db: Session, trade_lane: str) -> None:
    """Flag the most recent trend row for this lane as anomalous."""
    trend_row = (
        db.query(RateTrend)
        .filter_by(trade_lane=trade_lane)
        .order_by(RateTrend.computed_date.desc())
        .first()
    )
    if trend_row is not None:
        trend_row.anomaly_flag = True
    else:
        logger.warning("anomaly_flag_no_trend_row", trade_lane=trade_lane)


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------
@shared_task(name="ai.tasks.run_daily_trend_computation", bind=True, max_retries=3)
def run_daily_trend_computation(self) -> dict:
    """AI-1: compute 30-day trends for every trade lane and upsert to rate_trends."""
    started = datetime.utcnow()
    db = SessionLocal()
    try:
        rates_df = _load_recent_rates(db)
        if rates_df.empty:
            logger.warning("trend_computation_no_data")
            return {"lanes_upserted": 0, "lanes_skipped": 0}

        lanes_upserted, lanes_skipped = 0, 0
        for lane, lane_data in rates_df.groupby("trade_lane"):
            try:
                lane_data = lane_data.sort_values(by="rate_date").tail(TREND_WINDOW_DAYS)
                trend = compute_trend(str(lane), lane_data)
                _upsert_trend(db, trend)
                lanes_upserted += 1
            except Exception as lane_exc:
                db.rollback()
                lanes_skipped += 1
                logger.error("trend_lane_failed", trade_lane=str(lane), error=str(lane_exc))

        duration_s = round((datetime.utcnow() - started).total_seconds(), 2)
        logger.info(
            "trend_computation_completed",
            lanes_upserted=lanes_upserted,
            lanes_skipped=lanes_skipped,
            duration_s=duration_s,
        )
        return {"lanes_upserted": lanes_upserted, "lanes_skipped": lanes_skipped}

    except SQLAlchemyError as exc:
        db.rollback()
        logger.error("trend_computation_db_error", error=str(exc))
        raise self.retry(exc=exc, countdown=RETRY_COUNTDOWN_SECONDS)
    except Exception as exc:
        db.rollback()
        logger.error("trend_computation_critical", error=str(exc))
        raise self.retry(exc=exc, countdown=RETRY_COUNTDOWN_SECONDS)
    finally:
        db.close()


@shared_task(name="ai.tasks.run_daily_anomaly_detection", bind=True, max_retries=3)
def run_daily_anomaly_detection(self) -> dict:
    """AI-2: detect anomalies, set anomaly_flag, create/extend alert events."""
    started = datetime.utcnow()
    db = SessionLocal()
    try:
        rates_df = _load_recent_rates(db)
        if rates_df.empty:
            logger.warning("anomaly_detection_no_data")
            return {
                "lanes_processed": 0,
                "alerts_created": 0,
                "duplicates_skipped": 0,
                "events_extended": 0,
            }

        lanes_processed, alerts_created = 0, 0
        duplicates_skipped, events_extended = 0, 0
        for lane, lane_data in rates_df.groupby("trade_lane"):
            try:
                series = (
                    lane_data.sort_values(by="rate_date")
                    .tail(TREND_WINDOW_DAYS)["rate_usd"]
                )
                result = detect_anomalies(
                    str(lane), series, threshold=ANOMALY_THRESHOLD, adaptive=True
                )
                lanes_processed += 1
                if result is None:
                    continue

                # Multi-day event logic (P3 #3):
                # - Same-day re-run       → deduplicate (skip entirely)
                # - New day, active event → extend the existing alert
                # - No active event       → create a new alert
                active_event = _find_active_event(db, str(lane), result.alert_type)
                if active_event is not None and active_event.last_event_date == date.today():
                    duplicates_skipped += 1
                    logger.info(
                        "alert_deduplicated",
                        trade_lane=str(lane),
                        alert_type=result.alert_type,
                    )
                elif active_event is not None:
                    _extend_event(db, active_event, result)
                    events_extended += 1
                    logger.info(
                        "alert_event_extended",
                        trade_lane=str(lane),
                        alert_type=result.alert_type,
                        duration_days=active_event.duration_days,
                    )
                else:
                    _persist_alert(db, result)
                    alerts_created += 1
                    logger.info(
                        "anomaly_detected",
                        trade_lane=str(lane),
                        alert_type=result.alert_type,
                        magnitude_pct=result.magnitude_pct,
                        threshold_used=result.threshold_used,
                        pattern_type=result.pattern_type,
                    )

                _set_anomaly_flag(db, str(lane))
                db.commit()
            except Exception as lane_exc:
                db.rollback()
                logger.error("anomaly_lane_failed", trade_lane=str(lane), error=str(lane_exc))

        duration_s = round((datetime.utcnow() - started).total_seconds(), 2)
        logger.info(
            "anomaly_detection_completed",
            lanes_processed=lanes_processed,
            alerts_created=alerts_created,
            duplicates_skipped=duplicates_skipped,
            events_extended=events_extended,
            duration_s=duration_s,
        )
        return {
            "lanes_processed": lanes_processed,
            "alerts_created": alerts_created,
            "duplicates_skipped": duplicates_skipped,
            "events_extended": events_extended,
        }

    except SQLAlchemyError as exc:
        db.rollback()
        logger.error("anomaly_detection_db_error", error=str(exc))
        raise self.retry(exc=exc, countdown=RETRY_COUNTDOWN_SECONDS)
    except Exception as exc:
        db.rollback()
        logger.error("anomaly_detection_critical", error=str(exc))
        raise self.retry(exc=exc, countdown=RETRY_COUNTDOWN_SECONDS)
    finally:
        db.close()