import pytest
from datetime import date, timedelta
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.tasks.trend_computation import _run_trend_computation, compute_rate_trends
from app.models import FreightRate, RateTrend

class FakeSessionContext:
    def __init__(self, session):
        self.session = session
    async def __aenter__(self):
        return self.session
    async def __aexit__(self, exc_type, exc, traceback):
        return False

async def insert_rates(db_session, rates_data):
    for rd in rates_data:
        stmt = insert(FreightRate).values(**rd)
        await db_session.execute(stmt)

@pytest.mark.asyncio
async def test_trend_computation_happy_path_and_7d_30d_semantics(db_session):
    today = date(2023, 10, 8)
    rates = []

    for d in range(8):
        rates.append({
            "source": "SCFI", "trade_lane": "Egypt-Europe", "origin_port": "Port Said", "dest_region": "Europe",
            "container_type": "40ft", "rate_usd": 1000 + d * 10, "rate_date": today - timedelta(days=d), "week_number": 40
        })

    rates.append({
        "source": "SCFI", "trade_lane": "Egypt-Europe", "origin_port": "Port Said", "dest_region": "Europe",
        "container_type": "40ft", "rate_usd": 500, "rate_date": today - timedelta(days=30), "week_number": 36
    })

    await insert_rates(db_session, rates)

    res = await _run_trend_computation(computation_date=today, session_factory=lambda: FakeSessionContext(db_session))
    assert res["upserted"] == 1

    trend = (await db_session.execute(select(RateTrend))).scalars().first()

    assert trend is not None
    assert trend.trade_lane == "Egypt-Europe"

    assert float(trend.avg_7d_usd) == 1035.0
    assert float(trend.avg_30d_usd) == 975.56

    assert trend.change_7d_pct == -3.38
    assert trend.trend == "stable"
    assert trend.anomaly_flag is False

@pytest.mark.asyncio
async def test_threshold_boundaries(db_session):
    today = date(2023, 10, 8)

    # Test EXACTLY +5% (stable)
    rates = [
        {"source": "SCFI", "trade_lane": "Lane1", "origin_port": "P", "dest_region": "R", "container_type": "40ft", "rate_usd": 1050, "rate_date": today, "week_number": 40},
        {"source": "SCFI", "trade_lane": "Lane1", "origin_port": "P", "dest_region": "R", "container_type": "40ft", "rate_usd": 950, "rate_date": today - timedelta(days=7), "week_number": 40},
    ]
    await insert_rates(db_session, rates)

    await _run_trend_computation(computation_date=today, session_factory=lambda: FakeSessionContext(db_session))
    trend1 = (await db_session.execute(select(RateTrend).where(RateTrend.trade_lane == "Lane1"))).scalars().first()
    assert trend1.change_7d_pct == 5.0
    assert trend1.trend == "stable"
    assert trend1.anomaly_flag is False
    assert trend1.slope_per_week == 100.0

    # Test +12.01% (rising and anomaly)
    rates2 = [
        {"source": "SCFI", "trade_lane": "Lane2", "origin_port": "P", "dest_region": "R", "container_type": "40ft", "rate_usd": 1120.1, "rate_date": today, "week_number": 40},
        {"source": "SCFI", "trade_lane": "Lane2", "origin_port": "P", "dest_region": "R", "container_type": "40ft", "rate_usd": 879.9, "rate_date": today - timedelta(days=7), "week_number": 40},
    ]
    await insert_rates(db_session, rates2)

    await _run_trend_computation(computation_date=today, session_factory=lambda: FakeSessionContext(db_session))
    trend2 = (await db_session.execute(select(RateTrend).where(RateTrend.trade_lane == "Lane2"))).scalars().first()
    assert trend2.change_7d_pct > 12.0
    assert trend2.trend == "rising"
    assert trend2.anomaly_flag is True

@pytest.mark.asyncio
async def test_insufficient_historical_data(db_session):
    today = date(2023, 10, 8)
    rates = [
        {"source": "SCFI", "trade_lane": "LaneFuture", "origin_port": "P", "dest_region": "R", "container_type": "40ft", "rate_usd": 1050, "rate_date": today + timedelta(days=1), "week_number": 40},
    ]
    await insert_rates(db_session, rates)
    await _run_trend_computation(computation_date=today, session_factory=lambda: FakeSessionContext(db_session))

    trend = (await db_session.execute(select(RateTrend).where(RateTrend.trade_lane == "LaneFuture"))).scalars().first()
    assert trend.trend is None
    assert trend.avg_7d_usd is None
    assert trend.change_7d_pct is None
    assert trend.slope_per_week is None
    assert trend.anomaly_flag is False

@pytest.mark.asyncio
async def test_no_data_for_today(db_session):
    today = date(2023, 10, 8)
    rates = [
        {"source": "SCFI", "trade_lane": "LanePast", "origin_port": "P", "dest_region": "R", "container_type": "40ft", "rate_usd": 1000, "rate_date": today - timedelta(days=2), "week_number": 40},
        {"source": "SCFI", "trade_lane": "LanePast", "origin_port": "P", "dest_region": "R", "container_type": "40ft", "rate_usd": 2000, "rate_date": today - timedelta(days=7), "week_number": 40},
    ]
    await insert_rates(db_session, rates)
    await _run_trend_computation(computation_date=today, session_factory=lambda: FakeSessionContext(db_session))

    trend = (await db_session.execute(select(RateTrend).where(RateTrend.trade_lane == "LanePast"))).scalars().first()

    assert trend.change_7d_pct == -33.33
    assert trend.trend == "falling"
    assert trend.anomaly_flag is True
    assert trend.slope_per_week == -1400.0

@pytest.mark.asyncio
async def test_recomputation_preserving_ai_fields(db_session):
    today = date(2023, 10, 8)

    stmt = insert(RateTrend).values(
        trade_lane="LaneAI",
        computed_date=today,
        avg_7d_usd=100.0,
        outlook_text="Old AI Text",
        recommendation="ship_now",
        confidence=90,
        status="completed",
        error_message="None",
    )
    await db_session.execute(stmt)

    rates = [
        {"source": "SCFI", "trade_lane": "LaneAI", "origin_port": "P", "dest_region": "R", "container_type": "40ft", "rate_usd": 500, "rate_date": today, "week_number": 40},
    ]
    await insert_rates(db_session, rates)

    await _run_trend_computation(computation_date=today, session_factory=lambda: FakeSessionContext(db_session))

    trend = (await db_session.execute(select(RateTrend).where(RateTrend.trade_lane == "LaneAI"))).scalars().first()

    assert float(trend.avg_7d_usd) == 500.0

    assert trend.outlook_text == "Old AI Text"
    assert trend.recommendation == "ship_now"
    assert trend.confidence == 90
    assert trend.status == "completed"
    assert trend.error_message == "None"

@pytest.mark.asyncio
async def test_idempotent_repeated_execution(db_session):
    today = date(2023, 10, 8)
    rates = [
        {"source": "SCFI", "trade_lane": "Lane1", "origin_port": "P", "dest_region": "R", "container_type": "40ft", "rate_usd": 1050, "rate_date": today, "week_number": 40},
    ]
    await insert_rates(db_session, rates)

    await _run_trend_computation(computation_date=today, session_factory=lambda: FakeSessionContext(db_session))
    await _run_trend_computation(computation_date=today, session_factory=lambda: FakeSessionContext(db_session))

    count = len((await db_session.execute(select(RateTrend).where(RateTrend.trade_lane == "Lane1"))).scalars().all())
    assert count == 1
