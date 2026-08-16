import pytest
from httpx import AsyncClient
from app.main import app
from app.database import get_db

@pytest.fixture(autouse=True)
def override_dependency(db_session):
    async def _override():
        yield db_session
    app.dependency_overrides[get_db] = _override
    yield
    app.dependency_overrides.clear()

@pytest.mark.asyncio
async def test_create_rate_spike_rule(client: AsyncClient, auth_headers):
    response = await client.post("/api/v1/alerts/rules", json={
        "trade_lane": "Egypt-Europe",
        "alert_type": "rate_spike",
        "magnitude_pct": 5.0
    }, headers=auth_headers)
    assert response.status_code == 201
    data = response.json()
    assert data["alert_type"] == "rate_spike"
    assert data["magnitude_pct"] == 5.0
    assert data["target_usd"] is None
    assert data["is_active"] is True

@pytest.mark.asyncio
async def test_create_threshold_above_rule(client: AsyncClient, auth_headers):
    response = await client.post("/api/v1/alerts/rules", json={
        "trade_lane": "Egypt-Europe",
        "alert_type": "threshold_above",
        "target_usd": 2000.0
    }, headers=auth_headers)
    assert response.status_code == 201
    data = response.json()
    assert data["alert_type"] == "threshold_above"
    assert data["target_usd"] == 2000.0
    assert data["magnitude_pct"] is None

@pytest.mark.asyncio
async def test_invalid_rule_configuration(client: AsyncClient, auth_headers):
    # rate_spike but with target_usd instead of magnitude_pct
    response = await client.post("/api/v1/alerts/rules", json={
        "trade_lane": "Egypt-Europe",
        "alert_type": "rate_spike",
        "target_usd": 1500.0
    }, headers=auth_headers)
    assert response.status_code == 422
    assert "magnitude_pct is required" in response.text

    # threshold_above with magnitude_pct instead of target_usd
    response2 = await client.post("/api/v1/alerts/rules", json={
        "trade_lane": "Egypt-Europe",
        "alert_type": "threshold_above",
        "magnitude_pct": 10.0
    }, headers=auth_headers)
    assert response2.status_code == 422
    assert "target_usd is required" in response2.text

@pytest.mark.asyncio
async def test_list_and_delete_rule(client: AsyncClient, auth_headers):
    # Create rule
    create_resp = await client.post("/api/v1/alerts/rules", json={
        "trade_lane": "UAE-Asia",
        "alert_type": "rate_drop",
        "magnitude_pct": 10.0
    }, headers=auth_headers)
    assert create_resp.status_code == 201
    rule_id = create_resp.json()["id"]

    # List rules
    list_resp = await client.get("/api/v1/alerts/rules", headers=auth_headers)
    assert list_resp.status_code == 200
    rules = list_resp.json()
    assert len(rules) == 1
    assert rules[0]["id"] == rule_id

    # Delete rule
    del_resp = await client.delete(f"/api/v1/alerts/rules/{rule_id}", headers=auth_headers)
    assert del_resp.status_code == 204

    # List rules again
    list_resp_2 = await client.get("/api/v1/alerts/rules", headers=auth_headers)
    assert list_resp_2.status_code == 200
    assert len(list_resp_2.json()) == 0

@pytest.mark.asyncio
async def test_list_events(client: AsyncClient, auth_headers):
    list_resp = await client.get("/api/v1/alerts/events", headers=auth_headers)
    assert list_resp.status_code == 200
    assert isinstance(list_resp.json(), list)
