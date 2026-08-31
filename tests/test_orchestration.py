import pytest
import asyncio
from unittest.mock import patch, MagicMock

from app.tasks.orchestration import _trigger_daily_pipeline, _acquire_pipeline_lock
from app.redis_client import get_redis

@pytest.fixture(autouse=True)
async def cleanup_redis():
    """Ensure Redis is cleaned up before and after each test."""
    import app.redis_client
    app.redis_client._redis_client = None
    redis = get_redis()
    await redis.flushdb()
    yield
    await redis.flushdb()
    await redis.aclose()
    await redis.connection_pool.disconnect()
    app.redis_client._redis_client = None


@pytest.mark.asyncio
async def test_acquire_pipeline_lock():
    target_date = "2023-10-08"
    redis = get_redis()

    # First acquisition should succeed
    acquired1 = await _acquire_pipeline_lock(target_date)
    assert acquired1 is True

    # Check TTL
    ttl = await redis.ttl(f"pipeline_lock:{target_date}")
    assert 0 < ttl <= 86400

    # Second acquisition should fail
    acquired2 = await _acquire_pipeline_lock(target_date)
    assert acquired2 is False

@pytest.mark.asyncio
@patch("app.tasks.orchestration.chain")
async def test_trigger_daily_pipeline(mock_chain):
    mock_pipeline = MagicMock()
    mock_chain.return_value = mock_pipeline

    # First run dispatches
    res1 = await _trigger_daily_pipeline()
    assert res1["status"] == "dispatched"
    assert "target_date" in res1
    mock_pipeline.apply_async.assert_called_once()

    # Second run skips
    res2 = await _trigger_daily_pipeline()
    assert res2["status"] == "skipped"
    assert res2["reason"] == "lock_acquired"
    assert mock_pipeline.apply_async.call_count == 1 # still 1!
