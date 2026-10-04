"""Read-only exact-series T06/T08/T09 composition; no narration or generation."""
from datetime import datetime, timezone
from decimal import Decimal, Context, ROUND_HALF_EVEN, localcontext

from app.schemas.decision import Decision, DecisionInput, DecisionPolicy, SeriesIdentity
from app.schemas.decision_api import (
    DecisionAPIResponse, DecisionSeries, DecisionForecast, PublicDecision,
    PublicSampleEvidence, PublicHistoricalError, PublicDirectionalEvidence,
    PublicNormalizedSignals, PublicEvidenceFactor, PublicEvidence,
    PublicCurrentState, PublicPolicy, DecisionProvenance,
)
from app.services.forecast_persistence import ForecastPersistenceService
from app.services.forecast_state import ForecastStateCollector, snapshot_forecast
from app.services.decision_engine import evaluate_decision
from app.services.reliability import assess_evidence, EvidenceInputError


def utc_now():
    """One application-owned request instant, injectable in deterministic tests."""
    return datetime.now(timezone.utc)


def _finite_decimal(value):
    return value if isinstance(value, Decimal) and value.is_finite() else None


def to_public_response(decision, evidence):
    """Map approved values once without changing caller Decimal settings/flags."""
    # This helper is also usable outside the context-isolated HTTP composition.
    with localcontext(Context(prec=28, rounding=ROUND_HALF_EVEN)):
        return _to_public_response(decision, evidence)


def _to_public_response(decision, evidence):
    """Do not recompute state or duplicate snapshots."""
    f = decision.forecast_identity
    s = evidence.current_state
    if (f is None or s is None or evidence.provenance is None
            or evidence.decision_result != decision or decision.decision == Decision.UNAVAILABLE):
        raise EvidenceInputError('Artifact-backed composition is inconsistent')
    errors = evidence.historical_error
    return DecisionAPIResponse(
        identity=DecisionSeries(**f.series.model_dump()),
        forecast=DecisionForecast(forecast_id=f.forecast_id,
            predicted_rate=_finite_decimal(f.predicted_rate),
            latest_actual_rate=_finite_decimal(f.latest_actual_rate),
            latest_observation_date=f.latest_observation_date,
            forecast_for_date=f.forecast_for_date, forecast_horizon=f.forecast_horizon),
        decision=PublicDecision(decision=decision.decision, actionable=decision.actionable,
            movement=decision.movement,
            absolute_change=_finite_decimal(decision.signals.absolute_change),
            percentage_change=_finite_decimal(decision.signals.percentage_change),
            error_scale=_finite_decimal(decision.signals.error_scale),
            movement_within_error_scale=evidence.decision_margin.movement_within_error_scale,
            reasons=decision.reasons, limitations=decision.limitations),
        evidence=PublicEvidence(historical_evidence_status=evidence.historical_evidence_status,
            sample_sufficiency_status=evidence.sample_sufficiency_status,
            decision_evidence_status=evidence.decision_evidence_status,
            sample_evidence=PublicSampleEvidence(
                history_observations=evidence.sample_evidence.history_observations,
                evaluation_points=evidence.sample_evidence.evaluation_points,
                data_readiness=evidence.sample_evidence.data_readiness),
            historical_error=PublicHistoricalError(mae=errors.mae, rmse=errors.rmse, smape=errors.smape),
            directional_evidence=PublicDirectionalEvidence(
                directional_accuracy=evidence.directional_evidence.directional_accuracy),
            normalized_signals=PublicNormalizedSignals(
                mae_relative_to_latest_actual_pct=errors.mae_relative_to_latest_actual_pct,
                rmse_relative_to_latest_actual_pct=errors.rmse_relative_to_latest_actual_pct,
                movement_to_mae_ratio=errors.movement_to_mae_ratio),
            factors=tuple(PublicEvidenceFactor(**factor.model_dump()) for factor in evidence.factors),
            assessment_limitations=evidence.assessment_limitations),
        current_state=PublicCurrentState(current_input_freshness=s.current_input_freshness,
            input_freshness_at_generation=f.input_freshness_at_generation,
            latest_source_date=s.latest_source_date, context_state=s.context_state,
            source_superseded=s.source_superseded, forecast_superseded=s.forecast_superseded,
            stored_live_decision_eligible=s.stored_live_decision_eligible,
            effective_live_decision_eligible=s.effective_live_decision_eligible),
        policy=PublicPolicy(movement_threshold_pct=decision.policy.movement_threshold_pct,
            min_history_observations=decision.policy.min_history_observations,
            min_evaluation_points=decision.policy.min_evaluation_points,
            error_multiplier=decision.policy.error_multiplier,
            supported_horizons=tuple(sorted(decision.policy.supported_horizons))),
        provenance=DecisionProvenance(model_name=f.model_name, model_version=f.model_version,
            methodology_supported=evidence.provenance.methodology_supported,
            generated_at=f.generated_at, evaluated_at=decision.evaluated_at,
            engine_version=decision.engine_version, assessment_version=evidence.assessment_version),
    )


class DecisionAPIService:
    def __init__(self, session):
        self.session = session

    async def latest(self, source, trade_lane, container_type):
        series = SeriesIdentity(source=source, trade_lane=trade_lane, container_type=container_type)
        rows = await ForecastPersistenceService(self.session).get_latest_forecasts(
            source=source, trade_lane=trade_lane, container_type=container_type)
        if not rows:
            return None
        if len(rows) != 1:
            raise EvidenceInputError('Exact-series selection returned multiple winners')
        snapshot = snapshot_forecast(rows[0])
        if snapshot.series != series:
            raise EvidenceInputError('Selected forecast does not match requested series')
        if snapshot.generated_at.tzinfo is None or snapshot.generated_at.utcoffset() is None:
            raise EvidenceInputError('Forecast generation timestamp must be timezone-aware')
        evaluated_at = utc_now()
        if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
            raise EvidenceInputError('Evaluation timestamp must be timezone-aware')
        evaluated_at = evaluated_at.astimezone(timezone.utc)
        state = await ForecastStateCollector(self.session).collect(snapshot, evaluated_at,
                                                                     expected_series=series)
        # Isolate pure calculation and public Decimal|string validation flags.
        # Use the established Decimal precision; do not alter T08/T09 rules.
        with localcontext(Context(prec=28, rounding=ROUND_HALF_EVEN)):
            decision = evaluate_decision(DecisionInput(forecast=snapshot, current_state=state),
                                         DecisionPolicy(), evaluated_at)
            if decision.decision == Decision.UNAVAILABLE:
                raise EvidenceInputError('Persisted forecast unexpectedly produced UNAVAILABLE')
            evidence = assess_evidence(decision)
            return to_public_response(decision, evidence)
