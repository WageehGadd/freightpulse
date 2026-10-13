import asyncio
import json
from datetime import datetime, timezone
from typing import Dict, Set, Optional, Any
from fastapi import WebSocket, WebSocketDisconnect
# pyrefly: ignore [missing-import]
import structlog

from app.config import settings
from app.redis_client import get_redis

logger = structlog.get_logger()


class ConnectionManager:
    """
    Manages active WebSocket connections per user and facilitates real-time
    alert forwarding from Redis Pub/Sub channels to connected frontend clients.
    """

    def __init__(self) -> None:
        # Maps user_id string to a set of active WebSockets
        self.active_connections: Dict[str, Set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, user_id: str, websocket: WebSocket) -> None:
        """Accept connection and register websocket under the given user_id."""
        await websocket.accept()
        async with self._lock:
            if user_id not in self.active_connections:
                self.active_connections[user_id] = set()
            self.active_connections[user_id].add(websocket)
        logger.info("websocket_client_connected", user_id=user_id, total_clients=self.get_total_connections())

    async def disconnect(self, user_id: str, websocket: WebSocket) -> None:
        """Unregister websocket and clean up empty user buckets."""
        async with self._lock:
            if user_id in self.active_connections:
                self.active_connections[user_id].discard(websocket)
                if not self.active_connections[user_id]:
                    del self.active_connections[user_id]
        logger.info("websocket_client_disconnected", user_id=user_id, total_clients=self.get_total_connections())

    def get_total_connections(self) -> int:
        return sum(len(connections) for connections in self.active_connections.values())

    async def send_personal_message(self, message: dict, websocket: WebSocket) -> bool:
        """Send JSON message to a single websocket connection."""
        try:
            await websocket.send_json(message)
            return True
        except Exception as exc:
            logger.warning("websocket_send_failed", error=str(exc))
            return False

    async def broadcast_to_user(self, user_id: str, message: dict) -> int:
        """Send JSON message to all active connections of a specific user."""
        targets = list(self.active_connections.get(user_id, []))
        delivered = 0
        for ws in targets:
            success = await self.send_personal_message(message, ws)
            if success:
                delivered += 1
        return delivered

    async def broadcast_to_all(self, message: dict) -> int:
        """Broadcast JSON message to every connected client."""
        delivered = 0
        for user_id in list(self.active_connections.keys()):
            delivered += await self.broadcast_to_user(user_id, message)
        return delivered

    async def verify_auth(self, websocket: WebSocket, requested_user_id: Optional[str] = None, db_session=None) -> bool:
        """
        Authenticate WebSocket connection and enforce tenant isolation:
        1. X-API-Key header or api_key / key query param
        2. Bearer JWT access token from Authorization header or token query param
        3. Enforce that the authenticated user owns requested_user_id
        Fails closed on missing credentials or mismatched user ownership.
        """
        import uuid
        from app.config import settings

        api_key = (
            websocket.headers.get("X-API-Key")
            or websocket.headers.get("x-api-key")
            or websocket.query_params.get("api_key")
            or websocket.query_params.get("key")
        )
        bearer_token = (
            websocket.headers.get("Authorization")
            or websocket.query_params.get("token")
        )
        if bearer_token and bearer_token.startswith("Bearer "):
            bearer_token = bearer_token[7:].strip()

        # 1. Verify JWT access token if provided (preferred for browser WebSocket clients)
        if bearer_token:
            try:
                from app.auth.security import decode_access_token
                payload = decode_access_token(bearer_token)
                if payload and payload.get("sub"):
                    token_user_id = str(payload.get("sub"))
                    if requested_user_id and token_user_id != str(requested_user_id):
                        logger.warning("websocket_jwt_user_mismatch", token_user=token_user_id, requested_user=requested_user_id)
                        return False
                    return True
            except Exception as exc:
                logger.warning("websocket_jwt_auth_failed", error=str(exc))

        # 2. Allow master API key only in non-production environments for automated integration testing
        if settings.API_KEY and api_key == settings.API_KEY:
            if getattr(settings, "ENV", "development") != "production":
                return True
            logger.warning("websocket_master_key_bypass_rejected_in_production")
            return False

        # 3. Verify API key against database and check user ownership
        if api_key:
            from app.auth.security import hash_api_key
            from app.models.api_key import ApiKey
            from sqlalchemy import select

            key_hash = hash_api_key(api_key)

            async def _check_api_key(session):
                stmt = select(ApiKey).where(ApiKey.key_hash == key_hash)
                record = (await session.execute(stmt)).scalar_one_or_none()
                if not record:
                    return False
                is_valid = getattr(record, "is_active", True) is True and getattr(record, "revoked_at", None) is None
                if not is_valid:
                    logger.warning("websocket_auth_key_inactive", key_prefix=getattr(record, "key_prefix", None))
                    return False
                if requested_user_id:
                    try:
                        req_uuid = uuid.UUID(str(requested_user_id))
                        if record.user_id != req_uuid:
                            logger.warning("websocket_auth_user_mismatch", key_user=str(record.user_id), requested_user=str(requested_user_id))
                            return False
                    except ValueError:
                        if str(record.user_id) != str(requested_user_id):
                            logger.warning("websocket_auth_user_mismatch", key_user=str(record.user_id), requested_user=str(requested_user_id))
                            return False
                return True

            try:
                if db_session:
                    return await _check_api_key(db_session)
                else:
                    from app.database import AsyncSessionLocal
                    async with AsyncSessionLocal() as session:
                        return await _check_api_key(session)
            except Exception as exc:
                logger.warning("websocket_db_auth_check_failed", error=str(exc))

        # Fail closed: unauthenticated connections are strictly rejected
        return False

    async def subscribe_and_relay(self, user_id: str, websocket: WebSocket) -> None:
        """
        Subscribe to user-specific channel (alerts:{user_id}) and global broadcast
        channel (alerts:broadcast) in Redis and relay incoming alerts to the WebSocket.
        Also handles client ping/pong and disconnects cleanly.
        """
        redis = get_redis()
        pubsub = redis.pubsub()
        user_channel = f"alerts:{user_id}"
        broadcast_channel = "alerts:broadcast"
        all_channel = "alerts:all"

        stop_event = asyncio.Event()

        try:
            await pubsub.subscribe(user_channel, broadcast_channel, all_channel)
            logger.info("websocket_subscribed_channels", user_id=user_id, channels=[user_channel, broadcast_channel, all_channel])
        except Exception as exc:
            logger.warning("redis_pubsub_subscribe_failed", error=str(exc))
            # Continue even if Redis fails so client can still ping/pong

        # Task to poll messages from Redis Pub/Sub without hanging on shutdown
        async def _redis_listener():
            try:
                while not stop_event.is_set():
                    try:
                        message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.5)
                        if message and message.get("type") == "message":
                            data = message.get("data")
                            if isinstance(data, str):
                                try:
                                    payload = json.loads(data)
                                except Exception:
                                    payload = {"message": data, "timestamp": datetime.now(timezone.utc).isoformat()}
                            elif isinstance(data, dict):
                                payload = data
                            else:
                                payload = {"raw": str(data)}

                            await websocket.send_json(payload)
                    except (asyncio.CancelledError, GeneratorExit):
                        break
                    except Exception as exc:
                        if stop_event.is_set():
                            break
                        await asyncio.sleep(0.5)
            except (asyncio.CancelledError, GeneratorExit):
                pass
            except Exception as exc:
                logger.warning("redis_listener_error", user_id=user_id, error=str(exc))

        # Task to receive client messages (e.g. heartbeat ping/pong)
        async def _client_receiver():
            try:
                while not stop_event.is_set():
                    data = await websocket.receive_text()
                    try:
                        parsed = json.loads(data)
                        if isinstance(parsed, dict) and parsed.get("type") == "ping":
                            await websocket.send_json({
                                "type": "pong",
                                "timestamp": datetime.now(timezone.utc).isoformat()
                            })
                    except Exception:
                        if data.strip().lower() == "ping":
                            await websocket.send_text("pong")
            except (WebSocketDisconnect, asyncio.CancelledError, GeneratorExit):
                pass
            except Exception as exc:
                if not stop_event.is_set():
                    logger.warning("websocket_receiver_error", user_id=user_id, error=str(exc))
            finally:
                stop_event.set()

        listener_task = asyncio.create_task(_redis_listener())
        receiver_task = asyncio.create_task(_client_receiver())

        try:
            # Wait until either the client disconnects or an error occurs
            done, pending = await asyncio.wait(
                [listener_task, receiver_task],
                return_when=asyncio.FIRST_COMPLETED,
            )
        finally:
            stop_event.set()
            for task in [listener_task, receiver_task]:
                if not task.done():
                    task.cancel()
            try:
                await pubsub.unsubscribe(user_channel, broadcast_channel, all_channel)
                await pubsub.aclose()
            except Exception:
                pass


# Global singleton instance
manager = ConnectionManager()
