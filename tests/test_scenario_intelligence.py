"""Synthetic scenarios: upstream parity, immutable evidence and adversarial isolation."""
import ast
import builtins
import json
import inspect
import os
from pathlib import Path
import socket
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from decimal import Context, Decimal, Inexact, Rounded, FloatOperation, ROUND_DOWN, ROUND_UP, ROUND_HALF_UP, localcontext
from enum import IntEnum
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from app.schemas.decision import (
    Decision, DecisionInput, DecisionPolicy, ForecastSnapshot, ForecastState,
    HARD_BLOCKERS, REASON_ORDER, SeriesIdentity,
)
from app.schemas.scenario import (
    AbsoluteRate, PercentageAdjustment, AppliedAssumption, ScenarioComparison,
    ScenarioRequest, ScenarioResult,
)
from app.services.decision_engine import evaluate_decision
from app.services.reliability import assess_evidence
from app.services.scenario_intelligence import ScenarioInputError, _fingerprint, evaluate_scenario

NOW = datetime(2026, 1, 2, 12, tzinfo=timezone.utc)


def baseline(**updates):
    """Deliberately synthetic eligible fixture, not a generated runtime forecast."""
    fields = dict(forecast_id=UUID(int=1),
        series=SeriesIdentity(source="SCFI", trade_lane="Synthetic-L", container_type="40ft"),
        forecast_for_date=NOW.date(), predicted_rate=Decimal("103.00"),
        model_name="MA(3)", model_version="baseline-v1-decimal", forecast_horizon=1,
        latest_observation_date=NOW.date()-timedelta(days=1), latest_actual_rate=Decimal("100.00"),
        history_observations=100, evaluation_points=30, backtest_mae=1.0, backtest_rmse=2.0,
        backtest_smape=2.0, backtest_directional_accuracy=50.0, data_readiness="BASELINE_READY",
        input_freshness_at_generation="fresh", stored_live_decision_eligible=True,
        warning=None, generated_at=NOW-timedelta(hours=1))
    fields.update(updates)
    f = ForecastSnapshot(**fields)
    s = ForecastState(series=f.series, evaluated_at=NOW, latest_source_date=f.latest_observation_date,
        latest_forecast_id=f.forecast_id, latest_forecast_generated_at=f.generated_at,
        series_matches=True, source_superseded=False, forecast_superseded=False,
        current_input_freshness="fresh", stored_live_decision_eligible=f.stored_live_decision_eligible,
        effective_live_decision_eligible=f.stored_live_decision_eligible,
        context_state="current", context_warning=None)
    return DecisionInput(forecast=f, current_state=s)


def state(i, **updates):
    d = i.model_dump(mode="python")
    d["current_state"].update(updates)
    return DecisionInput.model_validate(d)


def request(value="105.00", kind="ABSOLUTE_PREDICTED_RATE"):
    return ScenarioRequest(assumption={"type": kind, "requested_value": value})


def run(i=None, q=None, policy=None, now=NOW):
    return evaluate_scenario(i if i is not None else baseline(), q or request(),
                             policy or DecisionPolicy(), now)


@pytest.mark.parametrize("kind,value,applied", [
    ("ABSOLUTE_PREDICTED_RATE", "105", "105"),
    ("ABSOLUTE_PREDICTED_RATE", "95", "95"),
    ("ABSOLUTE_PREDICTED_RATE", "103", "103"),
    ("PERCENTAGE_ADJUSTMENT", "5", "108.15"),
    ("PERCENTAGE_ADJUSTMENT", "-5", "97.85"),
    ("PERCENTAGE_ADJUSTMENT", "0", "103"),
    ("PERCENTAGE_ADJUSTMENT", "0.001", "103"),
])
def test_direct_t08_parity_and_full_preservation(kind, value, applied):
    i, p, q = baseline(), DecisionPolicy(), request(value, kind)
    before = i.model_dump(mode="python")
    p_before, q_before = p.model_dump(), q.model_dump()
    result = run(i, q, p)
    expected_doc = i.model_dump(mode="python")
    expected_doc["forecast"]["predicted_rate"] = Decimal(applied)
    expected = DecisionInput.model_validate(expected_doc)
    with localcontext(Context(prec=28)):
        direct = evaluate_decision(expected, p, NOW)
        factual = evaluate_decision(i, p, NOW)
    assert result.hypothetical_t08_result == direct
    assert result.baseline_evidence == assess_evidence(factual)
    scenario_doc = result.hypothetical_t08_result.input_snapshot.model_dump(mode="python")
    scenario_doc["forecast"]["predicted_rate"] = before["forecast"]["predicted_rate"]
    assert scenario_doc == before  # Every field, including nested state.
    assert i.model_dump(mode="python") == before
    assert p.model_dump() == p_before and q.model_dump() == q_before
    assert result.assumption.applied_predicted_rate == Decimal(applied)
    assert not result.live_actionable and result.hypothetical and result.non_operational
    assert result.assumption.provenance == "USER_SUPPLIED_HYPOTHETICAL"


@pytest.mark.parametrize("original,assumed,before,after", [
    ("101", "105", Decision.MONITOR, Decision.CONSIDER_EARLIER_BOOKING),
    ("103", "95", Decision.CONSIDER_EARLIER_BOOKING, Decision.CONSIDER_LATER_BOOKING),
    ("103", "101", Decision.CONSIDER_EARLIER_BOOKING, Decision.MONITOR),
    ("103", "105", Decision.CONSIDER_EARLIER_BOOKING, Decision.CONSIDER_EARLIER_BOOKING),
])
def test_decision_comparison(original, assumed, before, after):
    r = run(baseline(predicted_rate=Decimal(original)), request(assumed))
    c = r.comparison
    assert (c.baseline_decision, c.hypothetical_decision) == (before, after)
    assert c.decision_changed == (before != after)
    assert c.rule_actionability_changed == (c.baseline_rule_actionable != c.hypothetical_rule_actionable)
    assert not r.live_actionable


def test_zero_percentage_and_distinct_request_provenance():
    zero = run(q=request("-0.00", "PERCENTAGE_ADJUSTMENT"))
    assert zero.hypothetical_t08_result == zero.baseline_evidence.decision_result
    assert not zero.comparison.decision_changed
    assert zero.comparison.predicted_rate_delta == 0
    assert zero.comparison.added_hard_blockers == zero.comparison.removed_hard_blockers == ()
    assert zero.scenario_identity == run(q=request("0", "PERCENTAGE_ADJUSTMENT")).scenario_identity
    absolute = run(q=request("103"))
    assert zero.hypothetical_t08_result == absolute.hypothetical_t08_result
    assert zero.scenario_identity != absolute.scenario_identity
    rounded = run(q=request("0.001", "PERCENTAGE_ADJUSTMENT"))
    assert rounded.assumption.applied_predicted_rate == zero.assumption.applied_predicted_rate
    assert rounded.scenario_identity != zero.scenario_identity


def test_delta_uses_prediction_not_actual_and_t09_is_factual():
    r = run(q=request("10", "PERCENTAGE_ADJUSTMENT"))
    assert r.baseline_predicted_rate == Decimal("103")
    assert r.assumption.applied_predicted_rate == Decimal("113.30")
    assert r.comparison.predicted_rate_delta == Decimal("10.30")
    assert r.comparison.predicted_rate_delta_pct == Decimal("10")
    assert r.baseline_evidence.decision_result.forecast_identity.predicted_rate == Decimal("103")
    assert "hypothetical_evidence" not in r.model_fields


@pytest.mark.parametrize("condition", ["stale", "superseded", "source_newer", "historical",
    "history", "evaluation", "horizon", "metrics", "missing_source", "expired", "unknown", "minimal"])
def test_factual_blockers_survive_rate_substitution(condition):
    changes = {"history": {"history_observations": 31}, "evaluation": {"evaluation_points": 16},
        "horizon": {"forecast_horizon": 2}, "metrics": {"backtest_mae": None},
        "historical": {"stored_live_decision_eligible": False},
        "expired": {"forecast_for_date": NOW.date()-timedelta(days=1)},
        "minimal": {"data_readiness": "MINIMAL"}}
    i = baseline(**changes.get(condition, {}))
    if condition in ("stale", "unknown"):
        i = state(i, current_input_freshness=condition, effective_live_decision_eligible=False)
    if condition == "superseded":
        i = state(i, latest_forecast_generated_at=NOW, forecast_superseded=True,
                  context_state="superseded", effective_live_decision_eligible=False)
    if condition == "source_newer":
        i = state(i, latest_source_date=NOW.date(), source_superseded=True, forecast_superseded=True,
                  latest_forecast_id=None, latest_forecast_generated_at=None,
                  context_state="superseded", effective_live_decision_eligible=False)
    if condition == "missing_source":
        i = state(i, latest_source_date=None, forecast_superseded=True, latest_forecast_id=None,
                  latest_forecast_generated_at=None, context_state="source_unavailable",
                  effective_live_decision_eligible=False)
    r = run(i, request("90"))
    assert r.comparison.baseline_decision == r.comparison.hypothetical_decision == Decision.WITHHOLD
    assert r.comparison.baseline_movement != r.comparison.hypothetical_movement
    assert r.comparison.added_hard_blockers == r.comparison.removed_hard_blockers == ()
    assert r.analytical_only and not r.live_actionable


@pytest.mark.parametrize("assumed", ["102.99", "103", "103.01"])
def test_mae_guard_equality_through_upstream(assumed):
    i = baseline(backtest_mae=3.0)
    r = run(i, request(assumed))
    doc = i.model_dump(mode="python")
    doc["forecast"]["predicted_rate"] = Decimal(assumed)
    assert r.hypothetical_t08_result == evaluate_decision(DecisionInput.model_validate(doc), DecisionPolicy(), NOW)
    assert r.comparison.hypothetical_rule_actionable == (assumed == "103.01")
    expected_added = tuple(x for x in REASON_ORDER if x in HARD_BLOCKERS and
                           x in r.hypothetical_t08_result.reasons and
                           x not in r.baseline_evidence.decision_result.reasons)
    assert r.comparison.added_hard_blockers == expected_added


@pytest.mark.parametrize("value", [1.2, True, False, 105, "NaN", "Infinity", "-Infinity", "0", "-0",
    "-1", "1.001", "10000000000", "1e999999", "1e-999999", "1"*65, " 105"])
def test_invalid_absolute_assumptions(value):
    with pytest.raises(ValueError):
        request(value)


@pytest.mark.parametrize("value", [1.2, True, False, "NaN", "Infinity", "-Infinity", "1e999999"])
def test_invalid_percentage_representations(value):
    with pytest.raises(ValueError):
        request(value, "PERCENTAGE_ADJUSTMENT")


@pytest.mark.parametrize("value", ["-100", "-101", "-99.99999", "9999999999999999999999999999"])
def test_invalid_applied_percentage(value):
    with pytest.raises(ValueError):
        run(q=request(value, "PERCENTAGE_ADJUSTMENT"))


@pytest.mark.parametrize("raw,expected", [("0.005", "100.00"), ("0.015", "100.02")])
def test_half_even_once(raw, expected):
    r = run(baseline(predicted_rate=Decimal("100")), request(raw, "PERCENTAGE_ADJUSTMENT"))
    assert r.assumption.applied_predicted_rate == Decimal(expected)


@pytest.mark.parametrize("prec,rounding", [(6, ROUND_UP), (50, ROUND_DOWN)])
def test_caller_context_independence_and_no_flag_mutation(prec, rounding):
    expected = run(q=request("1.23456789", "PERCENTAGE_ADJUSTMENT"))
    with localcontext() as caller:
        caller.prec, caller.rounding = prec, rounding
        flags = caller.flags.copy()
        actual = run(q=request("1.23456789", "PERCENTAGE_ADJUSTMENT"))
        assert dict(caller.flags) == flags, (flags, dict(caller.flags))
        assert actual == expected


def test_large_valid_rate():
    r = run(baseline(predicted_rate=Decimal("9999999999.99")), request("0", "PERCENTAGE_ADJUSTMENT"))
    assert r.comparison.predicted_rate_delta == 0


@pytest.mark.parametrize("payload", [
    {}, {"category": "PORT_SCENARIO", "assumption": {"type": "ABSOLUTE_PREDICTED_RATE", "requested_value": "105"}},
    {"assumption": {"type": "FX_SCENARIO", "requested_value": "105"}},
    {"assumption": {"type": "ABSOLUTE_PREDICTED_RATE", "requested_value": "105", "percentage": "5"}},
    {"assumption": {"type": "ABSOLUTE_PREDICTED_RATE", "requested_value": "105"}, "policy": {}},
    {"assumption": {"type": "ABSOLUTE_PREDICTED_RATE", "requested_value": "105"}, "history_observations": 1000},
    {"assumption": [{"type": "ABSOLUTE_PREDICTED_RATE", "requested_value": "105"},
                    {"type": "PERCENTAGE_ADJUSTMENT", "requested_value": "5"}]},
])
def test_strict_request(payload):
    with pytest.raises(ValidationError):
        ScenarioRequest.model_validate(payload)


@pytest.mark.parametrize("field", ["latest_actual_rate", "current_freshness", "live_eligible", "model_version",
    "source", "mae", "forecast_horizon", "minimum_history", "error_multiplier", "evaluated_at"])
def test_no_arbitrary_overrides(field):
    d = request().model_dump()
    d[field] = "override"
    with pytest.raises(ValidationError):
        ScenarioRequest.model_validate(d)


@pytest.mark.parametrize("target", ["forecast", "state", "instant"])
def test_naive_time_rejected(target):
    i, now = baseline(), NOW
    if target == "forecast":
        i = baseline(generated_at=NOW.replace(tzinfo=None))
    elif target == "state":
        i = state(i, latest_forecast_generated_at=NOW.replace(tzinfo=None))
    else:
        now = NOW.replace(tzinfo=None)
    with pytest.raises(ValueError):
        run(i, now=now)


def test_timezone_equivalence_and_microseconds():
    i = baseline()
    d = i.model_dump(mode="python")
    offset = timezone(timedelta(hours=3))
    d["forecast"]["generated_at"] = d["forecast"]["generated_at"].astimezone(offset)
    for field in ("evaluated_at", "latest_forecast_generated_at"):
        d["current_state"][field] = d["current_state"][field].astimezone(offset)
    converted = run(DecisionInput.model_validate(d), now=NOW.astimezone(offset))
    assert converted.scenario_identity == run(i).scenario_identity
    later = NOW+timedelta(microseconds=1)
    assert run(state(i, evaluated_at=later), now=later).scenario_identity != run(i).scenario_identity


def test_dst_fold_identity_distinguishes_instants():
    zone = ZoneInfo("America/New_York")
    a = datetime(2026, 11, 1, 1, 30, fold=0, tzinfo=zone)
    b = datetime(2026, 11, 1, 1, 30, fold=1, tzinfo=zone)
    assert _fingerprint(a) != _fingerprint(b)
    assert _fingerprint(a) == _fingerprint(a.astimezone(timezone.utc))


def test_dst_fold_generation_mismatch_and_equivalent_state():
    zone = ZoneInfo("America/New_York")
    a = datetime(2026, 11, 1, 1, 30, fold=0, tzinfo=zone)
    b = datetime(2026, 11, 1, 1, 30, fold=1, tzinfo=zone)
    i = baseline(generated_at=a)
    with pytest.raises(ScenarioInputError):
        run(state(i, latest_forecast_generated_at=b))
    valid = state(i, evaluated_at=a, latest_forecast_generated_at=a.astimezone(timezone.utc))
    r = run(valid, now=a)
    assert r.evaluated_at == a.astimezone(timezone.utc)
    assert r.hypothetical_t08_result.input_snapshot.current_state.evaluated_at.tzinfo == timezone.utc


def test_bad_decimal_text_does_not_modify_caller_flags():
    with localcontext() as caller:
        flags = caller.flags.copy()
        with pytest.raises(ValueError):
            request("not a number")
        assert dict(caller.flags) == flags, (flags, dict(caller.flags))


def test_unvalidated_policy_rejected():
    p = DecisionPolicy().model_copy(update={"movement_threshold_pct": 2.0})
    with pytest.raises(ValueError):
        run(policy=p)


@pytest.mark.parametrize("text", ["scfi", " SCFI", "SCFI ", "é", "e\u0301", "SСFI", "SC FI"])
@pytest.mark.parametrize("dimension", ["source", "trade_lane", "container_type"])
def test_exact_series_preserved_without_normalization(text, dimension):
    # Preserve printable exact strings without inventing aliases.
    identity = baseline().forecast.series.model_dump()
    original = run()
    identity[dimension] = text
    i = baseline(series=SeriesIdentity(**identity))
    assert getattr(run(i).series, dimension) == text
    if text != getattr(original.series, dimension):
        assert run(i).scenario_identity != original.scenario_identity


@pytest.mark.parametrize("updates", [
    {"series_matches": False}, {"series": SeriesIdentity(source="other", trade_lane="L", container_type="40ft")},
    {"latest_forecast_id": UUID(int=2)}, {"latest_forecast_generated_at": NOW},
    {"evaluated_at": NOW+timedelta(seconds=1)}, {"source_superseded": True},
    {"stored_live_decision_eligible": False}, {"context_state": "superseded"},
])
def test_detectable_state_mismatch(updates):
    with pytest.raises(ValueError):
        run(state(baseline(), **updates))


@pytest.mark.parametrize("value", [Decimal("0"), Decimal("-1"), Decimal("NaN"), Decimal("Infinity"),
                                      Decimal("1.001"), 103.0, True])
def test_unvalidated_baseline_copies_rejected(value):
    i = baseline()
    corrupted = i.model_copy(update={"forecast": i.forecast.model_copy(update={"predicted_rate": value})})
    with pytest.raises(ValueError):
        run(corrupted)


def test_missing_baseline_rejected_without_generation():
    with pytest.raises(ScenarioInputError):
        evaluate_scenario(None, request(), DecisionPolicy(), NOW)


def test_invalid_constructed_request_revalidated():
    invalid = AbsoluteRate.model_construct(requested_value=Decimal("-1"))
    with pytest.raises(ValueError):
        run(q=ScenarioRequest.model_construct(assumption=invalid))


@pytest.mark.parametrize("field,value", [("backtest_mae", True), ("backtest_rmse", 2)])
def test_unsafe_metric_copy_is_not_silently_repaired(field, value):
    i = baseline()
    corrupted = i.model_copy(update={"forecast": i.forecast.model_copy(update={field: value})})
    with pytest.raises(ScenarioInputError):
        run(corrupted)


def test_immutability_and_live_promotion_rejected():
    r = run()
    for obj, field, value in [(r, "live_actionable", True), (r.assumption, "applied_predicted_rate", Decimal("999")),
                              (r.comparison, "decision_changed", True), (request().assumption, "requested_value", Decimal("999"))]:
        with pytest.raises(ValidationError):
            setattr(obj, field, value)
    d = r.model_dump()
    d["live_actionable"] = True
    with pytest.raises(ValidationError):
        ScenarioResult.model_validate(d)
    assert isinstance(r.limitations, tuple) and isinstance(r.comparison.added_hard_blockers, tuple)


def test_identity_tracks_all_factual_evidence_and_generation():
    r = run()
    for changes in ({"backtest_mae": 1.1}, {"warning": "different"}, {"history_observations": 101},
                    {"generated_at": NOW}, {"model_name": "MA(4)"}):
        updated = run(baseline(**changes))
        assert updated.baseline_fingerprint != r.baseline_fingerprint
        assert updated.scenario_identity != r.scenario_identity
    assert run(q=request("105.00")).scenario_identity == run(q=request("105.0")).scenario_identity
    assert run(q=request("106")).scenario_identity != r.scenario_identity
    assert _fingerprint({"a": frozenset({2, 1}), "b": Decimal("1.00")}) == _fingerprint({"b": Decimal("1"), "a": {1, 2}})


def test_supplied_application_policy_preserved():
    p = DecisionPolicy(movement_threshold_pct=Decimal("3"), supported_horizons=frozenset({1, 2}))
    r = run(policy=p)
    assert r.baseline_evidence.decision_result.policy == r.hypothetical_t08_result.policy == p


def test_pure_production_imports_and_no_shadow_engine():
    for file in ("app/schemas/scenario.py", "app/services/scenario_intelligence.py"):
        tree = ast.parse(Path(file).read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [node.module] if isinstance(node, ast.ImportFrom) else [a.name for a in node.names]
                assert all(name.split(".")[0] in {"datetime", "decimal", "enum", "typing", "pydantic",
                    "app", "hashlib", "json", "math", "uuid", "re"} for name in names)
                assert not any(token in name for name in names for token in (
                    "predictive_alert", "publisher", "database", "rate_outlook", "openai", "celery", "redis"))
            if isinstance(node, ast.Call):
                assert not (isinstance(node.func, ast.Attribute) and node.func.attr in ("now", "time", "model_copy"))


def test_runtime_guards_and_factual_only_t09(monkeypatch):
    import app.services.scenario_intelligence as service
    i, q, p = baseline(), request(), DecisionPolicy()
    original = service.assess_evidence
    seen = []
    def assess(result):
        seen.append(result)
        return original(result)
    monkeypatch.setattr(service, "assess_evidence", assess)
    def blocked(*args, **kwargs):
        raise AssertionError("Forbidden runtime infrastructure access")
    monkeypatch.setattr(builtins, "open", blocked)
    monkeypatch.setattr(socket, "socket", blocked)
    monkeypatch.setattr(os, "getenv", blocked)
    monkeypatch.setattr(subprocess, "run", blocked)
    r = run(i, q, p)
    assert seen == [r.baseline_evidence.decision_result]


def test_fresh_process_hashseed_and_infrastructure_isolation():
    script = '''
import sys
from tests.test_scenario_intelligence import baseline, request, NOW
from app.schemas.decision import DecisionPolicy
from app.services.scenario_intelligence import evaluate_scenario
print(evaluate_scenario(baseline(), request(), DecisionPolicy(), NOW).scenario_identity)
'''
    # Use a separate production-only process too: importing the test file imports pytest.
    pure = '''
import sys
import app.services.scenario_intelligence
bad = [n for n in sys.modules if n.split('.')[0] in {'sqlalchemy','redis','celery','fastapi','openai'}
       or 'predictive_alert' in n or 'alert_publisher' in n or n == 'app.config']
assert not bad, bad
'''
    subprocess.run([sys.executable, "-c", pure], check=True, capture_output=True, text=True)
    identities = []
    for seed in ("1", "321"):
        out = subprocess.run([sys.executable, "-c", script], env={**os.environ, "PYTHONHASHSEED": seed},
                             check=True, capture_output=True, text=True)
        identities.append(out.stdout.strip())
    assert identities == [run().scenario_identity]*2


def test_guarded_fresh_process_evaluation():
    setup = '''
import builtins, io, os, random, socket, subprocess, sys, time, uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID
from app.schemas.decision import DecisionInput, DecisionPolicy, ForecastSnapshot, ForecastState, SeriesIdentity
from app.schemas.scenario import ScenarioRequest
from app.services.scenario_intelligence import evaluate_scenario
NOW = datetime(2026, 1, 2, 12, tzinfo=timezone.utc)
'''
    guarded = '''
i = baseline()
q = ScenarioRequest(assumption={'type':'ABSOLUTE_PREDICTED_RATE','requested_value':'105'})
p = DecisionPolicy()
def blocked(*args, **kwargs):
    raise AssertionError('Forbidden runtime access')
original_import = builtins.__import__
def checked_import(name, *args, **kwargs):
    if name.split('.')[0] in {'sqlalchemy','redis','celery','fastapi','openai'} or any(
            token in name for token in ('predictive_alert','alert_publisher','app.config','app.database')):
        raise AssertionError('Forbidden import: '+name)
    return original_import(name, *args, **kwargs)
builtins.__import__ = checked_import
builtins.open = io.open = blocked
socket.socket = socket.create_connection = blocked
os.getenv = subprocess.run = subprocess.Popen = blocked
time.time = time.monotonic = random.random = uuid.uuid4 = blocked
class NoEnvironment(dict):
    def __getitem__(self, key): return blocked()
    def get(self, *args): return blocked()
os.environ = NoEnvironment()
r = evaluate_scenario(i, q, p, NOW)
assert r.live_actionable is False
print(r.scenario_identity)
'''
    out = subprocess.run([sys.executable, "-c", setup+inspect.getsource(baseline)+guarded],
                         check=True, capture_output=True, text=True)
    assert out.stdout.strip() == run().scenario_identity


@pytest.mark.parametrize("kind", ["ABSOLUTE_PREDICTED_RATE", "PERCENTAGE_ADJUSTMENT"])
@pytest.mark.parametrize("value", [None, "", " ", "\t", 5, "1_05", "١٠٥", "１０５", "1,05", "1 05", "1e-9999"])
def test_explicit_external_representation_rejections(kind, value):
    with pytest.raises(ValueError):
        request(value, kind)


@pytest.mark.parametrize("kind", ["ABSOLUTE_PREDICTED_RATE", "PERCENTAGE_ADJUSTMENT"])
@pytest.mark.parametrize("value", [Decimal("100"), "100", "+100.00", "1e2", "100."])
def test_plain_decimal_representations(kind, value):
    q = request(value, kind)
    assert q.assumption.requested_value == Decimal("100")


@pytest.mark.parametrize("value", ["1000", "1000.0", "1000.00", "1000.000", "1.00000e3"])
def test_redundant_zero_money_is_not_rounding(value):
    assert run(q=request(value)).assumption.applied_predicted_rate == Decimal("1000")
    assert run(q=request(value)).scenario_identity == run(q=request("1000")).scenario_identity


@pytest.mark.parametrize("zero", ["+0", "-0", "0.0", "-0.00", Decimal("-0")])
def test_all_zero_percentage_semantics(zero):
    r = run(q=request(zero, "PERCENTAGE_ADJUSTMENT"))
    reference = run(q=request("0", "PERCENTAGE_ADJUSTMENT"))
    assert r.scenario_identity == reference.scenario_identity
    assert r.hypothetical_t08_result == r.baseline_evidence.decision_result
    assert r.comparison.predicted_rate_delta == r.comparison.predicted_rate_delta_pct == 0
    assert not r.comparison.decision_changed and not r.comparison.rule_actionability_changed
    assert r.comparison.added_hard_blockers == r.comparison.removed_hard_blockers == ()
    assert not r.live_actionable


def test_percentage_equivalence_and_distinct_rounding_collisions():
    equivalent = [run(q=request(v, "PERCENTAGE_ADJUSTMENT")) for v in ("5", "5.0", "5.00")]
    assert len({r.scenario_identity for r in equivalent}) == 1
    collisions = [run(q=request(v, "PERCENTAGE_ADJUSTMENT")) for v in ("0.001", "0.002", "0.003")]
    assert len({r.scenario_identity for r in collisions}) == 3
    assert all(r.assumption.applied_predicted_rate == Decimal("103") for r in collisions)
    assert all(r.hypothetical_t08_result == collisions[0].hypothetical_t08_result for r in collisions)
    absolute = run(q=request("108.15"))
    assert absolute.hypothetical_t08_result == equivalent[0].hypothetical_t08_result
    assert absolute.scenario_identity != equivalent[0].scenario_identity


@pytest.mark.parametrize("dimension", ["source", "trade_lane", "container_type"])
@pytest.mark.parametrize("value", ["", " ", "\t\n", "\x00", "S\nCFI", "SC\u200bFI"])
def test_blank_control_series_fail_closed(dimension, value):
    identity = baseline().forecast.series.model_dump()
    identity[dimension] = value
    with pytest.raises(ScenarioInputError):
        run(baseline(series=SeriesIdentity(**identity)))


@pytest.mark.parametrize("value", ["0.01", "9999999999.99"])
def test_absolute_money_domain_endpoints(value):
    assert run(q=request(value)).assumption.applied_predicted_rate == Decimal(value)


@pytest.mark.parametrize("value", ["10000000000.00", "0.001", "+0", "-0.00", "-0.01"])
def test_absolute_money_just_outside_domain(value):
    with pytest.raises(ValueError):
        request(value)


@pytest.mark.parametrize("value,valid", [("-99.99", True), ("-99.999", False),
    ("-100", False), ("-101", False), ("1e27", False), ("-1e27", False)])
def test_percentage_money_extremes_are_domain_failures(value, valid):
    if valid:
        assert run(baseline(predicted_rate=Decimal("100")), request(value, "PERCENTAGE_ADJUSTMENT")).assumption.applied_predicted_rate == Decimal("0.01")
    else:
        with pytest.raises(ValueError):
            run(baseline(predicted_rate=Decimal("100")), request(value, "PERCENTAGE_ADJUSTMENT"))


@pytest.mark.parametrize("rounding", [ROUND_UP, ROUND_DOWN, ROUND_HALF_UP])
@pytest.mark.parametrize("precision", [2, 60])
def test_hostile_context_traps_and_preset_flags(rounding, precision):
    i, q, p = baseline(), request("0.005", "PERCENTAGE_ADJUSTMENT"), DecisionPolicy()
    reference = run(i, q, p)
    with localcontext() as c:
        c.prec, c.rounding = precision, rounding
        c.traps[Inexact] = c.traps[Rounded] = c.traps[FloatOperation] = True
        c.flags[Inexact] = c.flags[Rounded] = True
        saved = (c.prec, c.rounding, dict(c.traps), dict(c.flags))
        r = run(i, q, p)
        assert (c.prec, c.rounding, dict(c.traps), dict(c.flags)) == saved
        assert r == reference


class Horizon(IntEnum):
    ONE = 1


@pytest.mark.parametrize("field,value", [
    ("movement_threshold_pct", True), ("movement_threshold_pct", "2"),
    ("movement_threshold_pct", 2), ("error_multiplier", 1.0),
    ("min_history_observations", True), ("min_evaluation_points", "30"),
    ("supported_horizons", {1}), ("supported_horizons", frozenset({True})),
    ("supported_horizons", frozenset({Horizon.ONE})), ("supported_horizons", frozenset({"1"})),
    ("supported_horizons", frozenset({-1})), ("supported_horizons", frozenset()),
])
def test_nested_policy_construct_coercion(field, value):
    p = DecisionPolicy().model_copy(update={field: value})
    with pytest.raises(ValueError):
        run(policy=p)


@pytest.mark.parametrize("field", tuple(DecisionPolicy.model_fields))
def test_every_policy_field_affects_scenario_identity(field):
    values = {"movement_threshold_pct": Decimal("3"), "min_history_observations": 101,
        "min_evaluation_points": 31, "error_multiplier": Decimal("2"), "supported_horizons": frozenset({1, 2})}
    assert set(values) == set(DecisionPolicy.model_fields)
    p = DecisionPolicy(**{**DecisionPolicy().model_dump(), field: values[field]})
    assert run(policy=p).scenario_identity != run().scenario_identity
    assert run(policy=p).baseline_fingerprint == run().baseline_fingerprint


def test_policy_scale_and_set_equivalence():
    a = DecisionPolicy(movement_threshold_pct=Decimal("2"), supported_horizons=frozenset([2, 1]))
    b = DecisionPolicy(movement_threshold_pct=Decimal("2.00"), supported_horizons=frozenset([1, 2]))
    assert run(policy=a).scenario_identity == run(policy=b).scenario_identity


@pytest.mark.parametrize("level", ["request", "assumption", "baseline", "forecast", "state", "series", "policy"])
def test_unsafe_copy_extras_not_silently_erased(level):
    i, q, p = baseline(), request(), DecisionPolicy()
    if level == "request": q = q.model_copy(update={"policy": "override"})
    elif level == "assumption": q = q.model_copy(update={"assumption": q.assumption.model_copy(update={"freshness": "override"})})
    elif level == "baseline": i = i.model_copy(update={"policy": "override"})
    elif level == "forecast": i = i.model_copy(update={"forecast": i.forecast.model_copy(update={"confidence": 100})})
    elif level == "state": i = i.model_copy(update={"current_state": i.current_state.model_copy(update={"live_actionable": True})})
    elif level == "series": i = i.model_copy(update={"forecast": i.forecast.model_copy(update={"series": i.forecast.series.model_copy(update={"alias": "override"})})})
    else: p = p.model_copy(update={"confidence": 100})
    with pytest.raises(ValueError): run(i, q, p)


def test_custom_numeric_objects_never_invoked():
    class NumericLike:
        def __str__(self): raise AssertionError("custom str invoked")
        def __float__(self): raise AssertionError("custom numeric conversion invoked")
    class Text(str):
        def strip(self): raise AssertionError("subclass parser invoked")
    class Number(Decimal):
        def is_finite(self): raise AssertionError("numeric subclass invoked")
    for value in (NumericLike(), Text("105"), Number("105"), Horizon.ONE):
        for kind in ("ABSOLUTE_PREDICTED_RATE", "PERCENTAGE_ADJUSTMENT"):
            with pytest.raises(ValueError): request(value, kind)
    with pytest.raises(ValueError):
        run(baseline().model_copy(update={"forecast": baseline().forecast.model_copy(update={"predicted_rate": Number("105")})}))


@pytest.mark.parametrize("instant", [datetime.min.replace(tzinfo=timezone(timedelta(hours=1))),
                                    datetime.max.replace(tzinfo=timezone(timedelta(hours=-1)))])
def test_utc_conversion_overflow_becomes_domain_error(instant):
    with pytest.raises(ScenarioInputError): run(now=instant)
    with pytest.raises(ScenarioInputError): run(baseline(generated_at=instant))


def test_unrepresentable_next_observation_date_is_domain_error():
    now = datetime.max.replace(tzinfo=timezone.utc)
    i = state(baseline(latest_observation_date=date.max, forecast_for_date=date.max), evaluated_at=now)
    with pytest.raises(ScenarioInputError): run(i, now=now)


def test_exact_t08_t09_call_counts_and_arguments(monkeypatch):
    import app.services.scenario_intelligence as service
    calls, assessments = [], []
    original_decision, original_assess = service.evaluate_decision, service.assess_evidence
    def decide(i, p, instant):
        calls.append((i, p, instant))
        return original_decision(i, p, instant)
    def assess(result):
        assessments.append(result)
        return original_assess(result)
    monkeypatch.setattr(service, "evaluate_decision", decide)
    monkeypatch.setattr(service, "assess_evidence", assess)
    r = run()
    assert len(calls) == 2 and len(assessments) == 1
    assert assessments[0] == r.baseline_evidence.decision_result
    factual, hypothetical = calls[0][0].model_dump(), calls[1][0].model_dump()
    hypothetical["forecast"]["predicted_rate"] = factual["forecast"]["predicted_rate"]
    assert hypothetical == factual
    assert calls[0][1:] == calls[1][1:]
    assert r.baseline_evidence.decision_result.input_snapshot == calls[0][0]


def test_t09_from_another_baseline_cannot_be_supplied():
    a = run()
    q = request().model_copy(update={"baseline_evidence": a.baseline_evidence})
    with pytest.raises(ValueError): run(baseline(predicted_rate=Decimal("110")), q)


def test_decision_changes_without_movement_change_and_multiple_blockers():
    r = run(baseline(backtest_mae=3.0), request("104"))
    assert r.comparison.baseline_movement == r.comparison.hypothetical_movement
    assert r.comparison.decision_changed and r.comparison.rule_actionability_changed
    blocked = run(baseline(stored_live_decision_eligible=False, history_observations=31, evaluation_points=16), request("90"))
    factual_reasons = blocked.baseline_evidence.decision_result.reasons
    assert len([r for r in factual_reasons if r in HARD_BLOCKERS]) >= 3
    assert blocked.comparison.added_hard_blockers == blocked.comparison.removed_hard_blockers == ()


@pytest.mark.parametrize("schema", [AbsoluteRate, PercentageAdjustment, ScenarioRequest,
                                    AppliedAssumption, ScenarioComparison, ScenarioResult])
def test_every_public_schema_rejects_extra_fields(schema):
    r = run()
    objects = {AbsoluteRate: request().assumption, PercentageAdjustment: request("5", "PERCENTAGE_ADJUSTMENT").assumption,
        ScenarioRequest: request(), AppliedAssumption: r.assumption,
        ScenarioComparison: r.comparison, ScenarioResult: r}
    d = objects[schema].model_dump(mode="python")
    d["unauthorized_policy_override"] = "forbidden"
    with pytest.raises(ValueError): schema.model_validate(d)


def factual_mutations():
    """Inventory every scalar/nested identity leaf; no handpicked omission allowance."""
    forecast = {
        "forecast_id": UUID(int=2), "series": SeriesIdentity(source="OTHER", trade_lane="L", container_type="20ft"),
        "forecast_for_date": NOW.date()+timedelta(days=1), "predicted_rate": Decimal("104"),
        "model_name": "MA(4)", "model_version": "different-version", "forecast_horizon": 2,
        "latest_observation_date": NOW.date()-timedelta(days=2), "latest_actual_rate": Decimal("101"),
        "history_observations": 101, "evaluation_points": 31, "backtest_mae": 1.1,
        "backtest_rmse": 2.1, "backtest_smape": 3.0, "backtest_directional_accuracy": 51.0,
        "data_readiness": "MINIMAL", "input_freshness_at_generation": "aging",
        "stored_live_decision_eligible": False, "warning": "different warning",
        "generated_at": NOW,
    }
    current = {
        "series": forecast["series"], "evaluated_at": NOW+timedelta(microseconds=1),
        "latest_source_date": None, "latest_forecast_id": UUID(int=2), "latest_forecast_generated_at": NOW,
        "series_matches": False, "source_superseded": True, "forecast_superseded": True,
        "current_input_freshness": "aging", "stored_live_decision_eligible": False,
        "effective_live_decision_eligible": False, "context_state": "superseded", "context_warning": "different warning",
    }
    assert set(forecast) == set(ForecastSnapshot.model_fields)
    assert set(current) == set(ForecastState.model_fields)
    cases = [(section, field, value) for section, fields in (("forecast", forecast), ("current_state", current))
             for field, value in fields.items()]
    cases += [(section+".series", field, "distinct-"+field)
              for section in ("forecast", "current_state") for field in SeriesIdentity.model_fields]
    return cases


@pytest.mark.parametrize("section,field,value", factual_mutations())
def test_complete_factual_fingerprint_field_omission_attack(section, field, value):
    i, reference = baseline(), run()
    d = i.model_dump(mode="python")
    target = d
    for key in section.split("."): target = target[key]
    target[field] = value.model_dump() if isinstance(value, SeriesIdentity) else value
    changed = DecisionInput.model_validate(d)
    # Unit-level coverage of canonical fingerprinting includes invalid compositions.
    assert _fingerprint(changed) != reference.baseline_fingerprint
    coupled_forecast = {"forecast_id", "series", "latest_observation_date", "stored_live_decision_eligible", "generated_at"}
    accepted_state = {"current_input_freshness", "effective_live_decision_eligible", "context_warning"}
    must_reject = (section.endswith(".series") or
                   (section == "forecast" and field in coupled_forecast) or
                   (section == "current_state" and field not in accepted_state))
    if must_reject:
        with pytest.raises(ScenarioInputError): run(changed)
        return
    result = run(changed)
    assert result.baseline_fingerprint != reference.baseline_fingerprint
    assert result.scenario_identity != reference.scenario_identity


def test_coupled_generation_and_factual_state_changes_are_distinguishable():
    i = baseline()
    generation = i.forecast.generated_at+timedelta(microseconds=1)
    regenerated = baseline(generated_at=generation)
    a, b = run(i), run(regenerated)
    assert a.baseline_evidence.provenance.forecast_id == b.baseline_evidence.provenance.forecast_id
    assert a.baseline_fingerprint != b.baseline_fingerprint and a.scenario_identity != b.scenario_identity
    changed_state = run(state(i, context_warning="same generation, changed factual context"))
    assert changed_state.baseline_fingerprint != a.baseline_fingerprint
    assert changed_state.scenario_identity != a.scenario_identity


@pytest.mark.parametrize("bad", [Decimal("NaN"), Decimal("Infinity"), None, "2", True])
def test_unsafe_factual_integer_representation(bad):
    i = baseline()
    copied = i.model_copy(update={"forecast": i.forecast.model_copy(update={"history_observations": bad})})
    with pytest.raises(ValueError): run(copied)


@pytest.mark.parametrize("missing", ["baseline", "request", "forecast"])
def test_missing_constructed_domain_fields_are_controlled(missing):
    i, q = baseline(), request()
    if missing == "baseline": i = DecisionInput.model_construct()
    elif missing == "request": q = ScenarioRequest.model_construct()
    else: i = i.model_copy(update={"forecast": ForecastSnapshot.model_construct()})
    with pytest.raises(ValueError): run(i, q)


def test_all_nested_public_models_frozen_and_detached():
    r = run()
    for obj, field, value in [(r.baseline_evidence, "assessment_version", "changed"),
        (r.baseline_evidence.decision_result.input_snapshot.current_state, "context_state", "changed"),
        (r.hypothetical_t08_result.policy, "error_multiplier", Decimal("0.1")),
        (request(), "category", "PORT_SCENARIO")]:
        with pytest.raises(ValueError): setattr(obj, field, value)
    before = r.model_dump(mode="json")
    detached = r.model_dump(mode="python")
    detached["comparison"]["decision_changed"] = not r.comparison.decision_changed
    assert r.model_dump(mode="json") == before
    assert before["live_actionable"] is False and before["hypothetical"] is True
    assert before["comparison"]["hypothetical_rule_actionable"] is True


def test_fresh_process_full_output_locale_timezone_and_hashseed():
    script = '''
from tests.test_scenario_intelligence import run
print(run().model_dump_json())
'''
    outputs = []
    for seed, zone, locale_name in (("1", "UTC", "C"), ("321", "Pacific/Honolulu", "C.UTF-8")):
        r = subprocess.run([sys.executable, "-c", script], check=True, capture_output=True, text=True,
            env={**os.environ, "PYTHONHASHSEED": seed, "TZ": zone, "LC_ALL": locale_name})
        outputs.append(json.loads(r.stdout))
    assert outputs[0] == outputs[1] == run().model_dump(mode="json")


def test_subclass_models_and_nested_integer_enums_fail_closed():
    class PolicySubclass(DecisionPolicy):
        pass
    class RequestSubclass(ScenarioRequest):
        pass
    with pytest.raises(ValueError): run(policy=PolicySubclass())
    with pytest.raises(ValueError): run(q=RequestSubclass(assumption=request().assumption))
    i = baseline()
    corrupt = i.model_copy(update={"forecast": i.forecast.model_copy(update={"forecast_horizon": Horizon.ONE})})
    with pytest.raises(ValueError): run(corrupt)


@pytest.mark.parametrize("metric", [float("nan"), float("inf"), -1.0])
def test_deficient_float_metrics_remain_factual_blocked_evidence(metric):
    r = run(baseline(backtest_mae=metric))
    assert r.comparison.baseline_decision == r.comparison.hypothetical_decision == Decision.WITHHOLD
    assert not r.live_actionable and r.analytical_only
    assert r.comparison.added_hard_blockers == r.comparison.removed_hard_blockers == ()


def test_canonical_uuid_enum_and_ordered_sequence_semantics():
    assert _fingerprint(UUID(int=1)) == _fingerprint(UUID(str(UUID(int=1))))
    assert _fingerprint(Decision.MONITOR) == _fingerprint(Decision.MONITOR.value)
    # Ordered evidence tuples are semantic; do not erase their order.
    assert _fingerprint(("first", "second")) != _fingerprint(("second", "first"))
