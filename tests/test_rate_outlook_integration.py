import json
import pytest
import uuid
from datetime import date
from unittest.mock import AsyncMock, patch, MagicMock
from contextlib import asynccontextmanager

from app.models import RateTrend, FreightRate
from app.tasks.rate_outlook_generation import generate_rate_outlook_async
from app.ai.adapter import InsufficientDataError
from app.schemas.ai_outputs import RateOutlookOutput


@pytest.fixture
async def sample_trend(db_session):
    trend = RateTrend(
        id=uuid.uuid4(),
        trade_lane="USWC-ASIA",
        computed_date=date(2026, 8, 15),
        status="pending",
        anomaly_flag=False,
        avg_7d_usd=1500.0,
        avg_30d_usd=1400.0,
        change_7d_pct=2.5,
        slope_per_week=10.0,
        trend="rising"
    )
    db_session.add(trend)

    rate = FreightRate(
        rate_date=date(2026, 8, 15),
        trade_lane="USWC-ASIA",
        rate_usd=1550.0,
        source="SCFI",
        origin_port="Shanghai",
        dest_region="USWC",
        container_type="40ft",
    )
    db_session.add(rate)
    await db_session.commit()
    await db_session.refresh(trend)
    return trend


@pytest.fixture
def mock_redis():
    redis = AsyncMock()
    redis.get.return_value = None
    redis.setex = AsyncMock()
    return redis


@pytest.fixture
def mock_narrator():
    narrator = AsyncMock()
    narrator.narrate.return_value = RateOutlookOutput(
        outlook_text="Expect rates to rise consistently over the next quarter.",
        recommendation="book_now",
        confidence=85,
    )
    return narrator


def fake_session_factory(db_session):
    @asynccontextmanager
    async def factory():
        yield db_session
    return factory


@pytest.mark.asyncio
async def test_cache_miss_generates_and_caches(db_session, sample_trend, mock_redis, mock_narrator):
    with patch("app.tasks.rate_outlook_generation.get_redis", return_value=mock_redis):
        result = await generate_rate_outlook_async(
            str(sample_trend.id),
            session_factory=fake_session_factory(db_session),
            narrator_factory=lambda: mock_narrator,
        )

    assert result["status"] == "completed"

    # Assert DB is updated
    await db_session.refresh(sample_trend)
    assert sample_trend.status == "completed"
    assert sample_trend.outlook_text == "Expect rates to rise consistently over the next quarter."

    # Assert cache is set
    cache_key = f"rate_outlook:USWC-ASIA:2026-08-15"
    mock_redis.get.assert_awaited_once_with(cache_key)
    mock_redis.setex.assert_awaited_once()
    args = mock_redis.setex.call_args[0]
    assert args[0] == cache_key
    assert args[1] == 86400

    # Assert LLM was called
    mock_narrator.narrate.assert_awaited_once()


@pytest.mark.asyncio
async def test_cache_hit_bypasses_ai(db_session, sample_trend, mock_redis, mock_narrator):
    cached_payload = json.dumps({
        "outlook_text": "Cached outlook.",
        "recommendation": "wait",
        "confidence": 99,
    })
    mock_redis.get.return_value = cached_payload

    with patch("app.tasks.rate_outlook_generation.get_redis", return_value=mock_redis):
        result = await generate_rate_outlook_async(
            str(sample_trend.id),
            session_factory=fake_session_factory(db_session),
            narrator_factory=lambda: mock_narrator,
        )

    assert result["status"] == "completed"

    # Assert DB is updated with cache values
    await db_session.refresh(sample_trend)
    assert sample_trend.status == "completed"
    assert sample_trend.outlook_text == "Cached outlook."

    # Assert LLM was NEVER called
    mock_narrator.narrate.assert_not_awaited()


@pytest.mark.asyncio
async def test_insufficient_data_raises_error(db_session, mock_redis, mock_narrator):
    # Create trend missing historical data
    trend = RateTrend(
        id=uuid.uuid4(),
        trade_lane="USEC-EU",
        computed_date=date(2026, 8, 15),
        status="pending",
        anomaly_flag=False,
        avg_7d_usd=None, # Missing required field
    )
    db_session.add(trend)

    rate = FreightRate(
        rate_date=date(2026, 8, 15),
        trade_lane="USEC-EU",
        rate_usd=1550.0,
        source="SCFI",
        origin_port="New York",
        dest_region="EU",
        container_type="40ft",
    )
    db_session.add(rate)
    await db_session.commit()

    with patch("app.tasks.rate_outlook_generation.get_redis", return_value=mock_redis):
        with pytest.raises(InsufficientDataError):
            await generate_rate_outlook_async(
                str(trend.id),
                session_factory=fake_session_factory(db_session),
                narrator_factory=lambda: mock_narrator,
            )

    mock_narrator.narrate.assert_not_awaited()


@pytest.mark.asyncio
async def test_redis_get_failure_falls_back_to_ai(db_session, sample_trend, mock_redis, mock_narrator):
    mock_redis.get.side_effect = Exception("Redis connection refused")

    with patch("app.tasks.rate_outlook_generation.get_redis", return_value=mock_redis):
        result = await generate_rate_outlook_async(
            str(sample_trend.id),
            session_factory=fake_session_factory(db_session),
            narrator_factory=lambda: mock_narrator,
        )

    # Should still succeed
    assert result["status"] == "completed"
    await db_session.refresh(sample_trend)
    assert sample_trend.status == "completed"
    assert sample_trend.outlook_text == "Expect rates to rise consistently over the next quarter."

    # LLM is called because cache failed
    mock_narrator.narrate.assert_awaited_once()


@pytest.mark.asyncio
async def test_redis_set_failure_returns_success(db_session, sample_trend, mock_redis, mock_narrator):
    mock_redis.setex.side_effect = Exception("Redis connection refused")

    with patch("app.tasks.rate_outlook_generation.get_redis", return_value=mock_redis):
        result = await generate_rate_outlook_async(
            str(sample_trend.id),
            session_factory=fake_session_factory(db_session),
            narrator_factory=lambda: mock_narrator,
        )

    # Should still succeed
    assert result["status"] == "completed"
    await db_session.refresh(sample_trend)
    assert sample_trend.status == "completed"
    assert sample_trend.outlook_text == "Expect rates to rise consistently over the next quarter."


@pytest.mark.asyncio
async def test_idempotency_same_lane_date(db_session, mock_redis, mock_narrator):
    # Trend 1
    trend1 = RateTrend(
        id=uuid.uuid4(),
        trade_lane="USWC-ASIA",
        computed_date=date(2026, 8, 15),
        status="pending",
        anomaly_flag=False,
        avg_7d_usd=1500.0,
        avg_30d_usd=1400.0,
        change_7d_pct=2.5,
        slope_per_week=10.0,
    )
    db_session.add(trend1)

    rate = FreightRate(
        rate_date=date(2026, 8, 15),
        trade_lane="USWC-ASIA",
        rate_usd=1550.0,
        source="SCFI",
        origin_port="Shanghai",
        dest_region="USWC",
        container_type="40ft",
    )
    db_session.add(rate)
    await db_session.commit()

    # First call: Cache miss -> Generates and Sets Cache
    with patch("app.tasks.rate_outlook_generation.get_redis", return_value=mock_redis):
        await generate_rate_outlook_async(
            str(trend1.id),
            session_factory=fake_session_factory(db_session),
            narrator_factory=lambda: mock_narrator,
        )

    await db_session.refresh(trend1)
    assert trend1.outlook_text == "Expect rates to rise consistently over the next quarter."
    mock_narrator.narrate.assert_awaited_once()

    # Simulate cache set taking effect in our mock
    mock_redis.get.return_value = json.dumps({
        "outlook_text": "Expect rates to rise consistently over the next quarter.",
        "recommendation": "book_now",
        "confidence": 85,
    })

    # Second call (using a new trend row for the same lane/date, or we can use the same)
    # The rule says same lane/date. We'll use the same trend, but pretend it was pending.
    trend1.status = "pending"
    trend1.outlook_text = None
    await db_session.commit()

    with patch("app.tasks.rate_outlook_generation.get_redis", return_value=mock_redis):
        await generate_rate_outlook_async(
            str(trend1.id),
            session_factory=fake_session_factory(db_session),
            narrator_factory=lambda: mock_narrator,
        )

    await db_session.refresh(trend1)
    # Re-populated from cache
    assert trend1.outlook_text == "Expect rates to rise consistently over the next quarter."
    # Narrator should NOT have been called again (call count still 1)
    assert mock_narrator.narrate.call_count == 1
