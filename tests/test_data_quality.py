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


# Publication absence is distinct from absence of event records. No storage
# timestamp may substitute for publication time, and no cadence is invented.
ADVISORY_NOW = datetime(2026, 1, 31, 12, tzinfo=timezone.utc)
ADVISORY_OLD = ADVISORY_NOW - timedelta(days=30)
ADVISORY_NEW = ADVISORY_NOW - timedelta(days=2)


@pytest.fixture
def fixed_advisory_clock(monkeypatch):
    import app.services.data_quality as module
    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            assert tz is timezone.utc
            return ADVISORY_NOW
    monkeypatch.setattr(module, "datetime", FixedDatetime)
    return ADVISORY_NOW


@pytest.mark.asyncio
@pytest.mark.parametrize("publications,latest", [
    ([], None),
    ([None], None),
    ([None, None, None], None),
    ([ADVISORY_OLD], ADVISORY_OLD),
    ([ADVISORY_NEW, ADVISORY_OLD], ADVISORY_NEW),
    ([None, ADVISORY_OLD, None, ADVISORY_NEW], ADVISORY_NEW),
])
async def test_advisory_publication_sql_matrix(db_session, fixed_advisory_clock, publications, latest):
    from sqlalchemy import select, func
    for published in publications:
        db_session.add(CarrierAdvisory(carrier="Synthetic", advisory_type="surcharge",
            title="Synthetic advisory", raw_text="Synthetic test content",
            published_at=published, created_at=ADVISORY_NOW))
    await db_session.commit()
    aggregate = (await db_session.execute(select(func.count(CarrierAdvisory.id),
                                                 func.max(CarrierAdvisory.published_at)))).one()
    # Exercise actual PostgreSQL NULL aggregation, not a Python approximation.
    assert aggregate[0] == len(publications)
    assert aggregate[1] == latest
    service = DataQualityService()
    report = await service.evaluate_carrier_advisories(db_session)
    assert report == await service.evaluate_carrier_advisories(db_session)
    assert report.record_count == len(publications)
    assert report.available is bool(publications)
    assert report.latest_observation_at == latest
    assert report.age_seconds == ((ADVISORY_NOW-latest).total_seconds() if latest is not None else None)
    assert report.freshness_status == ("not_applicable" if publications else "unknown")
    assert report.completeness_status == ("not_applicable" if publications else "unknown")
    assert report.expected_cadence_seconds is None
    assert report.freshness_ratio is None
    assert report.usable_for_forecasting is False
    assert report.usable_for_decisioning is bool(publications)
    assert report.warnings == ([] if publications else ["No data available"])


@pytest.mark.asyncio
async def test_advisory_original_all_null_aggregate_regression(fixed_advisory_clock):
    from types import SimpleNamespace
    class Session:
        async def execute(self, statement):
            return SimpleNamespace(first=lambda: SimpleNamespace(cnt=1, latest=None))
    report = await DataQualityService().evaluate_carrier_advisories(Session())
    assert report.model_dump() == {
        "signal_name": "carrier_advisories", "source_type": "live",
        "evaluated_at": ADVISORY_NOW, "available": True, "record_count": 1,
        "latest_observation_at": None, "earliest_observation_at": None,
        "age_seconds": None, "expected_cadence_seconds": None,
        "freshness_status": "not_applicable", "freshness_ratio": None,
        "completeness_status": "not_applicable", "missing_periods": None,
        "duplicate_count": 0, "usable_for_forecasting": False,
        "usable_for_decisioning": True, "warnings": [],
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("publication", [
    ADVISORY_OLD,
    ADVISORY_OLD.astimezone(timezone(timedelta(hours=5))),
    ADVISORY_OLD.replace(tzinfo=None),
])
async def test_advisory_nonnull_timezone_full_report_parity(fixed_advisory_clock, publication):
    from types import SimpleNamespace
    class Session:
        async def execute(self, statement):
            return SimpleNamespace(first=lambda: SimpleNamespace(cnt=2, latest=publication))
    expected_latest = publication if publication.tzinfo is not None else publication.replace(tzinfo=timezone.utc)
    report = await DataQualityService().evaluate_carrier_advisories(Session())
    # Explicit pre-fix valid-state contract: naive values assume UTC, existing
    # offsets survive, age is informational and no event freshness penalty exists.
    assert report.model_dump() == {
        "signal_name": "carrier_advisories", "source_type": "live",
        "evaluated_at": ADVISORY_NOW, "available": True, "record_count": 2,
        "latest_observation_at": expected_latest, "earliest_observation_at": None,
        "age_seconds": (ADVISORY_NOW-expected_latest).total_seconds(),
        "expected_cadence_seconds": None, "freshness_status": "not_applicable",
        "freshness_ratio": None, "completeness_status": "not_applicable",
        "missing_periods": None, "duplicate_count": 0,
        "usable_for_forecasting": False, "usable_for_decisioning": True, "warnings": [],
    }
    assert report == await DataQualityService().evaluate_carrier_advisories(Session())


@pytest.mark.asyncio
async def test_advisory_unrelated_failure_not_masked(fixed_advisory_clock):
    class Session:
        async def execute(self, statement):
            raise RuntimeError("Synthetic infrastructure failure")
    with pytest.raises(RuntimeError, match="Synthetic infrastructure failure"):
        await DataQualityService().evaluate_carrier_advisories(Session())
