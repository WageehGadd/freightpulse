from fastapi import Depends, HTTPException, status
from app.auth.security import get_current_user
from app.models.user import User
from app.redis_client import get_redis
import structlog

logger = structlog.get_logger()

MAX_REQUESTS_PER_MINUTE = 100
WINDOW_SECONDS = 60


async def RateLimiter(user: User = Depends(get_current_user)) -> None:
    """FastAPI dependency for per-user rate limiting via Redis."""
    try:
        redis = get_redis()
        key = f"rate_limit:{user.id}"
        current = await redis.incr(key)
        if current == 1:
            await redis.expire(key, WINDOW_SECONDS)

        if current > MAX_REQUESTS_PER_MINUTE:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded: maximum {MAX_REQUESTS_PER_MINUTE} requests per minute",
            )
    except HTTPException:
        raise
    except Exception as exc:
        # Fail open on Redis connectivity/internal failure
        logger.warning("rate_limiter_redis_error_fail_open", error=str(exc))
        return
