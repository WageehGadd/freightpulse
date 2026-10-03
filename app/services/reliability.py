"""Pure evidence-v1 assessment. No new decision rules, state reads or scoring."""
import math
from decimal import Decimal, Context, localcontext, ROUND_HALF_EVEN

from app.schemas.decision import Decision, DecisionResult, HARD_BLOCKERS
from app.schemas.reliability import (
    EvidenceAssessment, HistoricalEvidenceStatus, SampleSufficiencyStatus,
    DecisionEvidenceStatus, EvidenceDimension, FactorKind, EvidenceFactorCode,
    EvidenceFactor, SampleEvidence, HistoricalErrorEvidence, DirectionalEvidence,
    DecisionMarginEvidence, ModelProvenance,
)

# Versioned with evidence-v1; identifiers match T04/T06, without importing their I/O graph.
SUPPORTED_METHODOLOGIES = (
    ("baseline-v1-decimal", frozenset({"Naive", "MA(2)", "MA(3)", "MA(4)", "Drift"})),
)


class EvidenceInputError(ValueError):
    """A completed T08 DecisionResult is required."""


def _metric(value, maximum=None):
    if (not isinstance(value, (int, float)) or isinstance(value, bool)
            or not math.isfinite(value) or value < 0
            or (maximum is not None and value > maximum)):
        return None
    return float(value)


def _count(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _finite_decimal(value):
    return value if isinstance(value, Decimal) and value.is_finite() else None


def _ratio(numerator, denominator, multiplier=Decimal(1)):
    # Fixed Decimal precision/rounding makes ratios independent of caller context.
    with localcontext(Context(prec=28, rounding=ROUND_HALF_EVEN)):
        return numerator / denominator * multiplier


def assess_evidence(decision_result: DecisionResult) -> EvidenceAssessment:
    # Pydantic's Decimal|string union probing can also set Decimal flags.
    # Isolate validation as well as arithmetic from the caller's entire context.
    with localcontext(Context(prec=28, rounding=ROUND_HALF_EVEN)):
        return _assess_evidence(decision_result)


def _assess_evidence(decision_result: DecisionResult) -> EvidenceAssessment:
    """Describe copied evidence, preserving T08 outcome and evaluation instant.

    Status precedence: no artifact; unsupported methodology; incomplete required
    historical evidence; available. Performance magnitude never selects a status.
    Factors have explicit construction order: method, validity, samples, normalized
    signals (MAE, RMSE, movement/MAE), selection limitation, directional limitation.
    """
    if not isinstance(decision_result, DecisionResult):
        raise EvidenceInputError("A completed DecisionResult is required")
    result = decision_result
    f = result.input_snapshot.forecast if result.input_snapshot else None
    if result.forecast_identity != f:
        raise EvidenceInputError("DecisionResult forecast identity and input snapshot disagree")
    current = result.input_snapshot.current_state if result.input_snapshot else None
    # Check the completed-result boundary, never rerun or repair T08 decisions.
    directional = result.decision in (
        Decision.CONSIDER_EARLIER_BOOKING, Decision.CONSIDER_LATER_BOOKING)
    if (not isinstance(result.decision, Decision) or type(result.actionable) is not bool
            or result.actionable != directional
            or (result.decision == Decision.UNAVAILABLE) != (f is None)):
        raise EvidenceInputError("DecisionResult outcome and artifact structure disagree")
    if f and (not isinstance(f.model_name, str) or not isinstance(f.model_version, str)):
        raise EvidenceInputError("Forecast methodology identifiers must be strings")
    if result.decision in (Decision.MONITOR, Decision.CONSIDER_EARLIER_BOOKING,
                          Decision.CONSIDER_LATER_BOOKING):
        if (any(reason in HARD_BLOCKERS for reason in result.reasons)
                or not f.stored_live_decision_eligible
                or not current.stored_live_decision_eligible
                or not current.effective_live_decision_eligible
                or not current.series_matches or current.series != f.series
                or current.latest_source_date is None or current.source_superseded
                or current.latest_forecast_id != f.forecast_id
                or current.latest_forecast_generated_at != f.generated_at
                or current.evaluated_at != result.evaluated_at
                or current.forecast_superseded
                or current.current_input_freshness not in ("fresh", "aging")):
            raise EvidenceInputError("Unblocked decision contradicts copied safety state")
    history = _count(f.history_observations) if f else None
    points = _count(f.evaluation_points) if f else None
    mae = _metric(f.backtest_mae) if f else None
    rmse = _metric(f.backtest_rmse) if f else None
    smape = _metric(f.backtest_smape, 200) if f else None
    direction = _metric(f.backtest_directional_accuracy, 100) if f else None
    supported = bool(f and any(f.model_version == version and f.model_name in models
        for version, models in SUPPORTED_METHODOLOGIES))
    samples = SampleSufficiencyStatus.NOT_ASSESSABLE
    if history is not None and points is not None:
        samples = (SampleSufficiencyStatus.POLICY_MINIMUMS_MET
            if history >= result.policy.min_history_observations and points >= result.policy.min_evaluation_points
            else SampleSufficiencyStatus.LIMITED)
    if result.decision in (Decision.MONITOR, Decision.CONSIDER_EARLIER_BOOKING,
                          Decision.CONSIDER_LATER_BOOKING):
        if (any(v is None for v in (mae, rmse, smape, direction, history, points))
                or samples != SampleSufficiencyStatus.POLICY_MINIMUMS_MET):
            raise EvidenceInputError("Unblocked decision contradicts required copied evidence")
    historical = HistoricalEvidenceStatus.UNAVAILABLE
    if f:
        if not supported:
            historical = HistoricalEvidenceStatus.UNSUPPORTED
        elif (any(v is None for v in (mae, rmse, smape, direction, history, points))
              or history == 0 or points == 0):
            historical = HistoricalEvidenceStatus.INVALID_OR_INCOMPLETE
        else:
            historical = HistoricalEvidenceStatus.AVAILABLE
    decision_status = {
        Decision.UNAVAILABLE: DecisionEvidenceStatus.UNAVAILABLE,
        Decision.WITHHOLD: DecisionEvidenceStatus.BLOCKED,
        Decision.MONITOR: DecisionEvidenceStatus.MONITOR_ONLY,
        Decision.CONSIDER_EARLIER_BOOKING: DecisionEvidenceStatus.DIRECTIONAL_RULES_PASSED,
        Decision.CONSIDER_LATER_BOOKING: DecisionEvidenceStatus.DIRECTIONAL_RULES_PASSED,
    }[result.decision]
    actual = _finite_decimal(f.latest_actual_rate) if f else None
    change = _finite_decimal(result.signals.absolute_change)
    scale = _finite_decimal(result.signals.error_scale)
    mae_pct = (_ratio(Decimal(str(mae)), actual, Decimal(100))
        if mae is not None and actual is not None and actual > 0 else None)
    rmse_pct = (_ratio(Decimal(str(rmse)), actual, Decimal(100))
        if rmse is not None and actual is not None and actual > 0 else None)
    movement_ratio = (_ratio(change.copy_abs(), Decimal(str(mae)))
        if change is not None and mae is not None and mae > 0 else None)
    within_scale = (change.copy_abs() <= scale
        if change is not None and scale is not None and scale >= 0 else None)
    factors = []
    limitations = []

    def factor(dimension, code, kind, reference, explanation, observed=None, requirement=None):
        factors.append(EvidenceFactor(dimension=dimension, code=code, kind=kind,
            reference=reference, observed=observed, requirement=requirement, explanation=explanation))

    if f:
        if not supported:
            factor(EvidenceDimension.METHODOLOGY, EvidenceFactorCode.METHODOLOGY_UNSUPPORTED,
                FactorKind.LIMITING, "model_methodology", "This model/version is not characterized by evidence-v1.",
                observed=f"{f.model_name}/{f.model_version}")
        if any(v is None for v in (mae, rmse, smape, direction, history, points)) or history == 0 or points == 0:
            factor(EvidenceDimension.HISTORICAL_ERROR, EvidenceFactorCode.HISTORICAL_EVIDENCE_INVALID_OR_INCOMPLETE,
                FactorKind.LIMITING, "historical_evidence", "Required historical metrics or sample counts are invalid or incomplete.")
        if samples == SampleSufficiencyStatus.NOT_ASSESSABLE:
            factor(EvidenceDimension.SAMPLE, EvidenceFactorCode.SAMPLE_COUNTS_INVALID_OR_UNAVAILABLE,
                FactorKind.LIMITING, "sample_counts", "Sample counts cannot be assessed.")
        else:
            met = samples == SampleSufficiencyStatus.POLICY_MINIMUMS_MET
            factor(EvidenceDimension.SAMPLE,
                EvidenceFactorCode.POLICY_SAMPLE_MINIMUM_MET if met else EvidenceFactorCode.POLICY_SAMPLE_MINIMUM_NOT_MET,
                FactorKind.SUPPORTING if met else FactorKind.LIMITING, "sample_counts",
                "History and evaluation counts meet the configured policy minimums; this is not statistical validation." if met else
                "One or more configured policy sample minimums are not met.",
                observed=f"history={history}; evaluation={points}",
                requirement=f"history>={result.policy.min_history_observations}; evaluation>={result.policy.min_evaluation_points}")
        for reference, value in (("mae_relative_to_latest_actual_pct", mae_pct),
                ("rmse_relative_to_latest_actual_pct", rmse_pct), ("movement_to_mae_ratio", movement_ratio)):
            factor(EvidenceDimension.HISTORICAL_ERROR,
                EvidenceFactorCode.NORMALIZED_ERROR_AVAILABLE if value is not None else EvidenceFactorCode.NORMALIZED_ERROR_UNAVAILABLE,
                FactorKind.INFORMATIONAL if value is not None else FactorKind.LIMITING, reference,
                "Descriptive ratio only; no evidence-quality threshold is applied." if value is not None else
                "Ratio unavailable because an input is invalid/missing or its denominator is not positive.", observed=value)
        if supported:
            limitations.append(EvidenceFactorCode.SELECTION_WINDOW_NOT_INDEPENDENT)
            factor(EvidenceDimension.METHODOLOGY, EvidenceFactorCode.SELECTION_WINDOW_NOT_INDEPENDENT,
                FactorKind.LIMITING, "backtest_protocol",
                "Prefix out-of-sample walk-forward metrics use the same evaluation window for champion selection and reporting; no independent post-selection holdout is recorded.")
        limitations.append(EvidenceFactorCode.DIRECTIONAL_DENOMINATOR_UNAVAILABLE)
        factor(EvidenceDimension.DIRECTIONAL, EvidenceFactorCode.DIRECTIONAL_DENOMINATOR_UNAVAILABLE,
            FactorKind.LIMITING, "valid_directional_sample_count",
            "Valid directional sample count is not recorded; evaluation_points is not its denominator.")
    return EvidenceAssessment(decision_result=result, evaluated_at=result.evaluated_at,
        historical_evidence_status=historical, sample_sufficiency_status=samples,
        decision_evidence_status=decision_status,
        sample_evidence=SampleEvidence(history_observations=history, evaluation_points=points,
            data_readiness=f.data_readiness if f else None, sample_sufficiency_status=samples),
        historical_error=HistoricalErrorEvidence(mae=mae, rmse=rmse, smape=smape,
            mae_relative_to_latest_actual_pct=mae_pct, rmse_relative_to_latest_actual_pct=rmse_pct,
            movement_to_mae_ratio=movement_ratio),
        directional_evidence=DirectionalEvidence(directional_accuracy=direction), current_state=current,
        decision_margin=DecisionMarginEvidence(signals=result.signals,
            movement_threshold_pct=result.policy.movement_threshold_pct, error_multiplier=result.policy.error_multiplier,
            movement_within_error_scale=within_scale),
        provenance=ModelProvenance(forecast_id=f.forecast_id, model_name=f.model_name,
            model_version=f.model_version, generated_at=f.generated_at,
            latest_observation_date=f.latest_observation_date, forecast_for_date=f.forecast_for_date,
            forecast_horizon=f.forecast_horizon, methodology_supported=supported) if f else None,
        factors=tuple(factors), assessment_limitations=tuple(limitations))
