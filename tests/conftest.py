import pytest
import pytest_asyncio
from dotenv import load_dotenv
import app.redis_client as redis_module

load_dotenv(".env.test", override=True)

from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    AsyncSession,
    async_sessionmaker,
)
from sqlalchemy.pool import NullPool

from app.database import Base, get_db
from app.config import settings
from app.main import app


@pytest_asyncio.fixture(scope="function")
async def db_session():
    engine = create_async_engine(
        settings.DATABASE_URL,
        poolclass=NullPool,
    )

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


@pytest_asyncio.fixture(scope="function")
async def client(db_session):
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)

    try:
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as ac:
            yield ac
    finally:
        app.dependency_overrides.pop(get_db, None)

@pytest_asyncio.fixture(autouse=True)
async def cleanup_redis():
    yield

    if redis_module._redis_client is not None:
        await redis_module._redis_client.aclose()
        redis_module._redis_client = None


@pytest.fixture
def auth_headers():
    return {"X-API-Key": settings.API_KEY}


