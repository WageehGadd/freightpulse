import uuid
from datetime import date
from unittest.mock import AsyncMock, patch
from contextlib import asynccontextmanager

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import RateTrend
from app.schemas.ai_outputs import RateOutlookOutput


@pytest.fixture
async def rate_trend(db_session: AsyncSession) -> RateTrend:
    from app.models import FreightRate
    trend = RateTrend(
        id=uuid.uuid4(),
        trade_lane="USWC-ASIA",
        computed_date=date.today(),
        status="none",
        anomaly_flag=False,
        avg_7d_usd=1500.0,
        avg_30d_usd=1400.0,
        change_7d_pct=2.5,
        slope_per_week=10.0,
    )
    db_session.add(trend)
    rate = FreightRate(
        rate_date=date.today(),
        trade_lane="USWC-ASIA",
        rate_usd=1550.0,
        source="SCFI",
        origin_port="Shanghai",
        dest_region="USWC",
        container_type="40ft",
    )
    db_session.add(rate)
    await db_session.commit()
    return trend


@pytest.mark.asyncio
async def test_rate_outlook_endpoint_creates_job(db_session: AsyncSession, rate_trend: RateTrend):
    from app.routers.rates import generate_rate_outlook_endpoint
    with patch("app.routers.rates.generate_rate_outlook.delay") as mock_delay:
        response = await generate_rate_outlook_endpoint(
            trend_id=rate_trend.id,
            db=db_session,
        )
        assert response.trend_id == str(rate_trend.id)
        assert response.status == "pending"

        mock_delay.assert_called_once_with(str(rate_trend.id))


@pytest.mark.asyncio
async def test_rate_outlook_celery_task_success(db_session: AsyncSession, rate_trend: RateTrend):
    from app.tasks.rate_outlook_generation import generate_rate_outlook_async

    # Set status to pending as if API endpoint was called
    rate_trend.status = "pending"
    await db_session.commit()

    mock_output = RateOutlookOutput(
        outlook_text="Expect rates to rise consistently over the next quarter due to market conditions.",
        recommendation="book_now",
        confidence=85,
    )

    mock_narrator = AsyncMock()
    mock_narrator.narrate.return_value = mock_output

    def mock_factory():
        return mock_narrator

    @asynccontextmanager
    async def mock_session_factory():
        yield db_session

    result = await generate_rate_outlook_async(
        str(rate_trend.id),
        session_factory=mock_session_factory,
        narrator_factory=mock_factory,
    )

    assert result["trend_id"] == str(rate_trend.id)
    assert result["status"] == "completed"

    await db_session.refresh(rate_trend)
    assert rate_trend.status == "completed"
    assert rate_trend.outlook_text == "Expect rates to rise consistently over the next quarter due to market conditions."
    assert rate_trend.recommendation == "book_now"
    assert rate_trend.confidence == 85
    assert rate_trend.error_message is None
