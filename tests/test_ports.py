from datetime import datetime, timedelta
from app.models import PortCongestion


async def test_ports_congestion_map_empty(client, auth_headers):
    response = await client.get("/api/v1/ports/congestion-map", headers=auth_headers)
    assert response.status_code == 200
    assert response.json() == {"ports": []}


async def test_ports_congestion_map_returns_latest(client, db_session, auth_headers):
    db_session.add(
        PortCongestion(
            port_code="EGPSD",
            port_name="Port Said",
            congestion_index=45.0,
            severity="normal",
            measured_at=datetime.utcnow() - timedelta(hours=6),
        )
    )
    db_session.add(
        PortCongestion(
            port_code="EGPSD",
            port_name="Port Said",
            congestion_index=62.0,  # the latest congestion index
            severity="elevated",
            measured_at=datetime.utcnow(),
        )
    )
    await db_session.commit()

    response = await client.get("/api/v1/ports/congestion-map", headers=auth_headers)
    ports = response.json()["ports"]
    assert len(ports) == 1
    assert ports[0]["congestion_index"] == 62.0
    assert ports[0]["latitude"] is not None  # the latitude is not None


async def test_port_congestion_by_code_not_found(client, auth_headers):
    response = await client.get("/api/v1/ports/ZZZZZ/congestion", headers=auth_headers)
    assert response.status_code == 404


async def test_port_congestion_by_code_case_insensitive(client, db_session, auth_headers):
    db_session.add(
        PortCongestion(
            port_code="AEJEA",
            port_name="Jebel Ali",
            congestion_index=78.0,
            severity="critical",
            measured_at=datetime.utcnow(),
        )
    )
    await db_session.commit()

    response = await client.get("/api/v1/ports/aejea/congestion", headers=auth_headers)  # حروف صغيرة
    assert response.status_code == 200
    assert response.json()["port_code"] == "AEJEA"