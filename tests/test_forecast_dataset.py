import pytest
from datetime import date, datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert
from app.services.forecast_dataset import ForecastDatasetBuilder
from app.models.freight_rate import FreightRate
from app.models.bunker_rate import BunkerRate
from app.models.exchange_rate import ExchangeRate
from app.models.port_congestion import PortCongestion
import pandas as pd

@pytest.fixture
def dataset_builder(db_session: AsyncSession):
    return ForecastDatasetBuilder(db_session)

@pytest.mark.asyncio
async def test_series_profiling(db_session: AsyncSession, dataset_builder):
    # Add multiple series
    today = date.today()
    for i in range(50):
        db_session.add(FreightRate(origin_port="Test", dest_region="Test", source="A", trade_lane="L1", container_type="20ft", rate_usd=1000, rate_date=today - timedelta(days=i)))
    for i in range(5):
        db_session.add(FreightRate(origin_port="Test", dest_region="Test", source="B", trade_lane="L2", container_type="40ft", rate_usd=2000, rate_date=today - timedelta(days=i*7)))
    await db_session.commit()
    
    profiles = await dataset_builder.profile_all_series()
    assert len(profiles) == 2
    
    p1 = next(p for p in profiles if p.series_id == "A_L1_20ft")
    assert p1.observation_count == 50
    assert p1.readiness == "MINIMAL"
    
    p2 = next(p for p in profiles if p.series_id == "B_L2_40ft")
    assert p2.observation_count == 5
    assert p2.readiness == "INSUFFICIENT"

@pytest.mark.asyncio
async def test_ordering_and_monotonicity(db_session: AsyncSession, dataset_builder):
    # Insert out of order
    today = date.today()
    dates = [today, today - timedelta(days=2), today - timedelta(days=1)]
    for d in dates:
        db_session.add(FreightRate(origin_port="Test", dest_region="Test", source="A", trade_lane="L1", container_type="20ft", rate_usd=1000, rate_date=d))
    await db_session.commit()
    
    dataset = await dataset_builder.build_dataset("A", "L1", "20ft")
    obs_dates = [obs.date for obs in dataset.observations]
    # Should be perfectly sorted ascending
    assert obs_dates == sorted(obs_dates)

@pytest.mark.asyncio
async def test_lag_and_rolling_leakage(db_session: AsyncSession, dataset_builder):
    today = date.today()
    rates = [100.0, 110.0, 120.0, 130.0, 9999.0] # 9999 is extreme future leak test
    for i, r in enumerate(rates):
        db_session.add(FreightRate(origin_port="Test", dest_region="Test", source="A", trade_lane="L1", container_type="20ft", rate_usd=r, rate_date=today + timedelta(days=i)))
    await db_session.commit()
    
    dataset = await dataset_builder.build_dataset("A", "L1", "20ft")
    
    # Check lag_1 for the 5th element (index 4) -> should be 130.0
    assert dataset.observations[4].features["lag_1"] == 130.0
    
    # Check that index 3's rolling mean doesn't include 9999.0
    # Values before index 3: 100, 110, 120 (rolling_mean_4 of shift 1)
    # The current target is 130, future is 9999.
    # index 3 uses shift 1: [100, 110, 120] -> mean is 110
    assert dataset.observations[3].features["rolling_mean_4"] == 110.0

@pytest.mark.asyncio
async def test_exogenous_asof_leakage(db_session: AsyncSession, dataset_builder):
    today = date.today()
    db_session.add(FreightRate(origin_port="Test", dest_region="Test", source="A", trade_lane="L1", container_type="20ft", rate_usd=1000, rate_date=today))
    db_session.add(FreightRate(origin_port="Test", dest_region="Test", source="A", trade_lane="L1", container_type="20ft", rate_usd=1000, rate_date=today + timedelta(days=2)))
    
    # Bunker on day 0
    db_session.add(BunkerRate(port_name="Global Average Bunker Price", fuel_type="IFO380", price_usd=600, observed_date=today))
    # Bunker on day 3 (Future relative to freight day 2)
    db_session.add(BunkerRate(port_name="Global Average Bunker Price", fuel_type="IFO380", price_usd=999, observed_date=today + timedelta(days=3)))
    await db_session.commit()
    
    dataset = await dataset_builder.build_dataset("A", "L1", "20ft")
    
    # Observation at day 0 -> Bunker 600
    assert dataset.observations[0].features["bunker_usd"] == 600.0
    # Observation at day 2 -> should still be 600, 999 is strictly future and must not leak
    assert dataset.observations[1].features["bunker_usd"] == 600.0

@pytest.mark.asyncio
async def test_missing_values(db_session: AsyncSession, dataset_builder):
    today = date.today()
    # Missing day 1
    db_session.add(FreightRate(origin_port="Test", dest_region="Test", source="A", trade_lane="L1", container_type="20ft", rate_usd=1000, rate_date=today))
    db_session.add(FreightRate(origin_port="Test", dest_region="Test", source="A", trade_lane="L1", container_type="20ft", rate_usd=1000, rate_date=today + timedelta(days=2)))
    await db_session.commit()
    
    dataset = await dataset_builder.build_dataset("A", "L1", "20ft")
    # Only 2 rows exist, missing periods are NOT fabricated or interpolated
    assert len(dataset.observations) == 2
    
    # lag_1 for first row is None (NaN converted to None)
    assert dataset.observations[0].features["lag_1"] is None
    
    # Exogenous is entirely missing, should be None, not 0
    assert dataset.observations[0].features["fx_usd_egp"] is None
