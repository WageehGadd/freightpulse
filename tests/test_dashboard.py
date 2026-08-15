from datetime import date, timedelta

from app.models import FreightRate


async def _seed_rate(db_session, *, days_ago: int, rate: float, lane: str):
    rate_date = date.today() - timedelta(days=days_ago)
    db_session.add(
        FreightRate(
            source="SCFI",
            trade_lane=lane,
            origin_port="Shanghai",
            dest_region="Europe",
            container_type="40ft",
            rate_usd=rate,
            rate_date=rate_date,
        )
    )
    await db_session.commit()


async def test_dashboard_returns_daily_average_rate_trend_for_last_30_days(
    client, db_session, auth_headers
):
    await _seed_rate(db_session, days_ago=2, rate=2000, lane="Shanghai-Europe")
    await _seed_rate(db_session, days_ago=2, rate=3000, lane="Shanghai-Mediterranean")
    await _seed_rate(db_session, days_ago=1, rate=2400, lane="Shanghai-Europe")
    await _seed_rate(db_session, days_ago=30, rate=1800, lane="Shanghai-Europe")

    response = await client.get("/api/v1/dashboard", headers=auth_headers)

    assert response.status_code == 200
    trend = response.json()["rate_trend_30d"]
    assert trend == [
        {"date": str(date.today() - timedelta(days=2)), "avg_rate_usd": 2500.0},
        {"date": str(date.today() - timedelta(days=1)), "avg_rate_usd": 2400.0},
    ]
