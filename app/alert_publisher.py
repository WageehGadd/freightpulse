import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional
import redis
# pyrefly: ignore [missing-import]
import structlog

from app.config import settings
from app.models.rate_alert import RateAlert
from app.redis_client import get_redis

logger = structlog.get_logger()


def format_alert_payload(
    alert: RateAlert | Dict[str, Any],
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Format a uniform JSON payload for real-time WebSocket distribution.
    Supports RateAlert models and custom alert dictionaries.
    """
    now_iso = datetime.now(timezone.utc).isoformat()

    if isinstance(alert, RateAlert):
        created_at = alert.created_at or datetime.now(timezone.utc)
        return {
            "id": str(alert.id),
            "user_id": str(alert.user_id) if alert.user_id else user_id,
            "alert_type": alert.alert_type or "rate_alert",
            "trade_lane": alert.trade_lane,
            "message": alert.message,
            "magnitude_pct": alert.magnitude_pct,
            "direction": alert.direction,
            "latest_rate": alert.latest_rate,
            "pattern_type": alert.pattern_type,
            "duration_days": alert.duration_days,
            "timestamp": created_at.isoformat() if hasattr(created_at, "isoformat") else now_iso,
        }

    # Dict payload
    return {
        "id": str(alert.get("id", "")),
        "user_id": str(alert.get("user_id") or user_id or ""),
        "alert_type": alert.get("alert_type", "rate_alert"),
        "trade_lane": alert.get("trade_lane"),
        "port_code": alert.get("port_code"),
        "carrier": alert.get("carrier"),
        "message": alert.get("message", ""),
        "magnitude_pct": alert.get("magnitude_pct"),
        "severity": alert.get("severity"),
        "direction": alert.get("direction"),
        "timestamp": alert.get("timestamp", now_iso),
    }


async def publish_alert(
    alert: RateAlert | Dict[str, Any],
    user_id: Optional[str] = None,
) -> None:
    """
    Publish an alert to Redis Pub/Sub asynchronously (for FastAPI handlers).
    If user_id is provided or attached to the alert, publishes to `alerts:{user_id}`.
    If no user_id is present (or 'all'/'broadcast'), publishes to `alerts:broadcast`.
    """
    payload = format_alert_payload(alert, user_id=user_id)
    target_user = payload.get("user_id") or user_id

    try:
        redis_client = get_redis()
        serialized = json.dumps(payload)

        if target_user and target_user not in ("None", "all", "broadcast", ""):
            # Publish to user-specific channel
            await redis_client.publish(f"alerts:{target_user}", serialized)
            logger.info("published_user_alert", user_id=target_user, alert_type=payload.get("alert_type"))
        else:
            # Broadcast to all connected clients
            await redis_client.publish("alerts:broadcast", serialized)
            logger.info("published_broadcast_alert", alert_type=payload.get("alert_type"))
    except Exception as exc:
        logger.warning("alert_publish_async_failed", error=str(exc))


def publish_alert_sync(
    alert: RateAlert | Dict[str, Any],
    user_id: Optional[str] = None,
) -> None:
    """
    Publish an alert to Redis Pub/Sub synchronously (for Celery workers).
    """
    payload = format_alert_payload(alert, user_id=user_id)
    target_user = payload.get("user_id") or user_id

    try:
        r = redis.from_url(settings.REDIS_URL, decode_responses=True)
        serialized = json.dumps(payload)

        if target_user and target_user not in ("None", "all", "broadcast", ""):
            r.publish(f"alerts:{target_user}", serialized)
            logger.info("published_user_alert_sync", user_id=target_user, alert_type=payload.get("alert_type"))
        else:
            r.publish("alerts:broadcast", serialized)
            logger.info("published_broadcast_alert_sync", alert_type=payload.get("alert_type"))
        r.close()
    except Exception as exc:
        logger.warning("alert_publish_sync_failed", error=str(exc))


async def publish_port_congestion_alert(
    port_code: str,
    port_name: str,
    severity: str,
    congestion_index: Optional[float] = None,
    advisory_text: Optional[str] = None,
) -> None:
    """Publish a real-time port congestion alert across the network."""
    payload = {
        "alert_type": "port_congestion",
        "port_code": port_code,
        "port_name": port_name,
        "severity": severity,
        "congestion_index": congestion_index,
        "message": advisory_text or f"Port congestion at {port_name} ({port_code}) is now {severity.upper()} (Index: {congestion_index}).",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    await publish_alert(payload)


async def publish_carrier_advisory_alert(
    carrier: str,
    title: str,
    advisory_type: str,
    affected_lanes: Optional[list] = None,
    impact_severity: Optional[str] = None,
) -> None:
    """Publish a real-time carrier advisory alert across the network."""
    lanes_text = f" on lanes: {', '.join(affected_lanes)}" if affected_lanes else ""
    payload = {
        "alert_type": "carrier_advisory",
        "carrier": carrier,
        "title": title,
        "advisory_type": advisory_type,
        "affected_lanes": affected_lanes or [],
        "severity": impact_severity or "medium",
        "message": f"[{carrier}] {title}{lanes_text}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    await publish_alert(payload)
