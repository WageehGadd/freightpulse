import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import uuid

from app.routers.carriers import get_carrier_advisories
from app.scrapers import carrier_advisories


class FakeSessionContext:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, traceback):
        return False


def test_scraper_persists_source_text_then_dispatches_after_commit(monkeypatch):
    advisory_id = uuid.uuid4()
    entry = SimpleNamespace(
        category="Prices & Surcharges",
        title="Peak season surcharge",
        description="Original carrier advisory source content.",
        link="https://carrier.example/advisory",
        published="Fri, 15 Aug 2026 12:00:00 GMT",
    )
    session = MagicMock()
    session.commit = AsyncMock(side_effect=lambda: setattr(session, "committed", True))
    existing_result = MagicMock()
    existing_result.scalar_one_or_none.return_value = None
    insert_result = MagicMock()
    insert_result.scalar_one.return_value = advisory_id
    session.execute = AsyncMock(side_effect=[existing_result, insert_result])
    session.committed = False
    dispatch = MagicMock(side_effect=lambda value: session.committed or pytest.fail("dispatched before commit"))

    monkeypatch.setattr(carrier_advisories, "AsyncSessionLocal", lambda: FakeSessionContext(session))
    monkeypatch.setattr(carrier_advisories, "fetch_feed_via_browser", AsyncMock(return_value=b"feed"))
    monkeypatch.setattr(
        carrier_advisories.feedparser,
        "parse",
        lambda content: SimpleNamespace(entries=[entry], bozo=False),
    )
    monkeypatch.setattr(carrier_advisories.summarize_advisory, "delay", dispatch)

    result = asyncio.run(carrier_advisories.CarrierAdvisoryScraper().scrape())

    inserted = session.execute.await_args_list[1].args[0].compile().params
    assert inserted["carrier"] == "CMA CGM"
    assert inserted["advisory_type"] == "surcharge"
    assert inserted["raw_text"] == "Original carrier advisory source content."
    assert inserted["summary"] is None
    session.commit.assert_awaited_once()
    dispatch.assert_called_once_with(str(advisory_id))
    assert result == {"rows_upserted": 1}


def test_carrier_api_returns_persisted_ai_fields():
    advisory = SimpleNamespace(
        id=uuid.uuid4(),
        carrier="MSC",
        advisory_type="schedule_change",
        title="Service update",
        summary="AI-generated operational summary.",
        affected_lanes=["Egypt-Europe"],
        effective_date=None,
        impact_severity="high",
        source_url="https://carrier.example/advisory",
        published_at=None,
    )
    db = MagicMock()
    db.execute = AsyncMock(
        return_value=SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [advisory]))
    )

    response = asyncio.run(get_carrier_advisories(db=db))

    item = response.advisories[0]
    assert item.summary == "AI-generated operational summary."
    assert item.impact_severity == "high"
    assert item.affected_lanes == ["Egypt-Europe"]
    assert item.source_url == "https://carrier.example/advisory"
    assert not hasattr(item, "raw_text")
