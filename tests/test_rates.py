from datetime import date, timedelta
from app.models import FreightRate, RateTrend


async def _seed_rate(db_session, trade_lane="Shanghai-Europe", container_type="40ft", days_ago=0, rate=2800.0):
    rate_date = date.today() - timedelta(days=days_ago)
    fr = FreightRate(
        source="SCFI",
        trade_lane=trade_lane,
        origin_port="Shanghai",
        dest_region="Europe",
        container_type=container_type,
        rate_usd=rate,
        rate_date=rate_date,
    )
    db_session.add(fr)
    await db_session.commit()
    return fr


async def test_rates_all_empty(client, auth_headers):
    response = await client.get("/api/v1/rates/all", headers=auth_headers)
    assert response.status_code == 200
    assert response.json() == {"lanes": []}


async def test_rates_all_returns_latest_rate(client, db_session, auth_headers):
    await _seed_rate(db_session, days_ago=1, rate=2700.0)
    await _seed_rate(db_session, days_ago=0, rate=2850.0)  

    response = await client.get("/api/v1/rates/all", headers=auth_headers)
    assert response.status_code == 200
    lanes = response.json()["lanes"]
    assert len(lanes) == 1
    assert lanes[0]["current_rate_usd"] == 2850.0


async def test_rates_lane_not_found_returns_404(client, auth_headers):
    response = await client.get("/api/v1/rates/NonExistentLane", headers=auth_headers)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


async def test_rates_lane_returns_history(client, db_session, auth_headers):
    await _seed_rate(db_session, days_ago=5, rate=2700.0)
    await _seed_rate(db_session, days_ago=0, rate=2850.0)

    response = await client.get("/api/v1/rates/Shanghai-Europe", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["current_rate"] == 2850.0
    assert len(data["history"]) == 2


async def test_rates_compare_calculates_percentages(client, db_session, auth_headers):
    await _seed_rate(db_session, days_ago=3, rate=2000.0)
    await _seed_rate(db_session, days_ago=0, rate=2200.0)

    response = await client.get(
        "/api/v1/rates/compare",
        params={"trade_lane": "Shanghai-Europe"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["current_rate"] == 2200.0
    assert data["avg_7d"] == 2100.0  
    assert data["vs_7d_pct"] > 0  


async def test_rates_endpoint_requires_api_key(client):
    response = await client.get("/api/v1/rates/all")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"