import uuid
import pytest
from httpx import AsyncClient
from app.main import app
from app.database import get_db
from app.models.user import User


@pytest.fixture(autouse=True)
def override_dependency(db_session):
    async def _override():
        yield db_session
    app.dependency_overrides[get_db] = _override
    yield
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_users_unauthorized(client: AsyncClient):
    """Accessing /api/v1/users without API key returns 401."""
    response = await client.get("/api/v1/users")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_all_users_authenticated(client: AsyncClient, auth_headers, db_session):
    """Accessing /api/v1/users with API key returns list of users."""
    user1 = User(id=uuid.uuid4(), email="user1@example.com", is_admin=False)
    user2 = User(id=uuid.uuid4(), email="user2@example.com", is_admin=True)
    db_session.add_all([user1, user2])
    await db_session.commit()

    response = await client.get("/api/v1/users", headers=auth_headers)
    assert response.status_code == 200
    users = response.json()
    assert isinstance(users, list)
    emails = [u["email"] for u in users]
    assert "user1@example.com" in emails
    assert "user2@example.com" in emails


@pytest.mark.asyncio
async def test_get_users_filter_admin(client: AsyncClient, auth_headers, db_session):
    """Filter users by is_admin status."""
    admin_user = User(id=uuid.uuid4(), email="admin_filter@example.com", is_admin=True)
    regular_user = User(id=uuid.uuid4(), email="regular_filter@example.com", is_admin=False)
    db_session.add_all([admin_user, regular_user])
    await db_session.commit()

    response = await client.get("/api/v1/users?is_admin=true", headers=auth_headers)
    assert response.status_code == 200
    users = response.json()
    for u in users:
        assert u["is_admin"] is True


@pytest.mark.asyncio
async def test_get_current_user_me(client: AsyncClient, auth_headers):
    """Get profile of currently authenticated user."""
    response = await client.get("/api/v1/users/me", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert "id" in data
    assert "email" in data
    assert "is_admin" in data


@pytest.mark.asyncio
async def test_get_user_by_id(client: AsyncClient, auth_headers, db_session):
    """Get single user by UUID."""
    user = User(id=uuid.uuid4(), email="specific@example.com", is_admin=False)
    db_session.add(user)
    await db_session.commit()

    response = await client.get(f"/api/v1/users/{user.id}", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == "specific@example.com"


@pytest.mark.asyncio
async def test_get_user_by_id_not_found(client: AsyncClient, auth_headers):
    """Get non-existent user returns 404."""
    fake_id = uuid.uuid4()
    response = await client.get(f"/api/v1/users/{fake_id}", headers=auth_headers)
    assert response.status_code == 404
