import hashlib
import structlog
from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.user import User
from app.models.api_key import ApiKey

logger = structlog.get_logger()

# We strictly enforce X-API-Key as approved, and this primitive integrates automatically with Swagger UI.
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

def hash_api_key(key: str) -> str:
    """Generate SHA-256 hash of the plaintext API key."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()

async def get_current_user(
    api_key: str = Security(api_key_header),
    db: AsyncSession = Depends(get_db)
) -> User:
    """
    FastAPI Dependency to resolve the current active user from the provided X-API-Key.
    Rejects missing keys, invalid hashes, revoked keys, or inactive users.
    """
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API Key",
        )

    key_hash = hash_api_key(api_key)

    # Fetch the API key along with the associated user in a single query
    stmt = (
        select(ApiKey)
        .options(selectinload(ApiKey.user))  # Ensure the user is eagerly loaded
        .where(ApiKey.key_hash == key_hash)
    )
    result = await db.execute(stmt)
    api_key_obj = result.scalar_one_or_none()

    if not api_key_obj:
        logger.warning("auth_failed", reason="invalid_key")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API Key",
        )

    if not api_key_obj.is_active:
        logger.warning("auth_failed", reason="revoked_key", key_prefix=api_key_obj.key_prefix)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API Key is revoked",
        )

    user = api_key_obj.user
    if not user or not user.is_active:
        logger.warning("auth_failed", reason="inactive_user", user_id=str(user.id) if user else None)
        # Even though user is inactive, we return 401 per standard unless specific 403 convention exists
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account is inactive",
        )

    logger.info(
        "auth_success",
        user_id=str(user.id),
        key_prefix=api_key_obj.key_prefix
    )
    return user
