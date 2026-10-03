"""Resolve one series and preserve the quantitative generation used by narration.
No Redis narration cache: validated persisted v2 output is the reuse boundary.
"""
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from fastapi import HTTPException
from sqlalchemy import select, func, update
from sqlalchemy.dialects.postgresql import insert
from app.models import RateTrend, RateForecast, FreightRate, RateOutlook
from app.services.forecast_persistence import ForecastPersistenceService
from app.services.data_quality import DataQualityService
from app.services.forecast_presentation import to_forecast_response
from app.schemas.outlook import GroundedOutlookResponse, NarrationResponse, ExactForecastValue
from app.schemas.forecast import RateForecastResponse
from app.schemas.ai_outputs import GroundedRateOutlookOutput

MAX_ATTEMPTS = 3
RETRY_COOLDOWN_SECONDS = 60
RETRYABLE_FAILURES = {"timeout", "service_unavailable", "queue_unavailable"}
PROMPT_VERSION = "v2"  # Grounded path is intentionally pinned; v1 cannot be selected.

class RateOutlookService:
    def __init__(self, session):
        self.session = session

    async def context_state(self, trend, forecast, generation=None):
        latest_date = await self.session.scalar(select(func.max(FreightRate.rate_date)).where(
            FreightRate.source == forecast.source, FreightRate.trade_lane == forecast.trade_lane,
            FreightRate.container_type == forecast.container_type))
        if latest_date is None:
            return "source_unavailable", "Matching source observations are unavailable."
        if latest_date > forecast.latest_observation_date:
            return "superseded", "Newer source observations require forecast regeneration."
        latest = await ForecastPersistenceService(self.session).get_latest_forecasts(
            forecast.source, forecast.trade_lane, forecast.container_type)
        if not latest or latest[0].id != forecast.id or (generation and forecast.generated_at != generation):
            return "superseded", "The selected forecast generation is no longer current."
        latest_trend_date = await self.session.scalar(select(func.max(RateTrend.computed_date)).where(
            RateTrend.trade_lane == forecast.trade_lane))
        if trend.trade_lane != forecast.trade_lane or trend.computed_date < forecast.latest_observation_date or trend.computed_date != latest_trend_date:
            return "historical_trend", "The requested trend is historical or mismatched; request the current trend."
        return "current", None

    async def create(self, trend_id, source=None, container_type=None, retry=False):
        trend = await self.session.get(RateTrend, trend_id)
        if trend is None:
            raise HTTPException(404, "Rate trend not found")
        if (source is None) != (container_type is None):
            raise HTTPException(422, "Supply source and container_type together")
        rows = await ForecastPersistenceService(self.session).get_latest_forecasts(
            source=source, trade_lane=trend.trade_lane, container_type=container_type)
        if not rows:
            raise HTTPException(404, "Matching quantitative forecast unavailable; generate forecasts through T06")
        if len(rows) != 1:
            raise HTTPException(409, "Multiple forecast series exist; supply source and container_type")
        forecast = rows[0]
        state, warning = await self.context_state(trend, forecast)
        if state != "current":
            raise HTTPException(409, warning)
        now = datetime.now(timezone.utc)
        snapshot = to_forecast_response(forecast, now).model_dump(mode="json")
        actual, predicted = forecast.latest_actual_rate, forecast.predicted_rate
        snapshot["exact_values"] = ExactForecastValue(
            predicted_rate=predicted, latest_actual_rate=actual,
            expected_change=predicted-actual,
            expected_change_pct=((predicted-actual)/actual*Decimal(100)).quantize(Decimal("0.0001")) if actual else None,
        ).model_dump(mode="json")
        stmt = insert(RateOutlook).values(id=uuid.uuid4(), trend_id=trend.id,
            forecast_id=forecast.id, forecast_generated_at=forecast.generated_at,
            prompt_version=PROMPT_VERSION, evidence_snapshot=snapshot, status="pending")
        stmt = stmt.on_conflict_do_nothing(constraint="uq_rate_outlook_generation").returning(RateOutlook)
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        if row is None:
            row = (await self.session.execute(select(RateOutlook).where(
                RateOutlook.trend_id==trend.id, RateOutlook.forecast_id==forecast.id,
                RateOutlook.forecast_generated_at==forecast.generated_at,
                RateOutlook.prompt_version==PROMPT_VERSION))).scalar_one()
        if retry:
            # Compare-and-set: concurrent retry requests cannot reset generating/completed work.
            await self.session.execute(update(RateOutlook).where(
                RateOutlook.id == row.id, RateOutlook.status == "failed",
                RateOutlook.failure_code.in_(RETRYABLE_FAILURES),
                RateOutlook.attempt_count < MAX_ATTEMPTS,
                RateOutlook.retry_after <= now,
            ).values(status="pending", error_message=None, failure_code=None,
                     retry_after=None, completed_at=None))
        await self.session.commit()
        await self.session.refresh(row)
        return row

    async def mark_enqueue_failed(self, row):
        # A broker may accept a job before reporting an error. Do not clobber a worker claim.
        await self.session.execute(update(RateOutlook).where(
            RateOutlook.id == row.id, RateOutlook.status == "pending",
        ).values(status="failed", failure_code="queue_unavailable",
                 attempt_count=RateOutlook.attempt_count + 1,
                 retry_after=datetime.now(timezone.utc) + timedelta(seconds=RETRY_COOLDOWN_SECONDS),
                 error_message="Narration could not be queued. Quantitative evidence remains available."))
        await self.session.commit()
        await self.session.refresh(row)

    async def read(self, outlook_id):
        row = await self.session.get(RateOutlook, outlook_id)
        if row is None:
            raise HTTPException(404, "Rate outlook not found")
        forecast = await self.session.get(RateForecast, row.forecast_id)
        trend = await self.session.get(RateTrend, row.trend_id)
        state, warning = await self.context_state(trend, forecast, row.forecast_generated_at)
        snapshot = row.evidence_snapshot
        # Pydantic constructs a new object; never mutate the stored generation snapshot.
        quantitative = RateForecastResponse.model_validate(snapshot)
        now = datetime.now(timezone.utc)
        freshness, _ = DataQualityService.evaluate_freight_rate_freshness(
            quantitative.provenance.latest_observation_date, now)
        quantitative.provenance.current_input_freshness = freshness
        quantitative.provenance.freshness_evaluated_at = now
        text = row.outlook_text
        if text is not None:
            try:
                text = GroundedRateOutlookOutput.model_validate({"outlook_text": text}).outlook_text
            except ValueError:
                text = None
                warning = "Stored narration failed validation."
        return GroundedOutlookResponse(id=row.id, trend_id=row.trend_id, forecast_id=row.forecast_id,
            prompt_version=row.prompt_version, created_at=row.created_at, completed_at=row.completed_at,
            quantitative=quantitative, exact_values=ExactForecastValue.model_validate(snapshot["exact_values"]),
            context_state=state, context_warning=warning,
            effective_live_decision_eligible=quantitative.safety.live_decision_eligible and freshness in ("fresh", "aging") and state=="current",
            narration=NarrationResponse(status=row.status if text or row.status!="completed" else "failed",
                text=text, error_message=row.error_message or (warning if row.status=="completed" and text is None else None),
                attempt_count=row.attempt_count,
                retryable=row.status=="failed" and row.failure_code in RETRYABLE_FAILURES and row.attempt_count < MAX_ATTEMPTS,
                retry_after=row.retry_after, input_evidence=row.narration_input))
