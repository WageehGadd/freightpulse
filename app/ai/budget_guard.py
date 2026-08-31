from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Tuple

from app.config import settings
from app.redis_client import get_redis

logger = logging.getLogger(__name__)

RATE_TTL_SECONDS = 120
BUDGET_TTL_SECONDS = 172_800


class AIBudgetExceededError(Exception):
    """Raised when an AI request would exceed the daily USD budget."""
    pass


class AIRateLimitExceededError(Exception):
    """Raised when an AI request exceeds the per-minute request rate limit."""
    pass


# Lua scripts for atomic Redis execution

LUA_CHECK_RATE_LIMIT = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
    redis.call('EXPIRE', KEYS[1], ARGV[2])
end
local max_req = tonumber(ARGV[1])
if max_req > 0 and current > max_req then
    return 0
end
return 1
"""

LUA_RESERVE_BUDGET = """
local actual = tonumber(redis.call('HGET', KEYS[1], 'actual_micro_usd') or '0')
local reserved = tonumber(redis.call('HGET', KEYS[1], 'reserved_micro_usd') or '0')
local est = tonumber(ARGV[1])
local budget = tonumber(ARGV[2])

if budget > 0 and (actual + reserved + est) > budget then
    return 0
end

redis.call('HINCRBY', KEYS[1], 'reserved_micro_usd', est)
redis.call('EXPIRE', KEYS[1], ARGV[3])
return 1
"""

LUA_RECONCILE_SUCCESS = """
local reserved = tonumber(redis.call('HGET', KEYS[1], 'reserved_micro_usd') or '0')
local est = tonumber(ARGV[1])
local actual = tonumber(ARGV[2])

local new_reserved = math.max(0, reserved - est)
redis.call('HSET', KEYS[1], 'reserved_micro_usd', new_reserved)
redis.call('HINCRBY', KEYS[1], 'actual_micro_usd', actual)
redis.call('EXPIRE', KEYS[1], ARGV[3])
return 1
"""

LUA_RELEASE_RESERVATION = """
local reserved = tonumber(redis.call('HGET', KEYS[1], 'reserved_micro_usd') or '0')
local est = tonumber(ARGV[1])

local new_reserved = math.max(0, reserved - est)
redis.call('HSET', KEYS[1], 'reserved_micro_usd', new_reserved)
redis.call('EXPIRE', KEYS[1], ARGV[2])
return 1
"""


class BudgetGuard:
    """Atomic Redis-backed budget reservation and rate limiter guard."""

    @staticmethod
    def estimate_input_tokens(text: str) -> int:
        """Deterministic input token estimation: ~4 chars per token + safety buffer of 10."""
        if not text:
            return 10
        return (len(text) // 4) + 10

    @classmethod
    def estimate_request_cost(
        cls,
        system_prompt: str,
        user_content: str,
        max_tokens: int,
        input_cost_per_1m: float = 0.15,
        output_cost_per_1m: float = 0.60,
    ) -> float:
        """Compute conservative pre-call cost estimate for budget reservation."""
        est_input_tokens = cls.estimate_input_tokens(system_prompt + user_content)
        est_input_cost = (est_input_tokens / 1_000_000.0) * input_cost_per_1m
        est_output_cost = (max_tokens / 1_000_000.0) * output_cost_per_1m
        return est_input_cost + est_output_cost

    @classmethod
    async def check_and_reserve(
        cls,
        estimated_cost_usd: float,
        feature_name: str = "unknown",
    ) -> int:
        """Atomically enforce rate limit and reserve estimated cost in Redis.

        Returns estimated_micro_usd for subsequent reconciliation.
        Raises AIRateLimitExceededError or AIBudgetExceededError if limits are breached.
        """
        max_rate = getattr(settings, "AI_MAX_REQUESTS_PER_MINUTE", 0)
        daily_budget = getattr(settings, "AI_DAILY_BUDGET_USD", 0.0)
        fail_open = getattr(settings, "AI_FAIL_OPEN_ON_REDIS_ERROR", True)

        estimated_micro_usd = int(estimated_cost_usd * 1_000_000)
        budget_micro_usd = int(daily_budget * 1_000_000)

        # No limits configured -> pass fast
        if max_rate <= 0 and daily_budget <= 0.0:
            return estimated_micro_usd

        try:
            redis = get_redis()
            now = datetime.now(timezone.utc)
            minute_ts = now.strftime("%Y%m%d%H%M")
            date_str = now.strftime("%Y-%m-%d")

            rate_key = f"ai:budget:rate:{minute_ts}"
            budget_key = f"ai:budget:daily:{date_str}"

            # 1. Rate limit check via Lua script
            if max_rate > 0:
                rate_allowed = await redis.eval(
                    LUA_CHECK_RATE_LIMIT, 1, rate_key, max_rate, RATE_TTL_SECONDS
                )
                if not rate_allowed:
                    logger.warning(
                        "ai_rate_limit_exceeded",
                        extra={"feature_name": feature_name, "max_rate": max_rate},
                    )
                    raise AIRateLimitExceededError(
                        f"AI request rate limit exceeded ({max_rate} req/min)."
                    )

            # 2. Budget reservation check via Lua script
            if daily_budget > 0.0:
                budget_allowed = await redis.eval(
                    LUA_RESERVE_BUDGET, 1, budget_key, estimated_micro_usd, budget_micro_usd, BUDGET_TTL_SECONDS
                )
                if not budget_allowed:
                    logger.warning(
                        "ai_budget_exceeded",
                        extra={"feature_name": feature_name, "daily_budget": daily_budget},
                    )
                    raise AIBudgetExceededError(
                        f"AI daily budget limit reached (${daily_budget:.2f})."
                    )

        except (AIRateLimitExceededError, AIBudgetExceededError):
            raise
        except Exception as exc:  # noqa: BLE001
            if fail_open:
                logger.warning(
                    "ai_budget_guard_redis_error_fail_open",
                    extra={"feature_name": feature_name, "error": str(exc)},
                )
            else:
                logger.error("ai_budget_guard_redis_error_strict", extra={"error": str(exc)})
                raise

        return estimated_micro_usd

    @classmethod
    async def reconcile_success(cls, estimated_micro_usd: int, actual_cost_usd: float) -> None:
        """Atomically convert reserved budget to actual spend after a successful call."""
        fail_open = getattr(settings, "AI_FAIL_OPEN_ON_REDIS_ERROR", True)
        actual_micro_usd = int(actual_cost_usd * 1_000_000)
        now = datetime.now(timezone.utc)
        date_str = now.strftime("%Y-%m-%d")
        budget_key = f"ai:budget:daily:{date_str}"

        try:
            redis = get_redis()
            await redis.eval(
                LUA_RECONCILE_SUCCESS, 1, budget_key, estimated_micro_usd, actual_micro_usd, BUDGET_TTL_SECONDS
            )
        except Exception as exc:  # noqa: BLE001
            if fail_open:
                logger.warning("ai_budget_reconciliation_failed_fail_open", extra={"error": str(exc)})
            else:
                raise

    @classmethod
    async def release_reservation(cls, estimated_micro_usd: int) -> None:
        """Atomically refund estimated reservation when a call fails or times out."""
        fail_open = getattr(settings, "AI_FAIL_OPEN_ON_REDIS_ERROR", True)
        now = datetime.now(timezone.utc)
        date_str = now.strftime("%Y-%m-%d")
        budget_key = f"ai:budget:daily:{date_str}"

        try:
            redis = get_redis()
            await redis.eval(
                LUA_RELEASE_RESERVATION, 1, budget_key, estimated_micro_usd, BUDGET_TTL_SECONDS
            )
        except Exception as exc:  # noqa: BLE001
            if fail_open:
                logger.warning("ai_budget_release_failed_fail_open", extra={"error": str(exc)})
            else:
                raise

    @classmethod
    async def get_budget_status(cls, date_str: Optional[str] = None) -> Tuple[float, float, float]:  # noqa: UP045
        """Get (actual_usd, reserved_usd, committed_usd) for a date string."""
        if not date_str:
            date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        budget_key = f"ai:budget:daily:{date_str}"

        try:
            redis = get_redis()
            raw_data = await redis.hgetall(budget_key)
            actual_micro = int(raw_data.get("actual_micro_usd", 0))
            reserved_micro = int(raw_data.get("reserved_micro_usd", 0))

            actual_usd = actual_micro / 1_000_000.0
            reserved_usd = reserved_micro / 1_000_000.0
            committed_usd = actual_usd + reserved_usd
            return actual_usd, reserved_usd, committed_usd
        except Exception as exc:  # noqa: BLE001
            logger.warning("ai_budget_status_fetch_failed", extra={"error": str(exc)})
            return 0.0, 0.0, 0.0
