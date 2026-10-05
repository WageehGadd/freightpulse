"""Pure rate substitution and comparison; T08 owns every decision rule."""
import hashlib
import json
import math
from datetime import date, datetime, timezone
from decimal import Context, Decimal, ROUND_HALF_EVEN, localcontext
from enum import Enum
from uuid import UUID

from pydantic import BaseModel

from app.schemas.decision import (
    DecisionInput, DecisionPolicy, ForecastSnapshot, ForecastState, SeriesIdentity,
    HARD_BLOCKERS, REASON_ORDER,
)
from app.schemas.scenario import (
    AbsoluteRate, PercentageAdjustment, AppliedAssumption, CENT, METHODOLOGY_VERSION, ScenarioComparison, ScenarioRequest,
    ScenarioResult, money,
)
from app.services.decision_engine import evaluate_decision
from app.services.reliability import assess_evidence


class ScenarioInputError(ValueError):
    """Malformed factual composition or unsupported hypothetical representation."""


def _utc(value):
    try:
        if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
            raise ScenarioInputError("Authoritative timestamps must be timezone-aware")
        return value.astimezone(timezone.utc)
    except (OverflowError, ValueError) as exc:
        raise ScenarioInputError("Timestamp must represent a valid timezone-aware UTC instant") from exc


def _same_types(before, after):
    """Detect nested coercion (including IntEnum -> int inside a policy set)."""
    if type(before) is not type(after):
        return False
    if isinstance(before, dict):
        return before.keys() == after.keys() and all(_same_types(before[k], after[k]) for k in before)
    if isinstance(before, (tuple, list)):
        return len(before) == len(after) and all(_same_types(a, b) for a, b in zip(before, after))
    if isinstance(before, (set, frozenset)):
        return len(before) == len(after) and all(any(
            type(a) is type(b) and _canonical(a) == _canonical(b) for b in after) for a in before)
    return True


def _declared_fields(model):
    # model_copy can retain extras that model_dump silently omits; do not erase attacks.
    if set(model.__dict__) != set(type(model).model_fields) or model.model_extra:
        raise ScenarioInputError("Domain model has missing or undeclared fields")


def _canonical(value):
    if isinstance(value, BaseModel):
        return _canonical(value.model_dump(mode="python"))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return _utc(value).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ScenarioInputError("Nonfinite Decimal cannot identify a scenario")
        sign, digits, exponent = value.as_tuple()
        digits = list(digits)
        if not any(digits):
            sign, digits, exponent = 0, [0], 0
        else:
            while digits[-1] == 0:
                digits.pop()
                exponent += 1
        return {"decimal": [sign, "".join(map(str, digits)), exponent]}
    if isinstance(value, float):
        # Deficient historical float metrics remain factual, and blocked by T08.
        return {"float": (0.0 if value == 0 else value).hex() if math.isfinite(value) else str(value)}
    if isinstance(value, dict):
        return {key: _canonical(item) for key, item in value.items()}
    if isinstance(value, (set, frozenset)):
        return sorted((_canonical(item) for item in value), key=_serialize)
    if isinstance(value, (tuple, list)):
        return [_canonical(item) for item in value]
    return value


def _serialize(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def _fingerprint(value):
    return hashlib.sha256(_serialize(_canonical(value)).encode("utf-8")).hexdigest()


def _validate_baseline(baseline, policy, evaluated_at):
    if type(baseline) is not DecisionInput or type(policy) is not DecisionPolicy:
        raise ScenarioInputError("Authoritative DecisionInput and application policy are required")
    _declared_fields(baseline)
    _declared_fields(policy)
    if type(baseline.forecast) is not ForecastSnapshot or type(baseline.current_state) is not ForecastState:
        raise ScenarioInputError("Factual input requires authoritative nested domain models")
    _declared_fields(baseline.forecast)
    _declared_fields(baseline.current_state)
    if type(baseline.forecast.series) is not SeriesIdentity or type(baseline.current_state.series) is not SeriesIdentity:
        raise ScenarioInputError("Factual input requires authoritative series models")
    for model in (baseline, baseline.forecast, baseline.current_state,
                  baseline.forecast.series, baseline.current_state.series, policy):
        _declared_fields(model)
    if (type(policy.movement_threshold_pct) is not Decimal or type(policy.error_multiplier) is not Decimal or
            type(policy.min_history_observations) is not int or type(policy.min_evaluation_points) is not int or
            type(policy.supported_horizons) is not frozenset or
            any(type(h) is not int for h in policy.supported_horizons)):
        raise ScenarioInputError("Application policy requires exact validated primitive types")
    # Reject numeric subclasses before serialization/canonical methods can run.
    money(baseline.forecast.predicted_rate)
    money(baseline.forecast.latest_actual_rate)
    # Reconstruct even model_construct/model_copy objects; no instance-validation shortcut.
    supplied_baseline = baseline.model_dump(mode="python")
    baseline = DecisionInput.model_validate(supplied_baseline, strict=True)
    if (not _same_types(supplied_baseline, baseline.model_dump(mode="python")) or
            _canonical(supplied_baseline) != _canonical(baseline)):
        raise ScenarioInputError("Factual domain input must not require coercion or evidence repair")
    supplied_policy = policy.model_dump(mode="python")
    policy = DecisionPolicy.model_validate(supplied_policy, strict=True)
    # T08's custom policy __init__ can coerce even model_validate(strict=True).
    # Check representation types without duplicating its policy validity rules.
    if not _same_types(supplied_policy, policy.model_dump(mode="python")):
        raise ScenarioInputError("Application policy must already contain validated domain types")
    f, s = baseline.forecast, baseline.current_state
    for identity in (f.series, s.series):
        for value in identity.model_dump().values():
            if not value.strip() or not all(char.isprintable() for char in value):
                raise ScenarioInputError("Exact series must be nonblank and contain no control characters")
    money(f.predicted_rate)
    money(f.latest_actual_rate)
    now = _utc(evaluated_at)
    generation = _utc(f.generated_at)
    latest_generation = (_utc(s.latest_forecast_generated_at)
                         if s.latest_forecast_generated_at is not None else None)
    if _utc(s.evaluated_at) != now:
        raise ScenarioInputError("State and evaluation instants disagree")
    if not s.series_matches or s.series != f.series:
        raise ScenarioInputError("Exact baseline/state series mismatch")
    if s.stored_live_decision_eligible != f.stored_live_decision_eligible:
        raise ScenarioInputError("Stored eligibility snapshots disagree")
    if s.effective_live_decision_eligible and not s.stored_live_decision_eligible:
        raise ScenarioInputError("Effective eligibility contradicts stored eligibility")
    source_newer = s.latest_source_date is not None and s.latest_source_date > f.latest_observation_date
    if s.source_superseded != source_newer:
        raise ScenarioInputError("Source supersession contradicts observed cutoff")
    generation_differs = (s.latest_forecast_id != f.forecast_id or
                          latest_generation != generation)
    if s.forecast_superseded != generation_differs:
        raise ScenarioInputError("Forecast supersession contradicts generation identity")
    expected_context = ("source_unavailable" if s.latest_source_date is None else
                        "superseded" if s.source_superseded or s.forecast_superseded else "current")
    if s.context_state != expected_context:
        raise ScenarioInputError("Context state contradicts factual identity/availability")
    if s.effective_live_decision_eligible and expected_context != "current":
        raise ScenarioInputError("Superseded/unavailable context cannot be effectively eligible")
    # Python equality for ambiguous local times can ignore fold or disagree with
    # equivalent UTC instants. T08 must receive canonical instants too, not just hashing.
    document = baseline.model_dump(mode="python")
    document["forecast"]["generated_at"] = generation
    document["current_state"]["latest_forecast_generated_at"] = latest_generation
    document["current_state"]["evaluated_at"] = now
    baseline = DecisionInput.model_validate(document, strict=True)
    return baseline, policy, now


def _decision(input_snapshot, policy, evaluated_at):
    """Translate representational overflow, never repair or replace a T08 outcome."""
    try:
        return evaluate_decision(input_snapshot, policy, evaluated_at)
    except ArithmeticError as exc:
        raise ScenarioInputError("Factual context exceeds supported decision arithmetic/date representation") from exc


def evaluate_scenario(baseline: DecisionInput, request: ScenarioRequest,
                      policy: DecisionPolicy, evaluated_at: datetime) -> ScenarioResult:
    """Application supplies facts/policy/time; caller supplies only the assumption."""
    with localcontext(Context(prec=28, rounding=ROUND_HALF_EVEN)):
        baseline, policy, now = _validate_baseline(baseline, policy, evaluated_at)
        if type(request) is not ScenarioRequest:
            raise ScenarioInputError("A typed ScenarioRequest is required")
        _declared_fields(request)
        if type(request.assumption) not in (AbsoluteRate, PercentageAdjustment):
            raise ScenarioInputError("A typed rate assumption is required")
        _declared_fields(request.assumption)
        request = ScenarioRequest.model_validate(request.model_dump(mode="python"))
        factual = _decision(baseline, policy, now)
        evidence = assess_evidence(factual)  # Exactly one assessment, factual only.
        assumption = request.assumption
        if assumption.type == "ABSOLUTE_PREDICTED_RATE":
            applied = assumption.requested_value
        else:
            try:
                raw = baseline.forecast.predicted_rate * (Decimal(1) + assumption.requested_value / Decimal(100))
                applied = raw.quantize(CENT)
            except ArithmeticError as exc:
                raise ScenarioInputError("Percentage transformation exceeds monetary representation") from exc
        applied = money(applied)
        document = baseline.model_dump(mode="python")
        document["forecast"]["predicted_rate"] = applied
        hypothetical = DecisionInput.model_validate(document, strict=True)
        scenario = _decision(hypothetical, policy, now)
        delta = applied - baseline.forecast.predicted_rate
        added = tuple(r for r in REASON_ORDER if r in HARD_BLOCKERS and
                      r in scenario.reasons and r not in factual.reasons)
        removed = tuple(r for r in REASON_ORDER if r in HARD_BLOCKERS and
                        r in factual.reasons and r not in scenario.reasons)
        comparison = ScenarioComparison(predicted_rate_delta=delta,
            predicted_rate_delta_pct=delta / baseline.forecast.predicted_rate * Decimal(100),
            baseline_movement=factual.movement, hypothetical_movement=scenario.movement,
            baseline_decision=factual.decision, hypothetical_decision=scenario.decision,
            decision_changed=factual.decision != scenario.decision,
            baseline_rule_actionable=factual.actionable, hypothetical_rule_actionable=scenario.actionable,
            rule_actionability_changed=factual.actionable != scenario.actionable,
            added_hard_blockers=added, removed_hard_blockers=removed)
        applied_assumption = AppliedAssumption(requested=assumption, applied_predicted_rate=applied)
        baseline_hash = _fingerprint(baseline)
        identity = _fingerprint({"methodology": METHODOLOGY_VERSION, "series": baseline.forecast.series,
            "baseline": baseline_hash, "forecast_id": baseline.forecast.forecast_id,
            "generation": baseline.forecast.generated_at, "policy": policy, "evaluated_at": now,
            "category": request.category, "assumption": applied_assumption})
        return ScenarioResult(series=baseline.forecast.series, evaluated_at=now,
            baseline_predicted_rate=baseline.forecast.predicted_rate,
            baseline_evidence=evidence, assumption=applied_assumption, hypothetical_t08_result=scenario,
            comparison=comparison, analytical_only=not factual.actionable,
            limitations=("HYPOTHETICAL_INPUT_NOT_MODEL_GENERATED", "NOT_A_PREDICTION_OR_PROBABILITY",
                         "NON_OPERATIONAL_NO_ALERTS_OR_BOOKING_ACTION", "BASELINE_EVIDENCE_NOT_SCENARIO_VALIDATION",
                         "T08_HEURISTICS_AND_BASELINE_LIMITATIONS_RETAINED"),
            baseline_fingerprint=baseline_hash, scenario_identity=identity)
