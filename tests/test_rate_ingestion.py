import pytest
from unittest.mock import patch
from datetime import date

from sqlalchemy import select
from app.tasks.rate_ingestion import _run_rate_ingestion, ingest_freight_rates
from app.models import FreightRate
from app.celery_app import celery_app
from unittest.mock import AsyncMock

class FakeSessionContext:
    def __init__(self, session):
        self.session = session
    async def __aenter__(self):
        return self.session
    async def __aexit__(self, exc_type, exc, traceback):
        return False

@pytest.mark.asyncio
async def test_successful_ingestion(db_session):
    mock_records = {
        "records": [
            {
                "source": "SCFI",
                "trade_lane": "Shanghai-Europe",
                "origin_port": "Shanghai",
                "dest_region": "Europe",
                "container_type": "20ft",
                "rate_usd": 1500.0,
                "rate_date": date(2023, 10, 1),
                "week_number": 40,
                "source_url": "http://example.com"
            }
        ]
    }
    with patch("app.tasks.rate_ingestion.SCFIScraper.run", new_callable=AsyncMock, return_value=mock_records):
        with patch("app.tasks.rate_ingestion.AsyncSessionLocal", return_value=FakeSessionContext(db_session)):
            res = await _run_rate_ingestion()
            assert res["upserted"] == 1
            assert res["invalid"] == 0

            rates = (await db_session.execute(select(FreightRate))).scalars().all()
            assert len(rates) == 1
            assert rates[0].rate_usd == 1500.0

@pytest.mark.asyncio
async def test_duplicate_ingestion(db_session):
    mock_records = {
        "records": [
            {
                "source": "SCFI",
                "trade_lane": "Shanghai-Europe",
                "origin_port": "Shanghai",
                "dest_region": "Europe",
                "container_type": "20ft",
                "rate_usd": 1500.0,
                "rate_date": date(2023, 10, 1),
                "week_number": 40,
                "source_url": "http://example.com"
            }
        ]
    }
    with patch("app.tasks.rate_ingestion.SCFIScraper.run", new_callable=AsyncMock, return_value=mock_records):
        with patch("app.tasks.rate_ingestion.AsyncSessionLocal", return_value=FakeSessionContext(db_session)):
            await _run_rate_ingestion()
            res = await _run_rate_ingestion()
            assert res["upserted"] == 1

            rates = (await db_session.execute(select(FreightRate))).scalars().all()
            assert len(rates) == 1

@pytest.mark.asyncio
async def test_upsert_updates_mutable_fields(db_session):
    mock_records = {
        "records": [
            {
                "source": "SCFI",
                "trade_lane": "Shanghai-Europe",
                "origin_port": "Shanghai",
                "dest_region": "Europe",
                "container_type": "20ft",
                "rate_usd": 1500.0,
                "rate_date": date(2023, 10, 1),
                "week_number": 40,
                "source_url": "http://example.com"
            }
        ]
    }
    with patch("app.tasks.rate_ingestion.SCFIScraper.run", new_callable=AsyncMock, return_value=mock_records):
        with patch("app.tasks.rate_ingestion.AsyncSessionLocal", return_value=FakeSessionContext(db_session)):
            await _run_rate_ingestion()

    mock_records["records"][0]["rate_usd"] = 2000.0
    with patch("app.tasks.rate_ingestion.SCFIScraper.run", new_callable=AsyncMock, return_value=mock_records):
        with patch("app.tasks.rate_ingestion.AsyncSessionLocal", return_value=FakeSessionContext(db_session)):
            await _run_rate_ingestion()

            rates = (await db_session.execute(select(FreightRate))).scalars().all()
            assert len(rates) == 1
            assert rates[0].rate_usd == 2000.0

@pytest.mark.asyncio
async def test_invalid_record_handling(db_session):
    mock_records = {
        "records": [
            {
                "source": "SCFI",
                "trade_lane": "Shanghai-Europe",
                "origin_port": "Shanghai",
                "dest_region": "Europe",
                "container_type": "20ft",
                "rate_usd": "invalid",
                "rate_date": date(2023, 10, 1),
                "week_number": 40,
                "source_url": "http://example.com"
            },
            {
                "source": "SCFI",
                "trade_lane": "Shanghai-USWC",
                "origin_port": "Shanghai",
                "dest_region": "USWC",
                "container_type": "40ft",
                "rate_usd": 2000.0,
                "rate_date": date(2023, 10, 1),
                "week_number": 40,
                "source_url": "http://example.com"
            }
        ]
    }
    with patch("app.tasks.rate_ingestion.SCFIScraper.run", new_callable=AsyncMock, return_value=mock_records):
        with patch("app.tasks.rate_ingestion.AsyncSessionLocal", return_value=FakeSessionContext(db_session)):
            res = await _run_rate_ingestion()
            assert res["upserted"] == 1
            assert res["invalid"] == 1

            rates = (await db_session.execute(select(FreightRate))).scalars().all()
            assert len(rates) == 1
            assert rates[0].trade_lane == "Shanghai-USWC"

def test_celery_retry_behavior_on_failure():
    with patch("app.tasks.rate_ingestion.SCFIScraper.run", new_callable=AsyncMock, side_effect=Exception("Scraper died")):
        with patch("app.tasks.rate_ingestion.ingest_freight_rates.retry", side_effect=Exception("Retry Triggered")):
            with pytest.raises(Exception, match="Retry Triggered"):
                ingest_freight_rates()

def test_celery_task_registration():
    assert "app.tasks.rate_ingestion.ingest_freight_rates" in celery_app.tasks

def test_celery_beat_registration():
    assert celery_app.conf.timezone == "Africa/Cairo"
    schedule = celery_app.conf.beat_schedule
    assert "run-daily-pipeline" in schedule
    assert schedule["run-daily-pipeline"]["task"] == "app.tasks.orchestration.trigger_daily_pipeline"
