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
async def test_auth_missing_key(client: AsyncClient):
    response = await client.get("/api/v1/dashboard")
    assert response.status_code == 401
    assert "Missing API Key" in response.text

@pytest.mark.asyncio
async def test_auth_invalid_key(client: AsyncClient):
    response = await client.get("/api/v1/dashboard", headers={"X-API-Key": "invalid_key"})
    assert response.status_code == 401
    assert "Invalid API Key" in response.text

@pytest.mark.asyncio
async def test_auth_valid_key(client: AsyncClient, auth_headers):
    # This should succeed since rate limit dependency is mock-injected or runs on Redis.
    # Assuming redis is up in tests, it will return 200.
    response = await client.get("/api/v1/dashboard", headers=auth_headers)
    assert response.status_code == 200

@pytest.mark.asyncio
async def test_health_public(client: AsyncClient):
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
