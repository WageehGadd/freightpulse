import asyncio
import json
# pyrefly: ignore [missing-import]
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.main import app
from app.config import settings
from app.websocket_manager import manager
from app.alert_publisher import publish_alert, format_alert_payload


def test_websocket_auth_rejection():
    """Unauthenticated client should be rejected with 1008 code."""
    client = TestClient(app)
    # If API_KEY is set and wrong key is sent, connection should close with 1008
    with pytest.raises(Exception):
        with client.websocket_connect("/api/v1/ws/alerts/user_test_1", headers={"X-API-Key": "wrong_key"}):
            pass


def test_websocket_connect_with_header():
    """Client with valid X-API-Key header can connect and send ping."""
    client = TestClient(app)
    headers = {"X-API-Key": settings.API_KEY}
    with client.websocket_connect("/api/v1/ws/alerts/user_test_2", headers=headers) as websocket:
        # Send heartbeat ping
        websocket.send_text(json.dumps({"type": "ping"}))
        response = websocket.receive_json()
        assert response.get("type") == "pong"


def test_websocket_connect_with_query_param():
    """Client with valid api_key query param can connect and receive pong."""
    client = TestClient(app)
    url = f"/api/v1/ws/alerts/user_test_3?api_key={settings.API_KEY}"
    with client.websocket_connect(url) as websocket:
        websocket.send_text(json.dumps({"type": "ping"}))
        response = websocket.receive_json()
        assert response.get("type") == "pong"


def test_websocket_root_path_connect():
    """Root path /ws/alerts/{user_id} should also be accessible."""
    client = TestClient(app)
    url = f"/ws/alerts/user_test_root?api_key={settings.API_KEY}"
    with client.websocket_connect(url) as websocket:
        websocket.send_text(json.dumps({"type": "ping"}))
        response = websocket.receive_json()
        assert response.get("type") == "pong"


@pytest.mark.asyncio
async def test_connection_manager_broadcast():
    """Test ConnectionManager in-memory direct delivery and broadcast."""
    class MockWebSocket:
        def __init__(self):
            self.messages = []
        async def accept(self):
            pass
        async def send_json(self, data):
            self.messages.append(data)

    test_mgr = manager
    mock_ws_1 = MockWebSocket()
    mock_ws_2 = MockWebSocket()

    await test_mgr.connect("user_100", mock_ws_1)
    await test_mgr.connect("user_200", mock_ws_2)

    # Broadcast to specific user
    alert_payload = {
        "alert_type": "rate_spike",
        "trade_lane": "Egypt-China",
        "message": "Spike detected",
    }
    delivered = await test_mgr.broadcast_to_user("user_100", alert_payload)
    assert delivered == 1
    assert len(mock_ws_1.messages) == 1
    assert mock_ws_1.messages[0]["message"] == "Spike detected"
    assert len(mock_ws_2.messages) == 0

    # Broadcast to all
    global_payload = {"alert_type": "port_congestion", "message": "Port delay"}
    delivered_all = await test_mgr.broadcast_to_all(global_payload)
    assert delivered_all == 2
    assert len(mock_ws_1.messages) == 2
    assert len(mock_ws_2.messages) == 1

    await test_mgr.disconnect("user_100", mock_ws_1)
    await test_mgr.disconnect("user_200", mock_ws_2)


def test_format_alert_payload():
    """Verify uniform alert payload formatting."""
    raw_alert = {
        "id": "123",
        "alert_type": "rate_spike",
        "trade_lane": "UAE-Europe",
        "message": "Rate up by 15%",
        "magnitude_pct": 15.0,
    }
    formatted = format_alert_payload(raw_alert, user_id="user_123")
    assert formatted["user_id"] == "user_123"
    assert formatted["alert_type"] == "rate_spike"
    assert formatted["trade_lane"] == "UAE-Europe"
    assert "timestamp" in formatted


def test_test_alert_endpoint():
    """Verify the /api/v1/ws/test-alert trigger endpoint."""
    client = TestClient(app)
    response = client.post(
        "/api/v1/ws/test-alert",
        json={
            "user_id": "test_user_abc",
            "trade_lane": "Egypt-China",
            "alert_type": "rate_spike",
            "message": "Testing real-time push",
            "magnitude_pct": 10.5,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["alert"]["trade_lane"] == "Egypt-China"
