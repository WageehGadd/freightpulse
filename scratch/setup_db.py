import asyncio
import os
import sys
import uuid
import hashlib

sys.path.insert(0, os.getcwd())

from app.database import AsyncSessionLocal
from app.models.user import User
from app.models.api_key import ApiKey

async def setup():
    async with AsyncSessionLocal() as db:
        # Create a user
        user_id = uuid.uuid4()
        user = User(
            id=user_id,
            email="admin@freightpulse.test",
            is_active=True,
            is_admin=True,
        )
        db.add(user)
        
        # Create an API key for the user
        raw_key = "test_admin_key_123"
        key_hash = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
        api_key = ApiKey(
            id=uuid.uuid4(),
            user_id=user_id,
            key_hash=key_hash,
            key_prefix="test_",
            name="test_key",
            is_active=True,
        )
        db.add(api_key)
        
        await db.commit()
        print(f"Created admin user {user.email} with API Key: {raw_key}")

if __name__ == "__main__":
    asyncio.run(setup())
