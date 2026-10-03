"""Observable evidence semantics, safety separation and offline computation."""
from datetime import datetime, timezone
from decimal import Decimal
import json
import subprocess
import sys

import pytest
from app.schemas.decision import Decision, DecisionPolicy, Reason
from app.schemas.reliability import (
    HistoricalEvidenceStatus as H, SampleSufficiencyStatus as S,
    DecisionEvidenceStatus as D, EvidenceFactorCode as C, FactorKind,
    EvidenceAssessment,
)
from app.services.decision_engine import evaluate_decision
from app.services.reliability import assess_evidence, EvidenceInputError
from tests.test_decision_engine import evidence, NOW


def result(state=None, policy=None, **fields):
    i = evidence(**{"model_version": "baseline-v1-decimal", **fields})
    if state:
        i = i.model_copy(update={"current_state": i.current_state.model_copy(update=state)})
    return evaluate_decision(i, policy or DecisionPolicy(), NOW)


def deficient_result(**fields):
    # Missing counts cannot be evaluated by T08's integer-only ORM contract.
    # Exercise T09 defensive evidence handling with a copied, blocked result.
    r = result(stored_live_decision_eligible=False)
    f = r.input_snapshot.forecast.model_copy(update=fields)
    return r.model_copy(update={"forecast_identity": f, "input_snapshot": r.input_snapshot.model_copy(update={"forecast": f})})


@pytest.mark.parametrize("fields,expected", [
    ({"predicted_rate": Decimal("103")}, D.DIRECTIONAL_RULES_PASSED),
    ({"predicted_rate": Decimal("97")}, D.DIRECTIONAL_RULES_PASSED),
    ({"predicted_rate": Decimal("101")}, D.MONITOR_ONLY),
    ({"stored_live_decision_eligible": False}, D.BLOCKED),
])
def test_mapping(fields, expected):
    r = result(**fields); a = assess_evidence(r)
    assert a.decision_evidence_status == expected
    assert a.decision_result == r and a.decision_result.actionable == r.actionable


def test_no_forecast_and_missing_caller():
    r = evaluate_decision(None, DecisionPolicy(), NOW)
    a = assess_evidence(r)
    assert (a.historical_evidence_status, a.sample_sufficiency_status, a.decision_evidence_status) == (H.UNAVAILABLE, S.NOT_ASSESSABLE, D.UNAVAILABLE)
    assert a.provenance is None and a.current_state is None and a.factors == ()
    for invalid in (None, {}, "decision"):
        with pytest.raises(EvidenceInputError): assess_evidence(invalid)


def test_available_does_not_grade_performance():
    for scale in (0, 1, 100000):
        a = assess_evidence(result(backtest_mae=scale, backtest_rmse=scale, backtest_smape=200, backtest_directional_accuracy=0))
        assert a.historical_evidence_status == H.AVAILABLE
        assert a.directional_evidence.directional_accuracy == 0
        assert a.directional_evidence.valid_directional_sample_count is None


@pytest.mark.parametrize("field,value", [
    (field, value) for field in ("backtest_mae", "backtest_rmse", "backtest_smape", "backtest_directional_accuracy")
    for value in (None, float("nan"), float("inf"), -1, True)
] + [("backtest_smape", 200.0001), ("backtest_directional_accuracy", 100.0001)])
def test_invalid_metrics(field, value):
    r = result(**{field: value}); a = assess_evidence(r)
    assert a.historical_evidence_status == H.INVALID_OR_INCOMPLETE
    assert a.decision_evidence_status == D.BLOCKED
    assert C.HISTORICAL_EVIDENCE_INVALID_OR_INCOMPLETE in [f.code for f in a.factors]
    assert a.decision_result == r


@pytest.mark.parametrize("fields", [{"model_name": "future-model"}, {"model_version": "future-v2"},
    {"model_name": "MA(3)", "model_version": "baseline-v1"}])
def test_unknown_method_preserves_decision(fields):
    r = result(**fields); a = assess_evidence(r)
    assert a.historical_evidence_status == H.UNSUPPORTED
    assert not a.provenance.methodology_supported
    assert a.decision_result == r and a.decision_evidence_status == D.DIRECTIONAL_RULES_PASSED
    assert C.SELECTION_WINDOW_NOT_INDEPENDENT not in a.assessment_limitations


@pytest.mark.parametrize("model", ["Naive", "MA(2)", "MA(3)", "MA(4)", "Drift"])
def test_supported_registry(model):
    assert assess_evidence(result(model_name=model)).historical_evidence_status == H.AVAILABLE


@pytest.mark.parametrize("history,points,expected", [
    (31,16,S.LIMITED), (99,30,S.LIMITED), (100,29,S.LIMITED),
    (100,30,S.POLICY_MINIMUMS_MET), (101,31,S.POLICY_MINIMUMS_MET), (0,0,S.LIMITED),
])
def test_sample_boundaries(history, points, expected):
    a = assess_evidence(result(history_observations=history,evaluation_points=points))
    assert a.sample_sufficiency_status == expected
    codes = [f.code for f in a.factors]
    assert (C.POLICY_SAMPLE_MINIMUM_MET in codes) == (expected == S.POLICY_MINIMUMS_MET)
    assert (C.POLICY_SAMPLE_MINIMUM_NOT_MET in codes) == (expected == S.LIMITED)


@pytest.mark.parametrize("field,value", [("history_observations",None), ("evaluation_points",None),
    ("history_observations",-1), ("evaluation_points",-1), ("history_observations",True), ("evaluation_points",1.5)])
def test_invalid_counts(field,value):
    a = assess_evidence(deficient_result(**{field:value}))
    assert a.sample_sufficiency_status == S.NOT_ASSESSABLE
    assert a.historical_evidence_status == H.INVALID_OR_INCOMPLETE


def test_custom_policy_is_only_sample_reference():
    r = result(history_observations=40,evaluation_points=20, policy=DecisionPolicy(min_history_observations=40,min_evaluation_points=20))
    a = assess_evidence(r)
    assert a.sample_sufficiency_status == S.POLICY_MINIMUMS_MET
    assert a.decision_result.policy == r.policy


def test_normalized_decimal_values():
    a = assess_evidence(result(latest_actual_rate=Decimal("125"),predicted_rate=Decimal("130"),backtest_mae=2.5,backtest_rmse=5))
    e = a.historical_error
    assert (e.mae_relative_to_latest_actual_pct,e.rmse_relative_to_latest_actual_pct,e.movement_to_mae_ratio) == (Decimal(2),Decimal(4),Decimal(2))
    a = assess_evidence(result(latest_actual_rate=Decimal("0.1"),predicted_rate=Decimal("0.4"),backtest_mae=0.1))
    assert a.historical_error.mae_relative_to_latest_actual_pct == Decimal(100)
    assert a.historical_error.movement_to_mae_ratio == Decimal(3)


@pytest.mark.parametrize("actual", [Decimal(0),Decimal(-1),None,Decimal("NaN"),Decimal("Infinity")])
def test_invalid_rate_denominator(actual):
    a = assess_evidence(result(latest_actual_rate=actual))
    assert a.historical_error.mae_relative_to_latest_actual_pct is None
    assert a.historical_error.rmse_relative_to_latest_actual_pct is None
    assert a.historical_evidence_status == H.AVAILABLE
    assert a.decision_evidence_status == D.BLOCKED


def test_zero_mae_and_missing_movement():
    a = assess_evidence(result(backtest_mae=0))
    assert a.historical_error.movement_to_mae_ratio is None
    assert a.historical_error.mae_relative_to_latest_actual_pct == 0
    a = assess_evidence(result(predicted_rate=Decimal(-1)))
    assert a.historical_error.movement_to_mae_ratio is None


@pytest.mark.parametrize("state", [
    {"current_input_freshness":"fresh"}, {"current_input_freshness":"aging"},
    {"current_input_freshness":"stale"}, {"current_input_freshness":"unknown"},
    {"source_superseded":True}, {"forecast_superseded":True},
    {"effective_live_decision_eligible":False},
])
def test_current_state_preserved_not_recomputed(state):
    r = result(state=state,backtest_mae=0,backtest_rmse=0,backtest_smape=0,backtest_directional_accuracy=100)
    a = assess_evidence(r)
    assert a.historical_evidence_status == H.AVAILABLE
    assert a.current_state == r.input_snapshot.current_state
    assert a.decision_result.reasons == r.reasons
    if r.decision == Decision.WITHHOLD: assert a.decision_evidence_status == D.BLOCKED


def test_stored_false_never_promoted():
    r = result(stored_live_decision_eligible=False,history_observations=1000,evaluation_points=900,backtest_mae=0)
    a = assess_evidence(r)
    assert a.decision_evidence_status == D.BLOCKED and not a.decision_result.actionable
    assert Reason.MODEL_INELIGIBLE in a.decision_result.reasons


def test_methodology_and_order():
    a = assess_evidence(result())
    assert [f.code for f in a.factors] == [C.POLICY_SAMPLE_MINIMUM_MET,
        C.NORMALIZED_ERROR_AVAILABLE,C.NORMALIZED_ERROR_AVAILABLE,C.NORMALIZED_ERROR_AVAILABLE,
        C.SELECTION_WINDOW_NOT_INDEPENDENT,C.DIRECTIONAL_DENOMINATOR_UNAVAILABLE]
    assert a.factors[0].kind == FactorKind.SUPPORTING
    assert "not statistical validation" in a.factors[0].explanation
    assert "no independent post-selection holdout" in a.factors[-2].explanation
    assert a.assessment_limitations == (C.SELECTION_WINDOW_NOT_INDEPENDENT,C.DIRECTIONAL_DENOMINATOR_UNAVAILABLE)
    assert a.directional_evidence.valid_directional_sample_count is None


def test_no_contradictory_ratio_factors():
    a = assess_evidence(result(backtest_mae=0))
    for ref in ("mae_relative_to_latest_actual_pct","rmse_relative_to_latest_actual_pct","movement_to_mae_ratio"):
        factors = [f for f in a.factors if f.reference == ref]
        assert len(factors) == 1
    assert C.POLICY_SAMPLE_MINIMUM_NOT_MET not in [f.code for f in a.factors]


def test_repeatability_immutability_and_versions():
    r = result(); before = r.model_dump_json(); a = assess_evidence(r)
    assert a == assess_evidence(r) and r.model_dump_json() == before
    assert a.assessment_version == "evidence-v1" and a.decision_result.engine_version == "decision-rules-v1"
    assert a.evaluated_at == NOW and isinstance(a.factors,tuple)
    with pytest.raises(ValueError): a.sample_sufficiency_status = S.LIMITED
    with pytest.raises(ValueError): a.historical_error.mae = 999
    with pytest.raises(ValueError): a.factors[0].explanation = "Changed"
    with pytest.raises(ValueError): a.decision_result.policy.min_evaluation_points = 0


def test_schema_semantics():
    schema=json.dumps(EvidenceAssessment.model_json_schema()).lower()
    for forbidden in ('confidence','probability','reliability_score','decision_score','success_probability','probability_correct'):
        assert forbidden not in schema
    assert 'actionable' not in EvidenceAssessment.model_fields
    assert not {'STALE_INPUT','SUPERSEDED_FORECAST','MODEL_INELIGIBLE'} & {c.value for c in C}


def test_offline_behavior_without_infrastructure_or_clock():
    script='''
import sys, importlib.abc
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in ('openai','azure','redis','celery','fastapi','sqlalchemy','requests','httpx','aiohttp') or fullname.startswith(('app.ai','app.models','app.database','app.routers','app.tasks')):
            raise ImportError(fullname)
sys.meta_path.insert(0,Block())
from app.schemas.decision import DecisionResult
from app.services.reliability import assess_evidence
r=DecisionResult.model_validate_json(sys.stdin.read())
a=assess_evidence(r)
assert a.evaluated_at==r.evaluated_at and a.decision_result==r
print(a.historical_evidence_status.value)
'''
    completed=subprocess.run([sys.executable,'-B','-c',script],input=result().model_dump_json(),text=True,capture_output=True,check=True)
    assert completed.stdout.strip()=='AVAILABLE'
    import ast
    from pathlib import Path
    tree=ast.parse(Path('app/services/reliability.py').read_text())
    assert not any(isinstance(n,ast.Attribute) and n.attr in ('now','utcnow','today') for n in ast.walk(tree))


def test_decimal_context_independence():
    from decimal import localcontext
    r = result(latest_actual_rate=Decimal('123.45'),predicted_rate=Decimal('127.89'),backtest_mae=1.2345,backtest_rmse=2.469)
    expected = assess_evidence(r)
    with localcontext() as context:
        context.prec = 3
        assert assess_evidence(r) == expected
    assert expected.historical_error.mae_relative_to_latest_actual_pct == Decimal(1)


def test_structural_caller_error_not_limited_evidence():
    r = result()
    with pytest.raises(EvidenceInputError): assess_evidence(r.model_copy(update={'input_snapshot':None}))


def test_unsupported_precedes_invalid_but_preserves_deficiencies():
    r = result(model_version='future-v2',backtest_mae=None)
    a = assess_evidence(r)
    assert a.historical_evidence_status == H.UNSUPPORTED
    assert C.HISTORICAL_EVIDENCE_INVALID_OR_INCOMPLETE in [f.code for f in a.factors]
    assert a.historical_error.mae is None and a.decision_result == r


@pytest.mark.parametrize("decision", [Decision.CONSIDER_EARLIER_BOOKING,
    Decision.CONSIDER_LATER_BOOKING, Decision.MONITOR])
@pytest.mark.parametrize("state", [
    {"effective_live_decision_eligible": False},
    {"stored_live_decision_eligible": False}, {"series_matches": False},
    {"source_superseded": True}, {"forecast_superseded": True},
    {"current_input_freshness": "stale"}, {"current_input_freshness": "unknown"},
])
def test_impossible_unblocked_state_rejected(decision, state):
    r = result(predicted_rate=Decimal("97") if decision == Decision.CONSIDER_LATER_BOOKING
        else Decimal("101") if decision == Decision.MONITOR else Decimal("103"))
    copied = r.input_snapshot.current_state.model_copy(update=state)
    bad = r.model_copy(update={"input_snapshot": r.input_snapshot.model_copy(update={"current_state": copied})})
    with pytest.raises(EvidenceInputError):
        assess_evidence(bad)


def test_impossible_outcome_identity_and_hard_blockers():
    r = result()
    for updates in ({"actionable": False}, {"decision": Decision.UNAVAILABLE},
                    {"reasons": (Reason.STALE_INPUT,)}, {"decision": "invented"}):
        with pytest.raises(EvidenceInputError):
            assess_evidence(r.model_copy(update=updates))
    for name in (None, [], 123):
        with pytest.raises(EvidenceInputError):
            assess_evidence(deficient_result(model_name=name))


@pytest.mark.parametrize("field", ["history_observations", "evaluation_points"])
@pytest.mark.parametrize("value", [False, True, 1.0, 1.5, "100", None, -1])
def test_both_count_types_defensive(field, value):
    a = assess_evidence(deficient_result(**{field: value}))
    assert a.sample_sufficiency_status == S.NOT_ASSESSABLE
    assert a.historical_evidence_status == H.INVALID_OR_INCOMPLETE


@pytest.mark.parametrize("field", ["backtest_mae", "backtest_rmse", "backtest_smape", "backtest_directional_accuracy"])
def test_negative_infinity_metrics(field):
    a = assess_evidence(result(**{field: float("-inf")}))
    assert a.historical_evidence_status == H.INVALID_OR_INCOMPLETE
    assert a.decision_evidence_status == D.BLOCKED


@pytest.mark.parametrize("fields", [
    {"model_name": "naive"}, {"model_name": "Naive "}, {"model_name": " MA(3)"},
    {"model_name": "MA(5)"}, {"model_version": "BASELINE-V1-DECIMAL"},
    {"model_version": "baseline-v1-decimal "}, {"model_version": "baseline-v2-decimal"},
])
def test_methodology_exact_matching(fields):
    a = assess_evidence(result(**fields))
    assert a.historical_evidence_status == H.UNSUPPORTED
    assert C.SELECTION_WINDOW_NOT_INDEPENDENT not in a.assessment_limitations


@pytest.mark.parametrize("value", [Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")])
def test_json_nonfinite_is_null_without_mutating_evidence(value):
    r = result(latest_actual_rate=value)
    a = assess_evidence(r)
    raw = a.model_dump_json()
    decoded = json.loads(raw, parse_constant=lambda value: pytest.fail(value))
    assert decoded["decision_result"]["forecast_identity"]["latest_actual_rate"] is None
    assert '"NaN"' not in raw and '"Infinity"' not in raw and '"-Infinity"' not in raw
    assert a.decision_result is r
    assert a.decision_result.forecast_identity.latest_actual_rate is value
    decoded["factors"].clear()
    assert a.factors


def test_serialized_versions_provenance_and_detached_containers():
    a = assess_evidence(result())
    decoded = json.loads(a.model_dump_json())
    assert decoded["assessment_version"] == "evidence-v1"
    assert decoded["decision_result"]["engine_version"] == "decision-rules-v1"
    assert decoded["provenance"]["model_version"] == "baseline-v1-decimal"
    assert decoded["provenance"]["forecast_id"] == str(a.provenance.forecast_id)
    assert decoded["historical_error"]["mae_relative_to_latest_actual_pct"] == "1.00"
    copied = list(a.factors)
    rebuilt = a.model_copy()  # Frozen nested models and tuples remain safe to share.
    copied.clear()
    assert rebuilt.factors == a.factors
    assert isinstance(decoded["factors"], list)


def test_decimal_context_flags_and_extreme_finite_ratios():
    from decimal import localcontext, ROUND_DOWN
    r = result(latest_actual_rate=Decimal("123.45"), predicted_rate=Decimal("127.89"), backtest_mae=1.2345)
    expected = assess_evidence(r).model_dump_json()
    with localcontext() as context:
        context.prec = 3
        context.rounding = ROUND_DOWN
        context.clear_flags()
        before = str(context)
        assert assess_evidence(r).model_dump_json() == expected
        assert str(context) == before
    for actual, metric in ((Decimal("1E-100"), 1e100), (Decimal("1E100"), 1e-100)):
        a = assess_evidence(deficient_result(latest_actual_rate=actual, backtest_mae=metric, backtest_rmse=metric))
        assert a.historical_error.mae_relative_to_latest_actual_pct == Decimal(str(metric)) / actual * 100
        assert a.historical_error.mae_relative_to_latest_actual_pct.is_finite()
    a = assess_evidence(result(backtest_mae=1e308, backtest_rmse=1e308, backtest_smape=200, backtest_directional_accuracy=100))
    assert a.historical_evidence_status == H.AVAILABLE


def test_factor_order_across_hash_seeds():
    import os
    script = "from app.schemas.decision import DecisionResult; from app.services.reliability import assess_evidence; import sys; print(assess_evidence(DecisionResult.model_validate_json(sys.stdin.read())).model_dump_json())"
    outputs = [subprocess.run([sys.executable, '-B', '-c', script], input=result().model_dump_json(),
        text=True, capture_output=True, check=True, env={**os.environ, "PYTHONHASHSEED": seed}).stdout
        for seed in ("1", "42")]
    assert outputs[0] == outputs[1]
    a = assess_evidence(result())
    explanation = next(f.explanation for f in a.factors if f.code == C.SELECTION_WINDOW_NOT_INDEPENDENT)
    assert "Prefix out-of-sample walk-forward" in explanation
    assert "same evaluation window" in explanation
    assert "no independent post-selection holdout" in explanation


@pytest.mark.parametrize("fields", [{"backtest_mae": None}, {"backtest_smape": float("nan")},
    {"history_observations": True}, {"evaluation_points": 29}])
def test_unblocked_malformed_evidence_rejected(fields):
    r = result()
    f = r.forecast_identity.model_copy(update=fields)
    bad = r.model_copy(update={"forecast_identity": f,
        "input_snapshot": r.input_snapshot.model_copy(update={"forecast": f})})
    with pytest.raises(EvidenceInputError):
        assess_evidence(bad)


def test_zero_and_tiny_authoritative_movement_ratios():
    for change in (Decimal("0"), Decimal("1E-20")):
        r = result(predicted_rate=Decimal("100"))
        copied = r.model_copy(update={"signals": r.signals.model_copy(update={"absolute_change": change})})
        a = assess_evidence(copied)
        assert a.historical_error.movement_to_mae_ratio == change
        assert a.decision_evidence_status == D.MONITOR_ONLY


@pytest.mark.parametrize("state", [{"latest_source_date": None}, {"latest_forecast_id": None},
    {"latest_forecast_generated_at": None}, {"evaluated_at": NOW.replace(year=2025)}])
def test_unblocked_copied_identity_context_contradictions(state):
    r = result()
    bad = r.model_copy(update={"input_snapshot": r.input_snapshot.model_copy(update={
        "current_state": r.input_snapshot.current_state.model_copy(update=state)})})
    with pytest.raises(EvidenceInputError):
        assess_evidence(bad)


def test_external_construction_containers_cannot_mutate_assessment():
    from app.schemas.decision import DecisionResult
    payload = result().model_dump(mode="python")
    payload["reasons"] = list(payload["reasons"])
    payload["policy"]["supported_horizons"] = set(payload["policy"]["supported_horizons"])
    a = assess_evidence(DecisionResult.model_validate(payload))
    before = a.model_dump_json()
    payload["reasons"].clear()
    payload["policy"]["supported_horizons"].add(5)
    payload["forecast_identity"]["series"]["source"] = "changed"
    assert a.model_dump_json() == before
    with pytest.raises(ValueError):
        a.provenance.model_version = "changed"
