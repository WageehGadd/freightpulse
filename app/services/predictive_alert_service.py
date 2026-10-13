"""
Predictive Alert Operationalization Service (T14).
Handles accepted checkpoints, compare-and-set concurrency, deduplication,
and delivery of factual directional transitions via Redis Pub/Sub and WebSockets.
Strictly separates pure evaluator proposals from accepted/delivered events.
"""
import json
import logging
from typing import Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession

from app.redis_client import get_redis
from app.alert_publisher import publish_alert

logger = logging.getLogger(__name__)


class PredictiveAlertService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.redis = get_redis()

    def _checkpoint_key(self, source: str, trade_lane: str, container_type: str) -> str:
        return f"predictive_alert:checkpoint:{source}:{trade_lane}:{container_type}"

    def _dedup_key(self, signal_identity: str) -> str:
        return f"predictive_alert:delivered:{signal_identity}"

    async def get_checkpoint(self, source: str, trade_lane: str, container_type: str) -> Optional[Any]:
        """Load stored alert checkpoint for series from Redis."""
        try:
            from app.schemas.predictive_alert import AlertCheckpoint
            raw = await self.redis.get(self._checkpoint_key(source, trade_lane, container_type))
            if raw:
                data = json.loads(raw)
                return AlertCheckpoint.model_validate(data)
        except Exception as exc:
            logger.warning("predictive_alert_checkpoint_read_failed", extra={"error": str(exc)})
        return None

    async def save_checkpoint(self, source: str, trade_lane: str, container_type: str, checkpoint: Any) -> bool:
        """Persist accepted checkpoint to Redis."""
        try:
            key = self._checkpoint_key(source, trade_lane, container_type)
            payload = checkpoint.model_dump_json() if hasattr(checkpoint, "model_dump_json") else json.dumps(checkpoint)
            await self.redis.set(key, payload)
            return True
        except Exception as exc:
            logger.exception("predictive_alert_checkpoint_save_failed", extra={"error": str(exc)})
            return False

    async def process_series(self, source: str, trade_lane: str, container_type: str) -> Dict[str, Any]:
        """
        Evaluate and conditionally deliver a predictive alert for an exact market series.
        Enforces compare-and-set, deduplication, and transactional dispatch.
        """
        # 1. Acquire distributed lock for this series to enforce atomic CAS
        lock_key = f"lock:predictive_alert:{source}:{trade_lane}:{container_type}"
        acquired = await self.redis.set(lock_key, "1", nx=True, ex=30)
        if not acquired:
            logger.info("predictive_alert_skipped_locked", extra={"series": f"{source}:{trade_lane}"})
            return {"status": "locked"}

        try:
            from app.schemas.decision import SeriesIdentity, DecisionPolicy, DecisionInput
            from app.schemas.predictive_alert import (
                PredictiveAlertInput,
                PredictiveAlertResult,
                AlertStatus,
            )
            from app.services.forecast_persistence import ForecastPersistenceService
            from app.services.forecast_state import ForecastStateCollector, snapshot_forecast
            from app.services.decision_engine import evaluate_decision
            from app.services.reliability import assess_evidence
            from app.services.predictive_alert_evaluator import evaluate_predictive_alert
        except ImportError as err:
            logger.warning("predictive_alert_modules_unavailable", extra={"error": str(err)})
            await self.redis.delete(lock_key)
            return {"status": "unavailable"}

        series = SeriesIdentity(source=source, trade_lane=trade_lane, container_type=container_type)

        try:
            # 2. Retrieve authoritative factual baseline and evaluate decision
            rows = await ForecastPersistenceService(self.session).get_latest_forecasts(
                source=source, trade_lane=trade_lane, container_type=container_type
            )
            if not rows or len(rows) != 1:
                return {"status": "no_forecast"}

            snapshot = snapshot_forecast(rows[0])
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc)
            collector_state = await ForecastStateCollector(self.session).collect(snapshot, now, expected_series=series)

            factual_decision = evaluate_decision(
                DecisionInput(forecast=snapshot, current_state=collector_state),
                DecisionPolicy(),
                now,
            )
            evidence = assess_evidence(factual_decision)

            # 3. Load previous checkpoint
            prev_checkpoint = await self.get_checkpoint(source, trade_lane, container_type)

            # 4. Evaluate predictive alert proposal
            proposal_input = PredictiveAlertInput(
                series=series,
                decision=factual_decision,
                evidence=evidence,
                previous_checkpoint=prev_checkpoint,
            )
            result: PredictiveAlertResult = evaluate_predictive_alert(proposal_input)

            # 5. CAS and delivery
            if result.status == AlertStatus.EMIT:
                # Deduplicate signal
                dedup_k = self._dedup_key(result.signal_identity)
                is_duplicate = await self.redis.get(dedup_k)
                if not is_duplicate:
                    # Save next checkpoint
                    if result.next_checkpoint:
                        await self.save_checkpoint(source, trade_lane, container_type, result.next_checkpoint)

                    # Mark delivered (24-hour expiration)
                    await self.redis.set(dedup_k, "1", ex=86400)

                    # Format alert payload and publish to subscribers
                    alert_payload = {
                        "id": f"pred-{result.signal_identity[:12]}",
                        "alert_type": "predictive_alert",
                        "trade_lane": trade_lane,
                        "category": result.category.value if hasattr(result.category, "value") else str(result.category),
                        "transition": result.transition.value if hasattr(result.transition, "value") else str(result.transition),
                        "message": f"Predictive freight signal transition: {result.transition} on {trade_lane}",
                        "signal_identity": result.signal_identity,
                        "reasons": [r.value if hasattr(r, "value") else str(r) for r in result.reasons],
                    }
                    await publish_alert(alert_payload)
                    logger.info("predictive_alert_emitted", extra={"series": f"{source}:{trade_lane}", "transition": str(result.transition)})
                    return {"status": "emitted", "transition": str(result.transition)}
                else:
                    return {"status": "suppressed_duplicate"}

            elif result.status in (AlertStatus.BASELINE_ONLY, AlertStatus.SUPPRESS):
                if result.next_checkpoint:
                    await self.save_checkpoint(source, trade_lane, container_type, result.next_checkpoint)
                return {"status": result.status.value if hasattr(result.status, "value") else str(result.status)}

            return {"status": "invalid_or_suppressed"}

        finally:
            await self.redis.delete(lock_key)
