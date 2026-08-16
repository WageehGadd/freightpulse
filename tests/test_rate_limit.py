import pytest
from httpx import AsyncClient
from app.redis_client import get_redis
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
async def test_rate_limit_exceeded(client: AsyncClient, auth_headers):
    # Send 100 requests to hit the limit
    for _ in range(100):
        resp = await client.get("/api/v1/dashboard", headers=auth_headers)
        assert resp.status_code == 200

    # The 101st request should fail
    resp_429 = await client.get("/api/v1/dashboard", headers=auth_headers)
    assert resp_429.status_code == 429
    assert "Rate limit exceeded" in resp_429.text

    # Clean up Redis after test
    redis = get_redis()
    await redis.flushdb()

@pytest.mark.asyncio
async def test_rate_limit_fail_open(client: AsyncClient, auth_headers, monkeypatch):
    """Test that if Redis raises an exception, the request still succeeds (fail-open)."""

    # Mock redis to raise an exception
    class BrokenRedis:
        async def incr(self, *args, **kwargs):
            raise Exception("Redis Connection Error")

    # Mock the get_redis dependency or function
    import app.auth.rate_limit as rl
    monkeypatch.setattr(rl, "get_redis", lambda: BrokenRedis())

    response = await client.get("/api/v1/dashboard", headers=auth_headers)
    assert response.status_code == 200
