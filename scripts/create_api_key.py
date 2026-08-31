import asyncio
import secrets
import structlog
from uuid import UUID

from app.database import async_session_maker
from app.models.user import User
from app.models.api_key import ApiKey
from app.auth.security import hash_api_key

logger = structlog.get_logger()

async def create_api_key(email: str, name: str):
    async with async_session_maker() as session:
        # 1. Find user or create if they don't exist
        from sqlalchemy import select
        result = await session.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()

        if not user:
            user = User(email=email)
            session.add(user)
            await session.flush()
            logger.info("created_new_user", email=email, user_id=str(user.id))

        # 2. Generate secure token
        token = secrets.token_urlsafe(32)
        plaintext_key = f"fp_live_{token}"
        key_hash = hash_api_key(plaintext_key)
        key_prefix = plaintext_key[:12] # prefix "fp_live_xxxx"

        # 3. Store the hash
        api_key_record = ApiKey(
            user_id=user.id,
            key_hash=key_hash,
            key_prefix=key_prefix,
            name=name
        )
        session.add(api_key_record)
        await session.commit()

        print("\n" + "="*50)
        print("API KEY GENERATED SUCCESSFULLY")
        print("="*50)
        print(f"User ID: {user.id}")
        print(f"Email:   {user.email}")
        print(f"Key Name: {name}")
        print(f"Prefix:  {key_prefix}")
        print("\n*** SECRET KEY ***")
        print(f"{plaintext_key}")
        print("******************\n")
        print("IMPORTANT: This is the ONLY time the plaintext key will be shown.")
        print("It has been securely hashed in the database.")
        print("="*50 + "\n")

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("Usage: python -m scripts.create_api_key <email> <key_name>")
        sys.exit(1)

    email = sys.argv[1]
    name = sys.argv[2]
    asyncio.run(create_api_key(email, name))
