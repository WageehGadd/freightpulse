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


from app.models.user import User
from app.models.api_key import ApiKey
from app.auth.security import hash_api_key

@pytest.fixture(scope="function")
async def test_user(db_session):
    user = User(email="test@freightpulse.ai")
    db_session.add(user)
    await db_session.flush()
    return user

@pytest.fixture(scope="function")
async def auth_headers(db_session, test_user):
    plaintext_key = "fp_live_testkey123"
    api_key = ApiKey(
        user_id=test_user.id,
        key_hash=hash_api_key(plaintext_key),
        key_prefix="fp_live_test",
        name="Test Key"
    )
    db_session.add(api_key)
    await db_session.commit()
    return {"X-API-Key": plaintext_key}
