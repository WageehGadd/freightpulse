from datetime import date, datetime, timedelta
from app.models import CarrierAdvisory


async def _seed_advisory(
    db_session,
    carrier="MSC",
    advisory_type="surcharge",
    lanes=None,
    impact_severity=None,
):
    adv = CarrierAdvisory(
        carrier=carrier,
        advisory_type=advisory_type,
        title=f"{carrier} test advisory",
        raw_text="Original source text.",
        summary="AI-generated summary.",
        impact_severity=impact_severity,
        affected_lanes=lanes or [],
        effective_date=date.today(),
        published_at=datetime.utcnow(),
    )
    db_session.add(adv)
    await db_session.commit()
    return adv


async def test_carrier_advisories_filter_by_carrier(client, db_session, auth_headers):
    await _seed_advisory(db_session, carrier="MSC")
    await _seed_advisory(db_session, carrier="Maersk")

    response = await client.get(
        "/api/v1/carriers/advisories", params={"carrier": "MSC"}, headers=auth_headers
    )
    advisories = response.json()["advisories"]
    assert len(advisories) == 1
    assert advisories[0]["carrier"] == "MSC"
    assert advisories[0]["impact_severity"] is None


async def test_carrier_advisories_returns_ai_impact_severity(client, db_session, auth_headers):
    await _seed_advisory(db_session, impact_severity="high")

    response = await client.get("/api/v1/carriers/advisories", headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["advisories"][0]["impact_severity"] == "high"


async def test_carrier_advisories_filter_by_affected_lane(client, db_session, auth_headers):
    await _seed_advisory(db_session, carrier="MSC", lanes=["Egypt-Europe"])
    await _seed_advisory(db_session, carrier="Maersk", lanes=["UAE-Asia"])

    response = await client.get(
        "/api/v1/carriers/advisories",
        params={"affected_lane": "Egypt-Europe"},
        headers=auth_headers,
    )
    advisories = response.json()["advisories"]
    assert len(advisories) == 1
    assert advisories[0]["carrier"] == "MSC"


async def test_carrier_advisories_ordered_by_newest_first(client, db_session, auth_headers):
    old = CarrierAdvisory(
        carrier="MSC", advisory_type="surcharge", title="Old",
        published_at=datetime.utcnow() - timedelta(days=5),
    )
    new = CarrierAdvisory(
        carrier="MSC", advisory_type="surcharge", title="New",
        published_at=datetime.utcnow(),
    )
    db_session.add_all([old, new])
    await db_session.commit()

    response = await client.get("/api/v1/carriers/advisories", headers=auth_headers)
    advisories = response.json()["advisories"]
    assert advisories[0]["title"] == "New"
