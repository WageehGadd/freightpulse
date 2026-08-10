import asyncio

import pytest
from dotenv import load_dotenv

# Load test environment variables before importing anything from the app.
load_dotenv(".env.test", override=True)

from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    AsyncSession,
    async_sessionmaker,
)

from app.database import Base
from app.config import settings
from app.main import app


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="function")
async def db_session():
    """
    Create all database tables before each test and drop them afterward
    so every test starts with a clean database state.
    """
    engine = create_async_engine(settings.DATABASE_URL)

    async_session = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_session() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest.fixture(scope="function")
async def client(db_session):
    """
    Create an HTTP client that communicates directly with the FastAPI app
    without requiring a running Uvicorn server.
    """
    transport = ASGITransport(app=app)

    async with AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as ac:
        yield ac


@pytest.fixture
def auth_headers():
    return {"X-API-Key": settings.API_KEY}
