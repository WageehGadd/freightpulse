import json
from datetime import datetime, timezone

from app.models import RateAlert
from app.redis_client import get_redis


async def publish_alert(alert: RateAlert) -> None:
    """Publish a persisted alert to its user's real-time Redis channel."""
    created_at = alert.created_at or datetime.now(timezone.utc)
    payload = {
        "id": str(alert.id),
        "alert_type": alert.alert_type,
        "trade_lane": alert.trade_lane,
        "message": alert.message,
        "magnitude_pct": alert.magnitude_pct,
        "timestamp": created_at.isoformat(),
    }
    await get_redis().publish(f"alerts:{alert.user_id}", json.dumps(payload))
