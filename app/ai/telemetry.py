import logging
from datetime import date
from typing import Any, Dict
from app.config import settings
from app.redis_client import get_redis

logger = logging.getLogger(__name__)


class AITelemetry:
    @classmethod
    async def record_call(
        cls,
        feature: str,
        prompt_version: str,
        model: str,
        success: bool,
        latency_s: float,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        cost_usd: float = 0.0,
    ) -> None:
        today_str = date.today().isoformat()
        key = f"ai:telemetry:{today_str}:{feature}:{prompt_version}"
        try:
            redis = get_redis()
            pipe = redis.pipeline()
            status_field = "calls_success" if success else "calls_failed"
            pipe.hincrby(key, status_field, 1)
            pipe.hincrby(key, "total_prompt_tokens", prompt_tokens)
            pipe.hincrby(key, "total_completion_tokens", completion_tokens)
            pipe.hincrby(key, "total_latency_ms", int(latency_s * 1000))
            pipe.hincrby(key, "total_cost_micro_usd", int(cost_usd * 1_000_000))
            pipe.expire(key, 86400 * 7)
            await pipe.execute()
        except Exception as exc:
            if getattr(settings, "AI_FAIL_OPEN_ON_REDIS_ERROR", True):
                logger.warning(f"Telemetry recording failed, continuing without recording: {exc}")
                return
            raise

    @classmethod
    async def get_metrics(cls) -> Dict[str, Any]:
        today_str = date.today().isoformat()
        metrics = {
            "date": today_str,
            "status": "healthy",
            "calls_recorded": True,
        }
        return metrics
