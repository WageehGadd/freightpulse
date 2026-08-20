import hashlib
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.models.api_key import ApiKey
from app.models.user import User
from app.config import settings


def hash_api_key(api_key: str) -> str:
    """Generate SHA-256 hash for API key storage and comparison."""
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


async def get_current_user(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    db: AsyncSession = Depends(get_db),
) -> User:
    if not x_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API Key",
        )

    # Check against global master key
    if settings.API_KEY and x_api_key == settings.API_KEY:
        # Return or find default system admin user
        stmt = select(User).where(User.is_admin == True).limit(1)  # noqa: E712
        user = (await db.execute(stmt)).scalar_one_or_none()
        if not user:
            user = User(email="admin@freightpulse.ai", is_admin=True)
            db.add(user)
            await db.commit()
            await db.refresh(user)
        return user

    key_hash = hash_api_key(x_api_key)
    stmt = select(ApiKey).where(ApiKey.key_hash == key_hash, ApiKey.revoked_at.is_(None))
    api_key_record = (await db.execute(stmt)).scalar_one_or_none()

    if not api_key_record:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API Key",
        )

    user = await db.get(User, api_key_record.user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API Key - User not found",
        )

    return user


async def get_current_admin_user(
    current_user: User = Depends(get_current_user),
) -> User:
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrative privileges required",
        )
    return current_user
