from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any, Dict, Optional

from app.redis_client import get_redis

logger = logging.getLogger(__name__)

# Metrics retention: 48 hours (172,800 seconds)
METRICS_TTL_SECONDS = 172_800


class AITelemetry:
    """Non-blocking Redis collector for AI generation telemetry and execution metrics."""

    @staticmethod
    async def record_call(
        feature_name: str,
        prompt_version: str,
        model: str,
        success: bool,
        latency: float,
        input_tokens: int = 0,
        output_tokens: int = 0,
        actual_cost: float = 0.0,
        error_type: Optional[str] = None,  # noqa: UP045
    ) -> None:
        """Record telemetry metrics for an AI call. Always fails open if Redis is down."""
        try:
            redis = get_redis()
            date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            metrics_key = f"ai:metrics:daily:{date_str}:{feature_name}"
            latency_ms = int(latency * 1000)
            cost_micro_usd = int(actual_cost * 1_000_000)

            # Atomic hash pipeline
            pipe = redis.pipeline()
            pipe.hincrby(metrics_key, "requests", 1)
            if success:
                pipe.hincrby(metrics_key, "successes", 1)
            else:
                pipe.hincrby(metrics_key, "errors", 1)

            pipe.hincrby(metrics_key, "input_tokens", input_tokens)
            pipe.hincrby(metrics_key, "output_tokens", output_tokens)
            pipe.hincrby(metrics_key, "cost_micro_usd", cost_micro_usd)
            pipe.hincrby(metrics_key, "total_latency_ms", latency_ms)
            pipe.expire(metrics_key, METRICS_TTL_SECONDS)

            if not success and error_type:
                error_key = f"ai:metrics:errors:{date_str}:{feature_name}"
                pipe.hincrby(error_key, error_type, 1)
                pipe.expire(error_key, METRICS_TTL_SECONDS)

            await pipe.execute()

        except Exception as exc:  # noqa: BLE001
            # Fail-open: Never fail an AI request due to telemetry recording errors
            logger.warning(
                "ai_telemetry_recording_failed",
                extra={
                    "feature_name": feature_name,
                    "error": str(exc),
                },
            )

    @staticmethod
    async def get_daily_metrics(date_str: Optional[str] = None) -> Dict[str, Any]:  # noqa: UP045
        """Fetch aggregated daily metrics across all features."""
        if not date_str:
            date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        features = ["carrier_summarizer", "rate_outlook", "route_brief"]
        feature_metrics: Dict[str, Any] = {}
        totals = {
            "requests": 0,
            "successes": 0,
            "errors": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "cost_usd": 0.0,
            "avg_latency_ms": 0.0,
        }

        total_latency_sum = 0

        try:
            redis = get_redis()
            for feat in features:
                metrics_key = f"ai:metrics:daily:{date_str}:{feat}"
                error_key = f"ai:metrics:errors:{date_str}:{feat}"

                raw_data = await redis.hgetall(metrics_key)
                raw_errors = await redis.hgetall(error_key)

                if not raw_data:
                    feature_metrics[feat] = {
                        "requests": 0,
                        "successes": 0,
                        "errors": 0,
                        "input_tokens": 0,
                        "output_tokens": 0,
                        "cost_usd": 0.0,
                        "avg_latency_ms": 0.0,
                        "error_breakdown": {},
                    }
                    continue

                requests = int(raw_data.get("requests", 0))
                successes = int(raw_data.get("successes", 0))
                errors = int(raw_data.get("errors", 0))
                input_tokens = int(raw_data.get("input_tokens", 0))
                output_tokens = int(raw_data.get("output_tokens", 0))
                cost_usd = int(raw_data.get("cost_micro_usd", 0)) / 1_000_000.0
                latency_ms = int(raw_data.get("total_latency_ms", 0))
                avg_latency = (latency_ms / requests) if requests > 0 else 0.0

                error_breakdown = {k: int(v) for k, v in raw_errors.items()} if raw_errors else {}

                feature_metrics[feat] = {
                    "requests": requests,
                    "successes": successes,
                    "errors": errors,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "cost_usd": round(cost_usd, 6),
                    "avg_latency_ms": round(avg_latency, 2),
                    "error_breakdown": error_breakdown,
                }

                totals["requests"] += requests
                totals["successes"] += successes
                totals["errors"] += errors
                totals["input_tokens"] += input_tokens
                totals["output_tokens"] += output_tokens
                totals["cost_usd"] += cost_usd
                total_latency_sum += latency_ms

            totals["cost_usd"] = round(totals["cost_usd"], 6)
            totals["avg_latency_ms"] = (
                round(total_latency_sum / totals["requests"], 2) if totals["requests"] > 0 else 0.0
            )

        except Exception as exc:  # noqa: BLE001
            logger.warning("ai_telemetry_fetch_failed", extra={"error": str(exc)})

        return {
            "date": date_str,
            "totals": totals,
            "features": feature_metrics,
        }
