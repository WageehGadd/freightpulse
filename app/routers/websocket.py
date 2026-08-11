import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.config import settings
from app.redis_client import get_redis


router = APIRouter()


@router.websocket("/ws/alerts/{user_id}")
async def alerts_websocket(websocket: WebSocket, user_id: str):
    """Relay Redis alert messages to a connected frontend client."""
    if websocket.headers.get("X-API-Key") != settings.API_KEY:
        await websocket.close(code=1008)
        return

    await websocket.accept()
    pubsub = get_redis().pubsub()
    await pubsub.subscribe(f"alerts:{user_id}")

    try:
        async for message in pubsub.listen():
            if message["type"] == "message":
                payload = message["data"]
                await websocket.send_json(json.loads(payload))
    except WebSocketDisconnect:
        pass
    finally:
        await pubsub.unsubscribe(f"alerts:{user_id}")
        await pubsub.aclose()
