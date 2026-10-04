"""Pure transitions over completed T08/T09 evidence; no acceptance or delivery."""
import hashlib
import json
import math
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ValidationError

from app.schemas.decision import Decision, HARD_BLOCKERS, Movement
from app.schemas.reliability import (
    DecisionEvidenceStatus as DES, HistoricalEvidenceStatus as H,
    SampleSufficiencyStatus as S,
)
from app.schemas.predictive_alert import (
    POLICY_VERSION, DIRECTIONS, AlertCheckpoint, AlertReason, AlertStatus,
    CheckpointState, ForecastGeneration, PredictiveAlertInput,
    PredictiveAlertResult, SignalCategory, Transition,
    expected_evidence_status,
)


def _canonical(value, *, omit_evaluation_times=True):
    """Typed numeric/non-finite encodings preserve deficient evidence identity.

    All evaluated_at fields are incidental observation instants. Generation and
    target/source dates remain identity-bearing. Preserve ordered evidence tuples.
    """
    if isinstance(value, BaseModel):
        return _canonical(value.model_dump(mode="python"), omit_evaluation_times=omit_evaluation_times)
    if isinstance(value, dict):
        # Validate even incidental datetimes before excluding them from identity.
        canonical = {key: _canonical(item, omit_evaluation_times=omit_evaluation_times)
                     for key, item in value.items()}
        return {key: item for key, item in canonical.items()
                if not omit_evaluation_times or key != "evaluated_at"}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Identity timestamps require an explicit timezone")
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal):
        if not value.is_finite():
            # Raw deficient T08 snapshots remain evidence, never live eligibility.
            return {"decimal_nonfinite": str(value)}
        sign, digits, exponent = value.as_tuple()
        digits = list(digits)
        if not any(digits):
            sign, digits, exponent = 0, [0], 0
        else:
            while digits[-1] == 0:
                digits.pop()
                exponent += 1
        # Context-free coefficient/exponent: 1 == 1.0 == 1.00, even huge exponents.
        return {"decimal": [sign, "".join(map(str, digits)), exponent]}
    if isinstance(value, float):
        return {"float": (0.0 if value == 0 else value).hex()
                if math.isfinite(value) else str(value)}
    if isinstance(value, (set, frozenset)):
        return sorted((_canonical(item, omit_evaluation_times=omit_evaluation_times)
                       for item in value), key=_serialize)
    if isinstance(value, (list, tuple)):
        return [_canonical(item, omit_evaluation_times=omit_evaluation_times) for item in value]
    return value


def _serialize(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True,
                      separators=(",", ":"), allow_nan=False)


def _digest(value):
    return hashlib.sha256(_serialize(_canonical(value)).encode("utf-8")).hexdigest()


def _same(first, second):
    # Python equality can equate distinct DST-fold instants in the same timezone.
    # Pair consistency retains evaluation times; identity alone omits them.
    return (_canonical(first, omit_evaluation_times=False)
            == _canonical(second, omit_evaluation_times=False))


def _token(series, state_fingerprint, previous_token, policy=POLICY_VERSION):
    return _digest({"kind": "checkpoint", "policy": policy, "series": series,
                    "parent": {"accepted_token": previous_token} if previous_token
                    else {"genesis": True}, "state": state_fingerprint})


def _invalid(reason):
    return PredictiveAlertResult(status=AlertStatus.INVALID_INPUT, reasons=(reason,))


def _valid_series(series):
    return all(isinstance(v, str) and any(c.isprintable() and not c.isspace() for c in v) for v in (
        series.source, series.trade_lane, series.container_type))


def _check_pair(data):
    r, a = data.decision, data.evidence
    f = r.forecast_identity
    state = r.input_snapshot.current_state if r.input_snapshot else None
    if not _same(a.decision_result, r) or not _same(a.evaluated_at, r.evaluated_at) or not _same(a.current_state, state):
        return AlertReason.PAIR_MISMATCH
    # T09's descriptive numeric outputs are sanitized, unlike raw T08 snapshots.
    numbers = (*a.historical_error.model_dump(mode="python").values(),
               a.directional_evidence.directional_accuracy,
               *a.decision_margin.signals.model_dump(mode="python").values(),
               *(factor.observed for factor in a.factors))
    if any((isinstance(v, float) and not math.isfinite(v))
           or (isinstance(v, Decimal) and not v.is_finite()) for v in numbers):
        return AlertReason.PAIR_MISMATCH
    if not _same(f, r.input_snapshot.forecast if r.input_snapshot else None):
        return AlertReason.GENERATION_MISMATCH
    if (r.decision == Decision.UNAVAILABLE) != (f is None):
        return AlertReason.SAFETY_CONTRADICTION
    if f and (f.series != data.series or state.series != data.series):
        return AlertReason.SERIES_MISMATCH
    expected_status = expected_evidence_status(r.decision)
    if (a.decision_evidence_status != expected_status
            or a.sample_sufficiency_status != a.sample_evidence.sample_sufficiency_status
            or a.decision_margin.signals != r.signals
            or a.decision_margin.movement_threshold_pct != r.policy.movement_threshold_pct
            or a.decision_margin.error_multiplier != r.policy.error_multiplier):
        return AlertReason.PAIR_MISMATCH
    if f:
        if a.provenance is None or any(not _same(getattr(a.provenance, key), getattr(f, key))
            for key in ("forecast_id", "generated_at", "model_name", "model_version",
                        "latest_observation_date", "forecast_for_date", "forecast_horizon")):
            return AlertReason.GENERATION_MISMATCH
        if (a.historical_evidence_status == H.AVAILABLE
                and (not a.provenance.methodology_supported
                     or any(v is None for v in (a.historical_error.mae,
                         a.historical_error.rmse, a.historical_error.smape,
                         a.directional_evidence.directional_accuracy,
                         a.sample_evidence.history_observations,
                         a.sample_evidence.evaluation_points)))):
            return AlertReason.PAIR_MISMATCH
        if (a.historical_evidence_status == H.UNSUPPORTED
                and a.provenance.methodology_supported):
            return AlertReason.PAIR_MISMATCH
        # Compare supplied copies only; T09 owns sanitization and assessment.
        for copied, original in (
            (a.sample_evidence.history_observations, f.history_observations),
            (a.sample_evidence.evaluation_points, f.evaluation_points),
            (a.sample_evidence.data_readiness, f.data_readiness),
            (a.historical_error.mae, f.backtest_mae),
            (a.historical_error.rmse, f.backtest_rmse),
            (a.historical_error.smape, f.backtest_smape),
            (a.directional_evidence.directional_accuracy, f.backtest_directional_accuracy),
        ):
            if copied is not None and copied != original:
                return AlertReason.PAIR_MISMATCH
    elif a.provenance is not None:
        return AlertReason.GENERATION_MISMATCH
    elif (a.historical_evidence_status != H.UNAVAILABLE
          or a.sample_sufficiency_status != S.NOT_ASSESSABLE):
        return AlertReason.PAIR_MISMATCH
    elif (any(v is not None for v in (
            a.sample_evidence.history_observations, a.sample_evidence.evaluation_points,
            a.sample_evidence.data_readiness, a.directional_evidence.directional_accuracy,
            *a.historical_error.model_dump(mode="python").values(),
            a.decision_margin.movement_within_error_scale))
          or a.factors or a.assessment_limitations):
        return AlertReason.PAIR_MISMATCH
    # Consume safety flags and T08 blockers; never recompute thresholds or ages.
    if r.decision in DIRECTIONS or r.decision == Decision.MONITOR:
        if (any(reason in HARD_BLOCKERS for reason in r.reasons)
                or not f.stored_live_decision_eligible
                or not state.stored_live_decision_eligible
                or not state.effective_live_decision_eligible
                or not state.series_matches or state.source_superseded
                or state.forecast_superseded or state.latest_source_date is None
                or state.context_state != "current"
                or state.latest_forecast_id != f.forecast_id
                or not _same(state.latest_forecast_generated_at, f.generated_at)
                or not _same(state.evaluated_at, r.evaluated_at)
                or state.current_input_freshness not in ("fresh", "aging")):
            return AlertReason.SAFETY_CONTRADICTION
    expected_movement = {
        Decision.CONSIDER_EARLIER_BOOKING: Movement.INCREASE,
        Decision.CONSIDER_LATER_BOOKING: Movement.DECREASE,
        Decision.MONITOR: Movement.NEGLIGIBLE,
        Decision.UNAVAILABLE: Movement.UNDEFINED,
    }.get(r.decision)
    if expected_movement is not None and r.movement != expected_movement:
        return AlertReason.SAFETY_CONTRADICTION
    return None


def evaluate_predictive_alert(data: PredictiveAlertInput) -> PredictiveAlertResult:
    """Return a reproducible proposal; caller must revalidate and atomically CAS.

    Malformed/bypassed model instances fail closed. A digest is an integrity and
    deduplication key, not proof that an untrusted caller supplied genuine evidence.
    """
    if not isinstance(data, PredictiveAlertInput):
        return _invalid(AlertReason.INVALID_STRUCTURE)
    try:
        if type(getattr(data.decision, "actionable", None)) is not bool:
            return _invalid(AlertReason.INVALID_STRUCTURE)
        # model_copy/model_construct bypass Pydantic validators: validate afresh.
        data = PredictiveAlertInput.model_validate(data.model_dump(mode="python"), strict=True)
        if not _valid_series(data.series):
            return _invalid(AlertReason.SERIES_MISMATCH)
        error = _check_pair(data)
        if error:
            return _invalid(error)
        previous = data.previous_checkpoint
        if previous:
            if previous.series != data.series:
                return _invalid(AlertReason.SERIES_MISMATCH)
            if (previous.state_fingerprint != _digest(previous.state)
                    or previous.accepted_checkpoint_token != _token(
                        previous.series, previous.state_fingerprint,
                        previous.previous_token, previous.policy_version)):
                return _invalid(AlertReason.INVALID_CHECKPOINT)
        r, a = data.decision, data.evidence
        generation = (ForecastGeneration(forecast_id=r.forecast_identity.forecast_id,
                      generated_at=r.forecast_identity.generated_at)
                      if r.forecast_identity else None)
        # Status availability is not accuracy/confidence. Unsupported/unavailable
        # evidence cannot support a directional signal; T08 itself is unchanged.
        direction = r.decision if (r.actionable
            and a.historical_evidence_status == H.AVAILABLE
            and a.sample_sufficiency_status == S.POLICY_MINIMUMS_MET
            and a.decision_evidence_status == DES.DIRECTIONAL_RULES_PASSED) else None
        state = CheckpointState(decision=r.decision, actionable=r.actionable,
            eligible_direction=direction, generation=generation,
            historical_evidence_status=a.historical_evidence_status,
            sample_sufficiency_status=a.sample_sufficiency_status,
            decision_evidence_status=a.decision_evidence_status,
            evidence_fingerprint=_digest(a))
        state_hash = _digest(state)
        parent = previous.accepted_checkpoint_token if previous else None
        checkpoint = (previous if previous and previous.state_fingerprint == state_hash
            else AlertCheckpoint(series=data.series, state=state, previous_token=parent,
                state_fingerprint=state_hash,
                accepted_checkpoint_token=_token(data.series, state_hash, parent)))
        transition = None
        if previous is None:
            status, reason = AlertStatus.BASELINE_ONLY, AlertReason.PREVIOUS_CHECKPOINT_ABSENT
        else:
            old = previous.state.eligible_direction
            if old is None and direction is not None:
                transition = Transition.DIRECTIONAL_ENTERED
            elif old is not None and direction is None:
                transition = Transition.ACTIONABILITY_WITHDRAWN
            elif old is not None and old != direction:
                transition = Transition.DIRECTION_REVERSED
            if transition:
                status, reason = AlertStatus.EMIT, AlertReason.STATE_TRANSITION
            else:
                status = AlertStatus.SUPPRESS
                reason = AlertReason.UNCHANGED_DIRECTION if direction else AlertReason.NO_DIRECTIONAL_TRANSITION
        reasons = (reason,)
        if r.actionable and direction is None:
            reasons += (AlertReason.EVIDENCE_NOT_AVAILABLE,)
        reasons = tuple(code for code in AlertReason if code in reasons)
        category = (SignalCategory.OPERATIONAL if transition == Transition.ACTIONABILITY_WITHDRAWN
                    else SignalCategory.DIRECTIONAL) if transition else None
        signal = _digest({"kind": "signal", "policy": POLICY_VERSION,
            "series": data.series, "previous_accepted_token": parent,
            "transition": transition, "state": state_hash}) if transition else None
        return PredictiveAlertResult(status=status, transition=transition, category=category,
            signal_identity=signal, reasons=reasons, evidence=a, next_checkpoint=checkpoint)
    except (ValidationError, ValueError, TypeError, AttributeError, KeyError, OverflowError):
        return _invalid(AlertReason.INVALID_STRUCTURE)
