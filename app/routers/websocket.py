from typing import Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, status
from pydantic import BaseModel
# pyrefly: ignore [missing-import]
import structlog

from app.websocket_manager import manager
from app.alert_publisher import publish_alert
from app.auth.security import get_current_admin_user
from app.models.user import User

logger = structlog.get_logger()

router = APIRouter()


class TestAlertRequest(BaseModel):
    user_id: Optional[str] = None
    trade_lane: Optional[str] = "Egypt-China"
    alert_type: Optional[str] = "rate_spike"
    message: Optional[str] = "Test Real-Time Alert: Freight rates spiked by 12.5% on Egypt-China"
    magnitude_pct: Optional[float] = 12.5
    severity: Optional[str] = "elevated"


@router.websocket("/ws/alerts/{user_id}")
async def alerts_websocket(websocket: WebSocket, user_id: str):
    """
    WebSocket endpoint for real-time freight alerts.
    Subscribes the client to user-specific alerts and network-wide broadcast alerts.
    Requires a user API key in the X-API-Key header. The key must belong to the
    same UUID in the URL; service/master keys cannot impersonate tenants.
    """
    is_authenticated = await manager.verify_auth(websocket, user_id)
    if not is_authenticated:
        logger.warning("websocket_auth_failed", user_id=user_id)
        await websocket.close(code=1008)  # 1008 = Policy Violation / Unauthorized
        return

    await manager.connect(user_id, websocket)

    try:
        await manager.subscribe_and_relay(user_id, websocket)
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.warning("websocket_session_error", user_id=user_id, error=str(exc))
    finally:
        await manager.disconnect(user_id, websocket)


@router.post("/ws/test-alert", status_code=status.HTTP_200_OK)
async def trigger_test_alert(req: TestAlertRequest, current_user: User = Depends(get_current_admin_user)):
    """
    Trigger a test alert over WebSocket for developer testing and verification.
    """
    # An administrator may test delivery only for their own tenant.  This keeps
    # the diagnostic endpoint from becoming a cross-tenant message injector.
    if req.user_id is not None and req.user_id != str(current_user.id):
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Test alerts may target only the current user")
    payload = {
        "id": "test-" + req.alert_type,
        "user_id": str(current_user.id),
        "trade_lane": req.trade_lane,
        "alert_type": req.alert_type,
        "message": req.message,
        "magnitude_pct": req.magnitude_pct,
        "severity": req.severity,
    }
    await publish_alert(payload, user_id=str(current_user.id))
    return {
        "status": "success",
        "message": "Test alert published to Redis Pub/Sub",
        "alert": payload,
    }
