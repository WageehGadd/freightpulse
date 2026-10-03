"""Pure gate-first evaluation of copied evidence. No I/O or narration inputs."""
from datetime import timedelta, timezone
from decimal import Decimal
import math
from app.schemas.decision import (Decision, Movement, Reason, Limitation, DecisionPolicy,
    DecisionInput, DecisionResult, Signals, REASON_ORDER)


def evaluate_decision(input_snapshot: DecisionInput | None, policy: DecisionPolicy, evaluated_at):
    policy = DecisionPolicy(**policy.model_dump())
    if evaluated_at.tzinfo is None:
        raise ValueError("evaluated_at must be timezone-aware")
    now = evaluated_at.astimezone(timezone.utc)
    reasons = []
    movement = Movement.UNDEFINED
    signals = Signals()
    decision = Decision.UNAVAILABLE
    forecast = input_snapshot.forecast if input_snapshot else None
    if forecast is None:
        reasons.append(Reason.NO_FORECAST)
    else:
        f, s = forecast, input_snapshot.current_state
        if not s.series_matches or s.series != f.series:
            reasons.append(Reason.SERIES_MISMATCH)
        if s.latest_source_date is None:
            reasons.append(Reason.SOURCE_UNAVAILABLE)
        if (s.source_superseded or s.forecast_superseded or
            (s.latest_source_date is not None and s.latest_source_date > f.latest_observation_date) or
            s.latest_forecast_id != f.forecast_id or s.latest_forecast_generated_at != f.generated_at):
            reasons.append(Reason.SUPERSEDED_FORECAST)
        if s.current_input_freshness == "stale":
            reasons.append(Reason.STALE_INPUT)
        elif s.current_input_freshness not in ("fresh", "aging"):
            reasons.append(Reason.UNKNOWN_FRESHNESS)
        if not f.stored_live_decision_eligible or not s.stored_live_decision_eligible or not s.effective_live_decision_eligible:
            reasons.append(Reason.MODEL_INELIGIBLE)
        if f.data_readiness == "MINIMAL":
            reasons.append(Reason.MINIMAL_READINESS)
        elif f.data_readiness not in ("BASELINE_READY", "EXTENDED_HISTORY"):
            reasons.append(Reason.INSUFFICIENT_READINESS)
        if f.history_observations < max(0, policy.min_history_observations):
            reasons.append(Reason.INSUFFICIENT_HISTORY)
        if f.evaluation_points < max(0, policy.min_evaluation_points):
            reasons.append(Reason.INSUFFICIENT_EVALUATION)
        rates_valid = all(v is not None and v.is_finite() and v > 0 for v in (f.latest_actual_rate, f.predicted_rate))
        if not rates_valid:
            reasons.append(Reason.INVALID_RATE)
        metrics = (f.backtest_mae, f.backtest_rmse, f.backtest_smape, f.backtest_directional_accuracy)
        metrics_valid = all(v is not None and not isinstance(v, bool) and math.isfinite(v) and v >= 0 for v in metrics)
        metrics_valid = metrics_valid and f.backtest_smape <= 200 and f.backtest_directional_accuracy <= 100
        if not metrics_valid:
            reasons.append(Reason.INVALID_METRICS)
        if f.forecast_horizon not in policy.supported_horizons:
            reasons.append(Reason.UNSUPPORTED_HORIZON)
        if now.date() > f.forecast_for_date:
            reasons.append(Reason.EXPIRED_TARGET)
        if (f.forecast_horizon != 1 or f.latest_observation_date > now.date() or
            f.forecast_for_date != f.latest_observation_date + timedelta(days=1) or
            s.evaluated_at != now):
            reasons.append(Reason.INVALID_TEMPORAL_CONTEXT)
        if rates_valid:
            change = f.predicted_rate - f.latest_actual_rate
            pct = change / f.latest_actual_rate * Decimal(100)
            movement = (Movement.INCREASE if pct >= policy.movement_threshold_pct else
                Movement.DECREASE if pct <= -policy.movement_threshold_pct else Movement.NEGLIGIBLE)
            signals = Signals(absolute_change=change, percentage_change=pct,
                error_scale=Decimal(str(f.backtest_mae)) * policy.error_multiplier if metrics_valid else None)
        decision = Decision.WITHHOLD
        if not reasons:
            if movement == Movement.NEGLIGIBLE:
                decision = Decision.MONITOR
                reasons.append(Reason.MOVEMENT_BELOW_THRESHOLD)
            elif abs(signals.absolute_change) <= signals.error_scale:
                reasons.append(Reason.MOVEMENT_WITHIN_ERROR_SCALE)
            else:
                decision = (Decision.CONSIDER_EARLIER_BOOKING if movement == Movement.INCREASE
                    else Decision.CONSIDER_LATER_BOOKING)
                reasons.append(Reason.FORECAST_INCREASE if movement == Movement.INCREASE else Reason.FORECAST_DECREASE)
        if s.current_input_freshness == "aging":
            reasons.append(Reason.AGING_INPUT)
    return DecisionResult(decision=decision, actionable=decision in (
        Decision.CONSIDER_EARLIER_BOOKING, Decision.CONSIDER_LATER_BOOKING), movement=movement,
        reasons=tuple(r for r in REASON_ORDER if r in reasons), signals=signals, limitations=tuple(Limitation),
        forecast_identity=forecast, evaluated_at=now, policy=policy, input_snapshot=input_snapshot)
