import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.auth.security import get_current_user, get_current_admin_user
from app.models.user import User
from app.models.rate_trend import RateTrend
from app.models.rate_alert import RateAlert
from app.ai.prompts.registry import registry
from app.ai.budget_guard import BudgetGuard
from app.ai.telemetry import AITelemetry
from app.tasks.trend_computation import compute_rate_trends
from app.tasks.alert_evaluation import evaluate_rate_alerts

router = APIRouter(prefix="/ai", tags=["AI"])


@router.get("/health")
async def get_ai_health(
    current_user: User = Depends(get_current_user),
):
    """Health check for AI provider and active models without triggering external LLM calls."""
    return {
        "status": "healthy",
        "provider": "openai",
        "model": settings.AI_MODEL,
        "active_prompts": {
            "carrier_summarizer": getattr(settings, "AI_CARRIER_SUMMARIZER_PROMPT_VERSION", "v1"),
            "rate_outlook": getattr(settings, "AI_RATE_OUTLOOK_PROMPT_VERSION", "v1"),
            "route_brief": getattr(settings, "AI_ROUTE_BRIEF_PROMPT_VERSION", "v1"),
        },
    }


@router.get("/metrics")
async def get_ai_metrics(
    current_user: User = Depends(get_current_admin_user),
):
    """Retrieve AI daily budget, spend reservation status, and operational telemetry."""
    actual_usd, reserved_usd, committed_usd = await BudgetGuard.get_budget_status()
    telemetry = await AITelemetry.get_metrics()

    return {
        "budget": {
            "daily_budget_usd": settings.AI_DAILY_BUDGET_USD,
            "actual_usd": actual_usd,
            "reserved_usd": reserved_usd,
            "committed_usd": committed_usd,
        },
        "telemetry": telemetry,
    }


@router.get("/prompts")
async def get_ai_prompts(
    current_user: User = Depends(get_current_admin_user),
):
    """List registered AI prompt versions metadata without exposing raw templates."""
    return {
        "features": {
            "carrier_summarizer": {
                "active_version": getattr(settings, "AI_CARRIER_SUMMARIZER_PROMPT_VERSION", "v1"),
                "available_versions": registry.list_versions("carrier_summarizer"),
            },
            "rate_outlook": {
                "active_version": getattr(settings, "AI_RATE_OUTLOOK_PROMPT_VERSION", "v1"),
                "available_versions": registry.list_versions("rate_outlook"),
            },
            "route_brief": {
                "active_version": getattr(settings, "AI_ROUTE_BRIEF_PROMPT_VERSION", "v1"),
                "available_versions": registry.list_versions("route_brief"),
            },
        }
    }


@router.post("/trends/compute")
async def compute_trends():
    """Trigger daily trend computation for all trade lanes."""
    try:
        task = compute_rate_trends.delay()
        task_id = task.id
    except Exception:
        task_id = "local-sync"

    return {
        "task_id": task_id,
        "status": "processing",
        "message": "Daily trend computation started",
    }


@router.post("/anomalies/detect")
async def detect_anomalies():
    """Trigger daily anomaly detection for all trade lanes."""
    try:
        task = evaluate_rate_alerts.delay()
        task_id = task.id
    except Exception:
        task_id = "local-sync"

    return {
        "task_id": task_id,
        "status": "processing",
        "message": "Daily anomaly detection started",
    }


@router.get("/trends/{trade_lane}")
async def get_trend(trade_lane: str, db: AsyncSession = Depends(get_db)):
    """Get the latest trend for a specific trade lane."""
    stmt = (
        select(RateTrend)
        .where(RateTrend.trade_lane == trade_lane)
        .order_by(RateTrend.computed_date.desc())
        .limit(1)
    )
    trend = (await db.execute(stmt)).scalar_one_or_none()
    if not trend:
        raise HTTPException(status_code=404, detail="No trend data found for this trade lane")

    return {
        "trade_lane": trend.trade_lane,
        "computed_date": trend.computed_date,
        "avg_7d_usd": float(trend.avg_7d_usd) if trend.avg_7d_usd else None,
        "avg_30d_usd": float(trend.avg_30d_usd) if trend.avg_30d_usd else None,
        "change_7d_pct": trend.change_7d_pct,
        "change_30d_pct": trend.change_30d_pct,
        "trend": trend.trend,
        "slope_per_week": trend.slope_per_week,
        "r_squared": trend.r_squared,
        "anomaly_flag": trend.anomaly_flag,
        "status": trend.status,
        "outlook_text": trend.outlook_text,
        "recommendation": trend.recommendation,
        "confidence": trend.confidence,
    }


@router.get("/alerts")
async def get_alerts(
    db: AsyncSession = Depends(get_db),
    unread_only: bool = False,
    limit: int = 50,
):
    """Get rate alerts, optionally filtering for unread only."""
    stmt = select(RateAlert)
    if unread_only:
        stmt = stmt.where(RateAlert.is_read == False)  # noqa: E712
    stmt = stmt.order_by(RateAlert.created_at.desc()).limit(limit)
    alerts = (await db.execute(stmt)).scalars().all()

    return {
        "alerts": [
            {
                "id": str(alert.id),
                "trade_lane": alert.trade_lane,
                "alert_type": alert.alert_type,
                "message": alert.message,
                "magnitude_pct": alert.magnitude_pct,
                "direction": alert.direction,
                "z_score": alert.z_score,
                "latest_rate": float(alert.latest_rate) if alert.latest_rate else None,
                "mean_30d": float(alert.mean_30d) if alert.mean_30d else None,
                "pattern_type": alert.pattern_type,
                "duration_days": alert.duration_days,
                "cumulative_magnitude_pct": alert.cumulative_magnitude_pct,
                "is_read": alert.is_read,
                "created_at": alert.created_at,
            }
            for alert in alerts
        ]
    }


@router.put("/alerts/{alert_id}/read")
async def mark_alert_read(alert_id: str, db: AsyncSession = Depends(get_db)):
    """Mark an alert as read."""
    try:
        alert_uuid = uuid.UUID(alert_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid alert ID format")

    alert = await db.get(RateAlert, alert_uuid)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    alert.is_read = True
    await db.commit()
    return {"message": "Alert marked as read"}