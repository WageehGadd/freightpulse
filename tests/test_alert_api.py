# pyrefly: ignore [missing-import]
import pytest
import uuid
# pyrefly: ignore [missing-import]
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_removed_alert_rules_endpoints_return_404(client: AsyncClient, auth_headers):
    # POST /api/v1/alerts/rules should return 404
    post_resp = await client.post(
        "/api/v1/alerts/rules",
        json={
            "trade_lane": "Egypt-Europe",
            "alert_type": "rate_spike",
            "magnitude_pct": 5.0,
        },
        headers=auth_headers,
    )
    assert post_resp.status_code == 404

    # GET /api/v1/alerts/rules should return 404
    get_resp = await client.get("/api/v1/alerts/rules", headers=auth_headers)
    assert get_resp.status_code == 404

    # DELETE /api/v1/alerts/rules/{rule_id} should return 404
    del_resp = await client.delete(
        f"/api/v1/alerts/rules/{uuid.uuid4()}", headers=auth_headers
    )
    assert del_resp.status_code == 404


@pytest.mark.asyncio
async def test_removed_alert_events_endpoint_returns_404(client: AsyncClient, auth_headers):
    # GET /api/v1/alerts/events should return 404
    get_resp = await client.get("/api/v1/alerts/events", headers=auth_headers)
    assert get_resp.status_code == 404

