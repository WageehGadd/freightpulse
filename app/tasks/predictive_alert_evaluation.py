"""Operational T14 boundary: persisted checkpoints, locked CAS and tenant delivery."""
import asyncio
import logging
from celery import shared_task
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from app.alert_publisher import publish_alert_sync
from app.database import AsyncSessionLocal
from app.models.rate_alert import PredictiveAlertCheckpoint, PredictiveAlertEvent, PredictiveAlertSubscription
from app.schemas.decision import SeriesIdentity
from app.schemas.predictive_alert import AlertCheckpoint, PredictiveAlertInput, AlertStatus
from app.services.decision_api import DecisionAPIService
from app.services.predictive_alert_evaluator import evaluate_predictive_alert

logger = logging.getLogger(__name__)


async def _evaluate_all():
    delivered, checked, failed = [], 0, 0
    async with AsyncSessionLocal() as session:
        subscriptions = (await session.execute(select(PredictiveAlertSubscription).where(
            PredictiveAlertSubscription.is_active == True))).scalars().all()
        # End the read transaction before opening per-subscription locked CAS transactions.
        await session.commit()
        for subscription in subscriptions:
            checked += 1
            try:
                async with session.begin():
                    locked = await session.scalar(select(PredictiveAlertSubscription).where(
                        PredictiveAlertSubscription.id == subscription.id).with_for_update())
                    checkpoint_row = await session.get(PredictiveAlertCheckpoint, locked.id, with_for_update=True)
                    previous = AlertCheckpoint.model_validate(checkpoint_row.checkpoint, strict=True) if checkpoint_row else None
                    context = await DecisionAPIService(session).context(locked.source, locked.trade_lane, locked.container_type)
                    if context is None:
                        continue
                    result = evaluate_predictive_alert(PredictiveAlertInput(
                        series=SeriesIdentity(source=locked.source, trade_lane=locked.trade_lane, container_type=locked.container_type),
                        decision=context.decision, evidence=context.evidence, previous_checkpoint=previous))
                    if result.status == AlertStatus.INVALID_INPUT or result.next_checkpoint is None:
                        continue
                    checkpoint_data = result.next_checkpoint.model_dump(mode="json")
                    if checkpoint_row:
                        checkpoint_row.accepted_token = result.next_checkpoint.accepted_checkpoint_token
                        checkpoint_row.checkpoint = checkpoint_data
                    else:
                        session.add(PredictiveAlertCheckpoint(subscription_id=locked.id,
                            accepted_token=result.next_checkpoint.accepted_checkpoint_token, checkpoint=checkpoint_data))
                    if result.status == AlertStatus.EMIT:
                        payload = result.model_dump(mode="json")
                        stmt = insert(PredictiveAlertEvent).values(subscription_id=locked.id, user_id=locked.user_id,
                            signal_identity=result.signal_identity, transition=result.transition.value,
                            category=result.category.value, payload=payload).on_conflict_do_nothing(
                                constraint="uq_predictive_alert_signal").returning(PredictiveAlertEvent.id)
                        inserted = await session.scalar(stmt)
                        if inserted is not None:
                            delivered.append((str(locked.user_id), payload))
            except Exception:
                failed += 1
                logger.exception("predictive_alert_subscription_failed", subscription_id=str(subscription.id))
        # commits occur per subscription transaction
    for user_id, payload in delivered:
        publish_alert_sync({"alert_type": "predictive_alert", "message": "Predictive alert transition detected", "payload": payload}, user_id=user_id)
    return {"checked": checked, "delivered": len(delivered), "failed": failed}


@shared_task(bind=True, max_retries=2, default_retry_delay=60)
def evaluate_predictive_alerts(self):
    try:
        return asyncio.run(_evaluate_all())
    except Exception as exc:
        raise self.retry(exc=exc) from exc
