# pyrefly: ignore [missing-import]
import pytest
import uuid
import os
from unittest.mock import patch, AsyncMock
from datetime import date

from app.models import User, RouteBrief, CarrierAdvisory, FreightRate, RateTrend, PortCongestion
from app.tasks.route_brief_generation import generate_route_brief_async
from app.schemas.ai_outputs import RouteBriefOutput
from app.database import get_db
from app.main import app

@pytest.fixture(autouse=True)
def override_dependency(db_session):
    async def _override():
        yield db_session
    app.dependency_overrides[get_db] = _override
    yield
    app.dependency_overrides.clear()

@pytest.fixture
async def tenant_a(db_session):
    user = User(email="tenant_a@example.com")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def tenant_b(db_session):
    user = User(email="tenant_b@example.com")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def sample_brief_a(db_session, tenant_a):
    brief = RouteBrief(
        user_id=tenant_a.id,
        origin="Shanghai",
        destination="Los Angeles",
        carrier="Maersk",
        cargo_type="40ft",
        status="pending",
    )
    db_session.add(brief)
    await db_session.commit()
    await db_session.refresh(brief)
    return brief


@pytest.fixture
async def context_data(db_session):
    # Setup context
    lane = "Shanghai-Los Angeles"
    adv = CarrierAdvisory(
        carrier="Maersk",
        advisory_type="delay",
        title="Port congestion",
        raw_text="Delays expected",
        summary="Expect delays",
        affected_lanes=[lane],
        impact_severity="high",
    )
    db_session.add(adv)

    rate = FreightRate(
        source="SCFI",
        trade_lane=lane,
        origin_port="Shanghai",
        dest_region="Los Angeles",
        container_type="40ft",
        rate_usd=2500.0,
        rate_date=date.today(),
    )
    db_session.add(rate)

    trend = RateTrend(
        trade_lane=lane,
        computed_date=date.today(),
        anomaly_flag=False,
    )
    db_session.add(trend)

    port = PortCongestion(
        port_code="SHG",
        port_name="Shanghai",
        measured_at=date.today(),
    )
    db_session.add(port)

    await db_session.commit()


@pytest.fixture
def mock_generator():
    generator = AsyncMock()
    generator.generate_brief.return_value = RouteBriefOutput(
        brief_markdown="# Route Brief\n" + "Everything looks good. " * 10,
        recommendation="ship_now",
        risk_level="low"
    )
    return generator


def fake_session_factory(db_session):
    from contextlib import asynccontextmanager
    @asynccontextmanager
    async def factory():
        yield db_session
    return factory


@pytest.mark.asyncio
async def test_route_brief_success_and_pdf(db_session, sample_brief_a, context_data, mock_generator):
    result = await generate_route_brief_async(
        str(sample_brief_a.id),
        session_factory=fake_session_factory(db_session),
        generator_factory=lambda: mock_generator,
    )

    assert result["status"] == "completed"

    await db_session.refresh(sample_brief_a)
    assert sample_brief_a.status == "completed"
    assert sample_brief_a.brief_markdown == "# Route Brief\n" + "Everything looks good. " * 10
    assert sample_brief_a.pdf_path is not None
    assert os.path.exists(sample_brief_a.pdf_path)


@pytest.mark.asyncio
async def test_route_brief_ai_failure(db_session, sample_brief_a, mock_generator):
    mock_generator.generate_brief.side_effect = Exception("AI Failed")

    with pytest.raises(Exception):
        await generate_route_brief_async(
            str(sample_brief_a.id),
            session_factory=fake_session_factory(db_session),
            generator_factory=lambda: mock_generator,
            mark_failed_on_error=True
        )

    await db_session.refresh(sample_brief_a)
    assert sample_brief_a.status == "failed"
    assert sample_brief_a.error_message == "Route brief generation failed. Please try again later."
    assert sample_brief_a.pdf_path is None


@pytest.fixture
async def tenant_b_headers(db_session, tenant_b):
    from app.models.api_key import ApiKey
    from app.auth.security import hash_api_key
    plaintext_key = "fp_live_tenantB123"
    api_key = ApiKey(
        user_id=tenant_b.id,
        key_hash=hash_api_key(plaintext_key),
        key_prefix="fp_live_tenB",
        name="Test Key B"
    )
    db_session.add(api_key)
    await db_session.commit()
    return {"X-API-Key": plaintext_key}


@pytest.fixture
async def tenant_a_headers(db_session, tenant_a):
    from app.models.api_key import ApiKey
    from app.auth.security import hash_api_key
    plaintext_key = "fp_live_tenantA123"
    api_key = ApiKey(
        user_id=tenant_a.id,
        key_hash=hash_api_key(plaintext_key),
        key_prefix="fp_live_tenA",
        name="Test Key A"
    )
    db_session.add(api_key)
    await db_session.commit()
    return {"X-API-Key": plaintext_key}


@pytest.mark.asyncio
async def test_tenant_isolation_status_and_pdf(client, db_session, tenant_a_headers, tenant_b_headers, sample_brief_a):
    # Tenant A can access its own status
    res = await client.get(f"/api/v1/route-briefs/{sample_brief_a.id}/status", headers=tenant_a_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "pending"
    assert data["brief_id"] == str(sample_brief_a.id)
    assert data["brief_markdown"] is None
    assert data["recommendation"] is None
    assert data["risk_level"] is None
    assert data["error_message"] is None
    assert data["created_at"] is not None

    # Tenant B gets 404 (isolation)
    res = await client.get(f"/api/v1/route-briefs/{sample_brief_a.id}/status", headers=tenant_b_headers)
    assert res.status_code == 404

    # Tenant A attempts PDF, gets 409 (still generating)
    res = await client.get(f"/api/v1/route-briefs/{sample_brief_a.id}/pdf", headers=tenant_a_headers)
    assert res.status_code == 409

    # Complete the brief
    sample_brief_a.status = "completed"
    sample_brief_a.brief_markdown = "# Route Brief: Shanghai to Los Angeles"
    sample_brief_a.recommendation = "ship_now"
    sample_brief_a.risk_level = "low"
    sample_brief_a.pdf_path = "test_dummy_path.pdf"
    await db_session.commit()

    # Status check after completion returns populated fields
    res_completed = await client.get(f"/api/v1/route-briefs/{sample_brief_a.id}/status", headers=tenant_a_headers)
    assert res_completed.status_code == 200
    comp_data = res_completed.json()
    assert comp_data["status"] == "completed"
    assert comp_data["brief_id"] == str(sample_brief_a.id)
    assert comp_data["brief_markdown"] == "# Route Brief: Shanghai to Los Angeles"
    assert comp_data["recommendation"] == "ship_now"
    assert comp_data["risk_level"] == "low"
    assert comp_data["error_message"] is None
    assert comp_data["created_at"] is not None

    with open("test_dummy_path.pdf", "w") as f:
        f.write("dummy pdf")

    # Tenant A gets PDF successfully
    res = await client.get(f"/api/v1/route-briefs/{sample_brief_a.id}/pdf", headers=tenant_a_headers)
    assert res.status_code == 200

    # Tenant B gets 404 for PDF
    res = await client.get(f"/api/v1/route-briefs/{sample_brief_a.id}/pdf", headers=tenant_b_headers)
    assert res.status_code == 404

    os.remove("test_dummy_path.pdf")


@pytest.mark.asyncio
async def test_route_brief_post_unauthenticated(client):
    res = await client.post("/api/v1/route-briefs", json={
        "origin": "Shanghai",
        "destination": "LA",
        "carrier": "Maersk",
        "cargo_type": "40ft"
    })
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_invalid_route_brief_id(client, tenant_a_headers):
    invalid_id = uuid.uuid4()
    res = await client.get(f"/api/v1/route-briefs/{invalid_id}/status", headers=tenant_a_headers)
    assert res.status_code == 404
