from uuid import uuid4

from app.models import RateAlert


async def _seed_alert(db_session, *, is_read=False):
    alert = RateAlert(
        user_id=uuid4(),
        trade_lane="Shanghai-Europe",
        alert_type="rate_spike",
        message="Rates increased by 18% in seven days.",
        magnitude_pct=18.0,
        is_read=is_read,
    )
    db_session.add(alert)
    await db_session.commit()
    await db_session.refresh(alert)
    return alert


async def test_alerts_can_be_filtered_to_unread(client, db_session, auth_headers):
    unread_alert = await _seed_alert(db_session, is_read=False)
    await _seed_alert(db_session, is_read=True)

    response = await client.get(
        "/api/v1/alerts", params={"unread": "true"}, headers=auth_headers
    )

    assert response.status_code == 200
    alerts = response.json()["alerts"]
    assert [alert["id"] for alert in alerts] == [str(unread_alert.id)]
    assert alerts[0]["is_read"] is False


async def test_alert_can_be_marked_as_read(client, db_session, auth_headers):
    alert = await _seed_alert(db_session)

    response = await client.patch(
        f"/api/v1/alerts/{alert.id}/read", headers=auth_headers
    )

    assert response.status_code == 200
    assert response.json() == {"id": str(alert.id), "is_read": True}


async def test_marking_unknown_alert_as_read_returns_404(client, auth_headers):
    response = await client.patch(
        f"/api/v1/alerts/{uuid4()}/read", headers=auth_headers
    )

    assert response.status_code == 404
