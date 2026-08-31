import structlog
from typing import Callable, Coroutine, Any
from fastapi import Request, HTTPException, status, Depends
import time

from app.redis_client import get_redis
from app.auth.security import get_current_user

logger = structlog.get_logger()

class RateLimiter:
    """
    FastAPI dependency for Redis-backed fixed-window rate limiting.
    Fail-open behavior ensures that if Redis is down, authentication proceeds
    without blocking valid users, prioritizing availability.
    """
    def __init__(self, calls: int = 100, window: int = 60):
        self.calls = calls
        self.window = window

    async def __call__(self, request: Request, current_user: Any = Depends(get_current_user)) -> None:
        if not current_user:
            # Should be impossible due to auth dependency
            return

        redis = get_redis()
        # Derive fixed window block (e.g. integer timestamp / 60)
        current_window = int(time.time() // self.window)
        endpoint = request.url.path

        # Key: rate_limit:{user_id}:{endpoint}:{window_start_timestamp}
        key = f"rate_limit:{current_user.id}:{endpoint}:{current_window}"

        try:
            # Atomic increment
            count = await redis.incr(key)
            if count == 1:
                # Set TTL only when created
                await redis.expire(key, self.window)

            if count > self.calls:
                logger.warning(
                    "rate_limit_exceeded",
                    user_id=str(current_user.id),
                    endpoint=endpoint,
                    calls=count,
                    limit=self.calls
                )
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Rate limit exceeded",
                    headers={"Retry-After": str(self.window)}
                )

        except HTTPException:
            raise
        except Exception as e:
            # Fail-open if Redis is entirely unreachable
            logger.error("rate_limit_redis_failure", error=str(e), user_id=str(current_user.id))
            # Proceed without rate limiting
            return
