import pytest
from datetime import datetime, timezone, timedelta
from sqlalchemy import select
from app.models.bunker_rate import BunkerRate
from app.models.exchange_rate import ExchangeRate
from app.scrapers.bunker import BunkerScraper
from app.scrapers.exchange_rate import ExchangeRateScraper

@pytest.fixture
def mock_httpx_bunker(monkeypatch):
    class MockResponse:
        def raise_for_status(self): pass
        @property
        def text(self):
            return """
            <table></table>
            <table></table>
            <table>
                <tr><th>Global Average Bunker Price</th><td>650.50</td></tr>
                <tr><th>Singapore</th><td>600.00</td></tr>
            </table>
            """
    
    class MockClient:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, exc_type, exc_val, exc_tb): pass
        async def get(self, url): return MockResponse()
        
    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", MockClient)

@pytest.fixture
def mock_httpx_fx(monkeypatch):
    class MockResponse:
        def raise_for_status(self): pass
        def json(self):
            return {"result": "success", "conversion_rates": {"EGP": 50.25}}
            
    class MockClient:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, exc_type, exc_val, exc_tb): pass
        async def get(self, url): return MockResponse()
        
    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", MockClient)

@pytest.fixture
def mock_redis(monkeypatch):
    class MockRedis:
        async def set(self, key, value, ex=None): pass
    
    monkeypatch.setattr("app.scrapers.bunker.get_redis", lambda: MockRedis())
    monkeypatch.setattr("app.scrapers.exchange_rate.get_redis", lambda: MockRedis())

@pytest.fixture
def mock_db(monkeypatch, db_session):
    import contextlib
    @contextlib.asynccontextmanager
    async def get_session():
        yield db_session
        
    monkeypatch.setattr("app.scrapers.bunker.AsyncSessionLocal", get_session)
    monkeypatch.setattr("app.scrapers.exchange_rate.AsyncSessionLocal", get_session)

@pytest.mark.asyncio
async def test_bunker_persistence_accumulates_and_idempotent(db_session, mock_httpx_bunker, mock_redis, mock_db):
    scraper = BunkerScraper()
    
    # 1. First run
    await scraper.scrape()
    
    rates = (await db_session.execute(select(BunkerRate))).scalars().all()
    assert len(rates) == 2
    
    singapore = next(r for r in rates if r.port_name == "Singapore")
    assert singapore.price_usd == 600.00
    assert singapore.fuel_type == "IFO380"
    
    # 2. Second run (idempotent, same date)
    await scraper.scrape()
    rates_after = (await db_session.execute(select(BunkerRate))).scalars().all()
    assert len(rates_after) == 2 # No duplicates
    
@pytest.mark.asyncio
async def test_fx_persistence_accumulates_and_idempotent(db_session, mock_httpx_fx, mock_redis, mock_db):
    scraper = ExchangeRateScraper()
    
    # 1. First run
    await scraper.scrape()
    
    rates = (await db_session.execute(select(ExchangeRate))).scalars().all()
    assert len(rates) == 1
    
    assert rates[0].base_currency == "USD"
    assert rates[0].quote_currency == "EGP"
    assert rates[0].exchange_rate == 50.25
    
    # 2. Second run (idempotent, same date)
    await scraper.scrape()
    rates_after = (await db_session.execute(select(ExchangeRate))).scalars().all()
    assert len(rates_after) == 1 # No duplicates
