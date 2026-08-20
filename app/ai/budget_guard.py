import logging
from datetime import date
from typing import Tuple
from app.config import settings
from app.redis_client import get_redis

logger = logging.getLogger(__name__)


class AIRateLimitExceededError(Exception):
    """Raised when AI requests per minute limit is exceeded."""


class AIBudgetExceededError(Exception):
    """Raised when AI daily spend budget is exceeded."""


class BudgetGuard:
    RATE_LIMIT_LUA = """
    local key = KEYS[1]
    local max_req = tonumber(ARGV[1])
    local curr = redis.call('INCR', key)
    if curr == 1 then
        redis.call('EXPIRE', key, 60)
    end
    if max_req > 0 and curr > max_req then
        return 0
    end
    return 1
    """

    RESERVE_BUDGET_LUA = """
    local key = KEYS[1]
    local est = tonumber(ARGV[1])
    local budget = tonumber(ARGV[2])

    local actual = tonumber(redis.call('HGET', key, 'actual_micro_usd') or 0)
    local reserved = tonumber(redis.call('HGET', key, 'reserved_micro_usd') or 0)

    if budget > 0 and (actual + reserved + est) > budget then
        return 0
    end

    redis.call('HINCRBY', key, 'reserved_micro_usd', est)
    redis.call('EXPIRE', key, 172800)
    return 1
    """

    RECONCILE_LUA = """
    local key = KEYS[1]
    local est = tonumber(ARGV[1])
    local actual = tonumber(ARGV[2])

    local curr_reserved = tonumber(redis.call('HGET', key, 'reserved_micro_usd') or 0)
    local curr_actual = tonumber(redis.call('HGET', key, 'actual_micro_usd') or 0)

    local new_reserved = math.max(0, curr_reserved - est)
    redis.call('HSET', key, 'reserved_micro_usd', new_reserved)
    redis.call('HSET', key, 'actual_micro_usd', curr_actual + actual)
    return 1
    """

    RELEASE_LUA = """
    local key = KEYS[1]
    local est = tonumber(ARGV[1])

    local curr_reserved = tonumber(redis.call('HGET', key, 'reserved_micro_usd') or 0)
    local new_reserved = math.max(0, curr_reserved - est)
    redis.call('HSET', key, 'reserved_micro_usd', new_reserved)
    return 1
    """

    @classmethod
    def estimate_request_cost(
        cls,
        system_prompt: str,
        user_content: str,
        max_tokens: int = 1000,
        input_cost_per_1m: float = 0.15,
        output_cost_per_1m: float = 0.60,
    ) -> float:
        est_input_tokens = max(1, len(system_prompt + user_content) // 4)
        est_output_tokens = max_tokens
        cost = (est_input_tokens / 1_000_000.0) * input_cost_per_1m + (
            est_output_tokens / 1_000_000.0
        ) * output_cost_per_1m
        return cost

    @classmethod
    async def check_and_reserve(cls, cost_usd: float, feature: str = "ai") -> int:
        est_micro = int(cost_usd * 1_000_000)
        max_req = getattr(settings, "AI_MAX_REQUESTS_PER_MINUTE", 60)
        daily_budget_usd = getattr(settings, "AI_DAILY_BUDGET_USD", 10.0)
        budget_micro = int(daily_budget_usd * 1_000_000)

        today_str = date.today().isoformat()
        rate_key = f"ai:rate_limit:{today_str}"
        budget_key = f"ai:budget:{today_str}"

        try:
            redis = get_redis()
            # 1. Check Rate Limit
            rate_ok = await redis.eval(cls.RATE_LIMIT_LUA, 1, rate_key, max_req)
            if rate_ok == 0:
                raise AIRateLimitExceededError(
                    f"AI rate limit of {max_req} requests/minute exceeded"
                )

            # 2. Check & Reserve Budget
            budget_ok = await redis.eval(
                cls.RESERVE_BUDGET_LUA, 1, budget_key, est_micro, budget_micro
            )
            if budget_ok == 0:
                raise AIBudgetExceededError(
                    f"AI daily budget of ${daily_budget_usd:.2f} exceeded"
                )

            return est_micro

        except (AIRateLimitExceededError, AIBudgetExceededError):
            raise
        except Exception as exc:
            if getattr(settings, "AI_FAIL_OPEN_ON_REDIS_ERROR", True):
                logger.warning(
                    f"BudgetGuard redis failure, failing open: {exc}"
                )
                return est_micro
            raise

    @classmethod
    async def reconcile_success(cls, est_micro: int, actual_cost_usd: float) -> None:
        actual_micro = int(actual_cost_usd * 1_000_000)
        today_str = date.today().isoformat()
        budget_key = f"ai:budget:{today_str}"
        try:
            redis = get_redis()
            await redis.eval(cls.RECONCILE_LUA, 1, budget_key, est_micro, actual_micro)
        except Exception as exc:
            logger.warning(f"Failed to reconcile budget spend: {exc}")

    @classmethod
    async def release_reservation(cls, est_micro: int) -> None:
        today_str = date.today().isoformat()
        budget_key = f"ai:budget:{today_str}"
        try:
            redis = get_redis()
            await redis.eval(cls.RELEASE_LUA, 1, budget_key, est_micro)
        except Exception as exc:
            logger.warning(f"Failed to release budget reservation: {exc}")

    @classmethod
    async def get_budget_status(cls) -> Tuple[float, float, float]:
        today_str = date.today().isoformat()
        budget_key = f"ai:budget:{today_str}"
        try:
            redis = get_redis()
            data = await redis.hgetall(budget_key)
            actual_micro = int(data.get("actual_micro_usd", 0) or 0)
            reserved_micro = int(data.get("reserved_micro_usd", 0) or 0)
            actual_usd = actual_micro / 1_000_000.0
            reserved_usd = reserved_micro / 1_000_000.0
            committed_usd = actual_usd + reserved_usd
            return actual_usd, reserved_usd, committed_usd
        except Exception as exc:
            logger.warning(f"Failed to get budget status from redis: {exc}")
            return 0.0, 0.0, 0.0
