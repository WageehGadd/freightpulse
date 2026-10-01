import pytest
from datetime import datetime, timezone, timedelta, date
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.data_quality import DataQualityService
from app.models.freight_rate import FreightRate
from app.models.bunker_rate import BunkerRate
from app.models.exchange_rate import ExchangeRate
from app.models.carrier_advisory import CarrierAdvisory
from app.models.port_congestion import PortCongestion

@pytest.fixture
def data_quality_service():
    return DataQualityService()

@pytest.mark.asyncio
async def test_availability_no_records(db_session: AsyncSession, data_quality_service):
    # db is empty
    report = await data_quality_service.evaluate_freight_rates(db_session)
    assert report.available is False
    assert report.record_count == 0
    assert report.freshness_status == "unknown"

@pytest.mark.asyncio
async def test_fresh_daily_signal(db_session: AsyncSession, data_quality_service):
    now = datetime.now(timezone.utc)
    bunker = BunkerRate(port_name="Test", fuel_type="IFO380", price_usd=100.0, observed_date=now.date())
    db_session.add(bunker)
    await db_session.commit()
    
    report = await data_quality_service.evaluate_bunker_rates(db_session)
    assert report.available is True
    assert report.freshness_status == "fresh"
    assert report.usable_for_decisioning is True

@pytest.mark.asyncio
async def test_stale_daily_signal(db_session: AsyncSession, data_quality_service):
    stale_date = datetime.now(timezone.utc).date() - timedelta(days=4)
    bunker = BunkerRate(port_name="Test", fuel_type="IFO380", price_usd=100.0, observed_date=stale_date)
    db_session.add(bunker)
    await db_session.commit()
    
    report = await data_quality_service.evaluate_bunker_rates(db_session)
    assert report.freshness_status == "stale"
    assert report.usable_for_decisioning is False
    assert "Data is stale" in report.warnings

@pytest.mark.asyncio
async def test_fresh_weekly_signal_older_than_24h(db_session: AsyncSession, data_quality_service):
    # 4 days old, which is fresh for weekly
    old_date = datetime.now(timezone.utc).date() - timedelta(days=4)
    rate = FreightRate(source="SCFI", trade_lane="Asia-Europe", origin_port="Shanghai", dest_region="Europe", container_type="40ft", rate_usd=1000.0, rate_date=old_date)
    db_session.add(rate)
    await db_session.commit()
    
    report = await data_quality_service.evaluate_freight_rates(db_session)
    assert report.freshness_status == "fresh"
    assert report.usable_for_decisioning is True

@pytest.mark.asyncio
async def test_port_congestion_never_trusted(db_session: AsyncSession, data_quality_service):
    now = datetime.now(timezone.utc)
    pc = PortCongestion(port_code="TEST", port_name="Test", measured_at=now)
    db_session.add(pc)
    await db_session.commit()
    
    report = await data_quality_service.evaluate_port_congestion(db_session)
    assert report.source_type == "seeded"
    assert report.usable_for_decisioning is False
    assert report.usable_for_forecasting is False
    assert any("MUST NOT be used" in w for w in report.warnings)

@pytest.mark.asyncio
async def test_completeness_with_gaps(db_session: AsyncSession, data_quality_service):
    today = datetime.now(timezone.utc).date()
    db_session.add(BunkerRate(port_name="P1", fuel_type="IFO380", price_usd=100, observed_date=today))
    db_session.add(BunkerRate(port_name="P1", fuel_type="IFO380", price_usd=100, observed_date=today - timedelta(days=3)))
    await db_session.commit()
    
    report = await data_quality_service.evaluate_bunker_rates(db_session)
    # Expected periods = 4 (today, -1, -2, -3)
    # Actual distinct dates = 2
    assert report.completeness_status == "gaps"
    assert report.missing_periods == 2
    assert report.usable_for_forecasting is False

@pytest.mark.asyncio
async def test_event_driven_data(db_session: AsyncSession, data_quality_service):
    # 30 days old advisory
    old_time = datetime.now(timezone.utc) - timedelta(days=30)
    adv = CarrierAdvisory(carrier="MSC", advisory_type="surcharge", title="Test", raw_text="test", published_at=old_time)
    db_session.add(adv)
    await db_session.commit()
    
    report = await data_quality_service.evaluate_carrier_advisories(db_session)
    assert report.source_type == "live"
    # Event data shouldn't be penalized for age
    assert report.freshness_status == "not_applicable"
    assert report.usable_for_decisioning is True
    assert report.usable_for_forecasting is False

@pytest.mark.asyncio
async def test_forecast_eligibility(db_session: AsyncSession, data_quality_service):
    # Add 10 continuous daily records
    today = datetime.now(timezone.utc).date()
    for i in range(10):
        db_session.add(BunkerRate(port_name="P1", fuel_type="IFO380", price_usd=100, observed_date=today - timedelta(days=i)))
    await db_session.commit()
    
    report = await data_quality_service.evaluate_bunker_rates(db_session)
    assert report.missing_periods == 0
    assert report.usable_for_forecasting is True
