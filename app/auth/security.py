import hashlib
import structlog
from datetime import datetime, timedelta
from typing import Optional
from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader, HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.user import User
from app.models.api_key import ApiKey
from app.config import settings

logger = structlog.get_logger()

# Password hashing
# pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
pwd_context = CryptContext(
    schemes=["argon2", "bcrypt"],
    deprecated=["bcrypt"],
)

# JWT settings
SECRET_KEY = getattr(settings, "SECRET_KEY", "your-secret-key-change-this-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 days

# We strictly enforce X-API-Key as approved, and this primitive integrates automatically with Swagger UI.
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

# JWT Bearer token authentication
security = HTTPBearer(auto_error=False)

def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain password against a hashed password."""
    return pwd_context.verify(plain_password, hashed_password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create a JWT access token."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def decode_access_token(token: str) -> Optional[dict]:
    """Decode and verify a JWT access token."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None

def hash_api_key(key: str) -> str:
    """Generate SHA-256 hash of the plaintext API key."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()

async def get_current_user_from_token(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security),
    db: AsyncSession = Depends(get_db)
) -> Optional[User]:
    """
    Get current user from JWT token (optional).
    Returns None if no token is provided or if token is invalid.
    """
    if credentials is None:
        return None

    token = credentials.credentials
    payload = decode_access_token(token)
    if payload is None:
        return None

    user_id: str = payload.get("sub")
    if user_id is None:
        return None

    try:
        stmt = select(User).where(User.id == user_id)
        result = await db.execute(stmt)
        user = result.scalar_one_or_none()
        return user
    except Exception:
        return None

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


async def get_current_admin_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """
    FastAPI Dependency ensuring the current user has administrative privileges.
    Raises 403 FORBIDDEN if the user is not an admin.
    """
    if not getattr(current_user, "is_admin", False):
        logger.warning("auth_forbidden_admin_required", user_id=str(current_user.id))
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrative privileges required",
        )
    return current_user
