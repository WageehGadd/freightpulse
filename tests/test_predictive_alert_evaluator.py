"""Real upstream outputs, adversarial boundaries and pure-process proof."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest

from app.schemas.decision import Decision, DecisionPolicy, Movement, SeriesIdentity
from app.schemas.reliability import HistoricalEvidenceStatus
from app.schemas.reliability import DecisionEvidenceStatus
from app.schemas.predictive_alert import (
    AlertCheckpoint, AlertReason, AlertStatus, PredictiveAlertInput,
    PredictiveAlertResult, SignalCategory, Transition,
)
from app.services.decision_engine import evaluate_decision
from app.services.reliability import assess_evidence
from app.services.predictive_alert_evaluator import evaluate_predictive_alert, _digest, _token
from tests.test_decision_engine import evidence, NOW


def current(kind="earlier", previous=None, series=None, state=None, **fields):
    if kind == "unavailable":
        r = evaluate_decision(None, DecisionPolicy(), NOW)
    else:
        fields = {"model_version": "baseline-v1-decimal", **fields}
        fields.setdefault("predicted_rate", Decimal({
            "earlier": "103", "later": "97", "monitor": "101", "blocked": "103", "unsupported": "103"}[kind]))
        if kind == "blocked":
            fields.setdefault("stored_live_decision_eligible", False)
        if kind == "unsupported":
            fields.setdefault("model_name", "unsupported")
        i = evidence(**fields)
        if series:
            i = i.model_copy(update={"forecast": i.forecast.model_copy(update={"series": series}),
                                    "current_state": i.current_state.model_copy(update={"series": series})})
        if state:
            i = i.model_copy(update={"current_state": i.current_state.model_copy(update=state)})
        r = evaluate_decision(i, DecisionPolicy(), NOW)
    a = assess_evidence(r)
    return PredictiveAlertInput(series=series or SeriesIdentity(source="SCFI", trade_lane="L", container_type="40ft"),
                               decision=r, evidence=a, previous_checkpoint=previous)


def checkpoint(kind, **fields):
    result = evaluate_predictive_alert(current(kind, **fields))
    assert result.status == AlertStatus.BASELINE_ONLY
    return result.next_checkpoint


@pytest.mark.parametrize("kind", ["earlier", "later", "blocked", "monitor", "unavailable", "unsupported"])
def test_genesis(kind):
    r = evaluate_predictive_alert(current(kind))
    assert r.status == AlertStatus.BASELINE_ONLY
    assert r.transition is None and r.signal_identity is None
    assert AlertReason.PREVIOUS_CHECKPOINT_ABSENT in r.reasons
    assert r.next_checkpoint.previous_token is None


@pytest.mark.parametrize("old", ["earlier", "later", "blocked", "monitor", "unavailable", "unsupported"])
@pytest.mark.parametrize("new", ["earlier", "later", "blocked", "monitor", "unavailable", "unsupported"])
def test_complete_transition_matrix(old, new):
    data = current(new, checkpoint(old))
    r = evaluate_predictive_alert(data)
    entered, reversed_, withdrawn = (Transition.DIRECTIONAL_ENTERED,
        Transition.DIRECTION_REVERSED, Transition.ACTIONABILITY_WITHDRAWN)
    # Explicit contract oracle, independent of the evaluator's branching.
    columns = ("earlier", "later", "blocked", "monitor", "unavailable", "unsupported")
    rows = {
        "earlier": (None, reversed_, withdrawn, withdrawn, withdrawn, withdrawn),
        "later": (reversed_, None, withdrawn, withdrawn, withdrawn, withdrawn),
        "blocked": (entered, entered, None, None, None, None),
        "monitor": (entered, entered, None, None, None, None),
        "unavailable": (entered, entered, None, None, None, None),
        "unsupported": (entered, entered, None, None, None, None),
    }
    expected = rows[old][columns.index(new)]
    assert r.transition == expected
    assert r.status == (AlertStatus.EMIT if expected else AlertStatus.SUPPRESS)
    if expected:
        assert r.category == (SignalCategory.OPERATIONAL if
            expected == Transition.ACTIONABILITY_WITHDRAWN else SignalCategory.DIRECTIONAL)
    else:
        assert r.signal_identity is None and r.category is None
    assert r.evidence == data.evidence
    assert r == evaluate_predictive_alert(data)


def test_cycle_and_retry_identity():
    first = evaluate_predictive_alert(current("earlier", checkpoint("blocked")))
    withdrawal = evaluate_predictive_alert(current("blocked", first.next_checkpoint))
    recurring = evaluate_predictive_alert(current("earlier", withdrawal.next_checkpoint))
    assert first.transition == recurring.transition == Transition.DIRECTIONAL_ENTERED
    assert first.signal_identity != recurring.signal_identity
    assert first.next_checkpoint.state_fingerprint == recurring.next_checkpoint.state_fingerprint
    assert first.next_checkpoint.accepted_checkpoint_token != recurring.next_checkpoint.accepted_checkpoint_token
    data = current("earlier", withdrawal.next_checkpoint)
    assert all(evaluate_predictive_alert(data) == recurring for _ in range(30))


def test_same_id_generation_changes_identity_without_directional_noise():
    old = checkpoint("earlier")
    r = evaluate_predictive_alert(current("earlier", old, generated_at=NOW-timedelta(minutes=1)))
    assert r.status == AlertStatus.SUPPRESS
    assert r.reasons == (AlertReason.UNCHANGED_DIRECTION,)
    assert r.next_checkpoint.state.generation.forecast_id == old.state.generation.forecast_id
    assert r.next_checkpoint.state_fingerprint != old.state_fingerprint


@pytest.mark.parametrize("field", ["source", "trade_lane", "container_type"])
def test_exact_series_isolation(field):
    series = current().series.model_copy(update={field: "different"})
    assert evaluate_predictive_alert(current(series=series)).status == AlertStatus.BASELINE_ONLY
    assert checkpoint("earlier", series=series).accepted_checkpoint_token != checkpoint("earlier").accepted_checkpoint_token
    r = evaluate_predictive_alert(current(previous=checkpoint("earlier"), series=series))
    assert r.status == AlertStatus.INVALID_INPUT and r.next_checkpoint is None
    mismatched = current().model_copy(update={"series": series})
    assert evaluate_predictive_alert(mismatched).status == AlertStatus.INVALID_INPUT


@pytest.mark.parametrize("identifier", ["", " ", "\t\n"])
def test_blank_series(identifier):
    assert evaluate_predictive_alert(current(series=current().series.model_copy(update={"source": identifier}))).status == AlertStatus.INVALID_INPUT


def test_no_series_normalization():
    tokens = [checkpoint("earlier", series=current().series.model_copy(update={"source": s})).accepted_checkpoint_token
              for s in ("SCFI", "scfi", " SCFI", "SCFI ")]
    assert len(set(tokens)) == 4


@pytest.mark.parametrize("state", [
    {"current_input_freshness": "stale"}, {"current_input_freshness": "unknown"},
    {"source_superseded": True}, {"forecast_superseded": True},
    {"effective_live_decision_eligible": False}, {"latest_source_date": None},
])
def test_valid_upstream_blockers_withdraw_operationally(state):
    data = current(previous=checkpoint("earlier"), state=state)
    assert not data.decision.actionable
    r = evaluate_predictive_alert(data)
    assert r.transition == Transition.ACTIONABILITY_WITHDRAWN
    assert r.category == SignalCategory.OPERATIONAL
    assert r.evidence.current_state == data.evidence.current_state


@pytest.mark.parametrize("fields", [
    {"stored_live_decision_eligible": False}, {"forecast_horizon": 2},
    {"forecast_for_date": NOW.date()-timedelta(days=1)},
    {"history_observations": 31, "evaluation_points": 16},
    {"backtest_mae": None}, {"backtest_mae": float("nan")},
    {"latest_actual_rate": Decimal("NaN")},
])
def test_safe_deficient_evidence_is_not_invalid(fields):
    data = current(previous=checkpoint("blocked"), **fields)
    r = evaluate_predictive_alert(data)
    assert r.status == AlertStatus.SUPPRESS
    assert r.next_checkpoint.state.eligible_direction is None


def test_unsupported_methodology_preserves_t08_and_suppresses():
    data = current(model_name="future-method")
    assert data.decision.actionable  # Legitimate T09 unsupported classification.
    r = evaluate_predictive_alert(data)
    assert r.status == AlertStatus.BASELINE_ONLY
    assert r.next_checkpoint.state.actionable
    assert r.next_checkpoint.state.eligible_direction is None
    assert r.evidence == data.evidence
    assert AlertReason.EVIDENCE_NOT_AVAILABLE in r.reasons


@pytest.mark.parametrize("field,value", [
    ("policy_version", "wrong"), ("evidence", None), ("decision", None),
])
def test_malformed_input(field, value):
    r = evaluate_predictive_alert(current().model_copy(update={field: value}))
    assert r.status == AlertStatus.INVALID_INPUT and r.next_checkpoint is None


@pytest.mark.parametrize("value", [None, {}, "wrong"])
def test_non_model_input(value):
    assert evaluate_predictive_alert(value).status == AlertStatus.INVALID_INPUT


def test_decision_evidence_pair_mismatch():
    data = current().model_copy(update={"evidence": current("later").evidence})
    assert evaluate_predictive_alert(data).reasons == (AlertReason.PAIR_MISMATCH,)


def test_generation_pair_mismatch():
    data = current()
    a = data.evidence.model_copy(update={"provenance": data.evidence.provenance.model_copy(
        update={"generated_at": NOW-timedelta(seconds=1)})})
    assert evaluate_predictive_alert(data.model_copy(update={"evidence": a})).reasons == (AlertReason.GENERATION_MISMATCH,)


@pytest.mark.parametrize("field,updates", [
    ("historical_error", {"mae": 99}),
    ("sample_evidence", {"history_observations": 999}),
    ("provenance", {"methodology_supported": False}),
    ("decision_margin", {"error_multiplier": Decimal("2")}),
])
def test_inconsistent_copied_evidence(field, updates):
    data = current()
    a = data.evidence.model_copy(update={field: getattr(data.evidence, field).model_copy(update=updates)})
    assert evaluate_predictive_alert(data.model_copy(update={"evidence": a})).status == AlertStatus.INVALID_INPUT


def test_unavailable_evidence_cannot_emit_and_missing_pair_is_invalid():
    data = current(previous=checkpoint("blocked"))
    a = data.evidence.model_copy(update={"historical_evidence_status": HistoricalEvidenceStatus.UNAVAILABLE})
    r = evaluate_predictive_alert(data.model_copy(update={"evidence": a}))
    assert r.status == AlertStatus.SUPPRESS and r.signal_identity is None
    assert evaluate_predictive_alert(data.model_copy(update={"evidence": None})).status == AlertStatus.INVALID_INPUT


def test_reason_and_limitation_order_is_preserved():
    data = current(model_name="unsupported")
    results = [evaluate_predictive_alert(data) for _ in range(10)]
    assert all(r.reasons == results[0].reasons for r in results)
    assert all(r.evidence.factors == data.evidence.factors for r in results)
    assert all(r.evidence.assessment_limitations == data.evidence.assessment_limitations for r in results)


def test_naive_generation_is_invalid():
    data = current()
    r = data.decision
    f = r.forecast_identity.model_copy(update={"generated_at": NOW.replace(tzinfo=None)})
    state = r.input_snapshot.current_state.model_copy(update={"latest_forecast_generated_at": f.generated_at})
    r = r.model_copy(update={"forecast_identity": f, "input_snapshot": r.input_snapshot.model_copy(update={"forecast": f, "current_state": state})})
    a = data.evidence.model_copy(update={"decision_result": r, "current_state": state,
        "provenance": data.evidence.provenance.model_copy(update={"generated_at": f.generated_at})})
    assert evaluate_predictive_alert(data.model_copy(update={"decision": r, "evidence": a})).status == AlertStatus.INVALID_INPUT


@pytest.mark.parametrize("field,value", [
    ("policy_version", "old-policy"), ("state_fingerprint", "a"*64),
    ("accepted_checkpoint_token", "b"*64), ("previous_token", "c"*64),
    ("accepted_checkpoint_token", "malformed"),
])
def test_malformed_previous_checkpoint(field, value):
    old = checkpoint("blocked").model_copy(update={field: value})
    assert evaluate_predictive_alert(current(previous=old)).status == AlertStatus.INVALID_INPUT


def test_checkpoint_state_cannot_be_changed_without_rehash():
    old = checkpoint("earlier")
    corrupted = old.model_copy(update={"state": old.state.model_copy(update={"decision": Decision.CONSIDER_LATER_BOOKING})})
    assert evaluate_predictive_alert(current(previous=corrupted)).status == AlertStatus.INVALID_INPUT


@pytest.mark.parametrize("updates", [
    {"effective_live_decision_eligible": False}, {"forecast_superseded": True},
    {"current_input_freshness": "stale"},
    {"context_state": "superseded"},
    {"latest_forecast_generated_at": NOW-timedelta(seconds=1)},
])
def test_contradictory_directional_state_fails_closed(updates):
    data = current()
    state = data.decision.input_snapshot.current_state.model_copy(update=updates)
    r = data.decision.model_copy(update={"input_snapshot": data.decision.input_snapshot.model_copy(update={"current_state": state})})
    a = data.evidence.model_copy(update={"decision_result": r, "current_state": state})
    assert evaluate_predictive_alert(data.model_copy(update={"decision": r, "evidence": a})).status == AlertStatus.INVALID_INPUT


def test_impossible_outcome_and_movement():
    for updates in ({"actionable": False}, {"movement": Movement.DECREASE}):
        data = current()
        r = data.decision.model_copy(update=updates)
        a = data.evidence.model_copy(update={"decision_result": r})
        assert evaluate_predictive_alert(data.model_copy(update={"decision": r, "evidence": a})).status == AlertStatus.INVALID_INPUT


def test_canonical_unicode_escaping_and_order():
    assert _digest({"b": "航运\n\\\"", "a": "é"}) == _digest({"a": "é", "b": "航运\n\\\""})
    assert _digest({"a": "x|y", "b": "z"}) != _digest({"a": "x", "b": "y|z"})
    assert _digest({"a": "é"}) != _digest({"a": "e\u0301"})
    series = current().series.model_copy(update={"trade_lane": "航运\n\\\""})
    data = current(previous=checkpoint("blocked", series=series), series=series)
    assert evaluate_predictive_alert(data) == evaluate_predictive_alert(data)


def test_policy_and_chain_separation():
    series = current().series
    h = "a"*64
    assert len({_token(series, h, None), _token(series, h, "b"*64),
                _token(series, h, None, "future-policy")}) == 3


def test_incidental_evaluation_time_does_not_change_identity():
    data = current(previous=checkpoint("blocked"))
    r = data.decision
    now = NOW+timedelta(seconds=10)
    state = r.input_snapshot.current_state.model_copy(update={"evaluated_at": now})
    r = r.model_copy(update={"evaluated_at": now, "input_snapshot": r.input_snapshot.model_copy(update={"current_state": state})})
    a = data.evidence.model_copy(update={"evaluated_at": now, "decision_result": r, "current_state": state})
    first = evaluate_predictive_alert(data)
    later = evaluate_predictive_alert(data.model_copy(update={"decision": r, "evidence": a}))
    assert first.signal_identity == later.signal_identity
    assert first.next_checkpoint == later.next_checkpoint
    assert first.evidence != later.evidence  # Lossless supplied timestamps remain visible.


def test_nested_frozen_and_forbidden_fields():
    data = current()
    r = evaluate_predictive_alert(data)
    for model, field, value in (
        (data, "policy_version", "invalid"), (data.series, "source", "changed"),
        (r, "status", AlertStatus.EMIT), (r.next_checkpoint, "previous_token", "a"*64),
        (r.next_checkpoint.state, "actionable", False), (r.evidence, "factors", ()),
        (r.evidence.decision_result.policy, "min_evaluation_points", 0)):
        with pytest.raises(ValueError):
            setattr(model, field, value)
    assert isinstance(r.reasons, tuple) and isinstance(r.evidence.factors, tuple)
    fields = set(PredictiveAlertInput.model_fields) | set(PredictiveAlertResult.model_fields) | set(AlertCheckpoint.model_fields)
    assert not fields & {"confidence", "probability", "score", "severity", "interval", "savings"}


@pytest.mark.parametrize("seed,locale", [("0", "C"), ("1", "en_US.UTF-8"), ("8675309", "C")])
def test_pure_import_and_evaluation_in_fresh_process(seed, locale):
    payload = current(previous=checkpoint("blocked")).model_dump_json()
    script = '''
import builtins, json, sys
original = builtins.__import__
forbidden = ('sqlalchemy', 'redis', 'celery', 'fastapi', 'openai', 'azure', 'requests', 'httpx')
def guarded(name, *args, **kwargs):
    if name.split('.')[0] in forbidden:
        raise AssertionError('infrastructure import: ' + name)
    return original(name, *args, **kwargs)
builtins.__import__ = guarded
from app.schemas.predictive_alert import PredictiveAlertInput
from app.services.predictive_alert_evaluator import evaluate_predictive_alert
import socket, time, os, io, subprocess, random, uuid
data = PredictiveAlertInput.model_validate_json(sys.stdin.read())
def denied(*args, **kwargs):
    raise AssertionError('forbidden runtime access')
socket.socket = denied
socket.create_connection = denied
time.time = denied
time.monotonic = denied
builtins.open = io.open = os.open = denied
os.getenv = denied
class NoEnvironment(dict):
    __getitem__ = get = __iter__ = __contains__ = denied
os.environ = NoEnvironment()
subprocess.Popen = subprocess.run = denied
random.random = random.randrange = random.randint = random.choice = denied
os.urandom = uuid.uuid4 = denied
def guard_clock(frame, event, arg):
    if event == 'c_call' and getattr(arg, '__name__', '') in ('now', 'today', 'utcnow'):
        denied()
sys.setprofile(guard_clock)
first = evaluate_predictive_alert(data)
assert first.status.value == 'EMIT'
assert all(evaluate_predictive_alert(data) == first for _ in range(20))
sys.setprofile(None)
print(first.model_dump_json())
'''
    env = {key: value for key, value in os.environ.items()
           if not any(part in key.upper() for part in ("DATABASE", "REDIS", "AZURE", "OPENAI", "API_KEY"))}
    env.update(PYTHONHASHSEED=seed, LC_ALL=locale)
    run = subprocess.run([sys.executable, "-c", script], input=payload, text=True,
                         capture_output=True, env=env, cwd=Path(__file__).resolve().parents[1])
    assert run.returncode == 0, run.stderr
    assert json.loads(run.stdout) == json.loads(evaluate_predictive_alert(
        current(previous=checkpoint("blocked"))).model_dump_json())


@pytest.mark.parametrize("kind", ["earlier", "later", "monitor", "blocked", "unavailable", "unsupported"])
def test_accepted_exact_state_does_not_advance_chain(kind):
    old = checkpoint(kind)
    result = evaluate_predictive_alert(current(kind, old))
    assert result.status == AlertStatus.SUPPRESS
    assert result.next_checkpoint == old
    assert result.signal_identity is None


@pytest.mark.parametrize("old,new,transition", [
    ("blocked", "earlier", Transition.DIRECTIONAL_ENTERED),
    ("earlier", "later", Transition.DIRECTION_REVERSED),
    ("earlier", "blocked", Transition.ACTIONABILITY_WITHDRAWN),
])
def test_retry_before_and_after_acceptance(old, new, transition):
    data = current(new, checkpoint(old))
    first = evaluate_predictive_alert(data)
    assert first.transition == transition
    assert first == evaluate_predictive_alert(data)
    accepted = first.next_checkpoint
    retried = evaluate_predictive_alert(current(new, accepted))
    assert retried.status == AlertStatus.SUPPRESS
    assert retried.next_checkpoint == accepted
    assert retried.signal_identity is None


@pytest.mark.parametrize("kind", ["earlier", "later", "monitor", "blocked"])
def test_changed_generation_advances_once_without_noise(kind):
    old = checkpoint(kind)
    fields = {"generated_at": NOW+timedelta(microseconds=1)}
    new = evaluate_predictive_alert(current(kind, old, **fields))
    assert new.status == AlertStatus.SUPPRESS
    assert new.next_checkpoint.accepted_checkpoint_token != old.accepted_checkpoint_token
    assert evaluate_predictive_alert(current(kind, new.next_checkpoint, **fields)).next_checkpoint == new.next_checkpoint


@pytest.mark.parametrize("amount", ["103", "103.0", "103.00", "1.03E2"])
def test_decimal_format_is_not_semantic_evidence_change(amount):
    old = checkpoint("earlier", predicted_rate=Decimal("103"))
    result = evaluate_predictive_alert(current("earlier", old, predicted_rate=Decimal(amount)))
    assert result.status == AlertStatus.SUPPRESS
    assert result.next_checkpoint == old


@pytest.mark.parametrize("values", [
    (Decimal("1"), Decimal("1.00")),
    (Decimal("0"), Decimal("-0.000")),
    (Decimal("1E+999"), Decimal("10E+998")),
    (0.0, -0.0),
])
def test_equivalent_numeric_encoding(values):
    assert _digest({"value": values[0]}) == _digest({"value": values[1]})


@pytest.mark.parametrize("identifier", ["\x00\x01", "\u200b", "\t\x00\n"])
def test_control_only_series_is_invalid(identifier):
    series = current().series.model_copy(update={"source": identifier})
    result = evaluate_predictive_alert(current(series=series))
    assert result.status == AlertStatus.INVALID_INPUT
    assert result.next_checkpoint is None and result.signal_identity is None


def test_naive_incidental_timestamps_still_fail_closed():
    data = current()
    r = data.decision
    naive = NOW.replace(tzinfo=None)
    state = r.input_snapshot.current_state.model_copy(update={"evaluated_at": naive})
    r = r.model_copy(update={"evaluated_at": naive,
        "input_snapshot": r.input_snapshot.model_copy(update={"current_state": state})})
    a = data.evidence.model_copy(update={"evaluated_at": naive, "decision_result": r, "current_state": state})
    result = evaluate_predictive_alert(data.model_copy(update={"decision": r, "evidence": a}))
    assert result.status == AlertStatus.INVALID_INPUT and result.next_checkpoint is None


def test_checkpoint_impossible_status_is_rejected_even_if_rehashed():
    old = checkpoint("blocked")
    state = old.state.model_copy(update={"decision_evidence_status": DecisionEvidenceStatus.DIRECTIONAL_RULES_PASSED})
    fingerprint = _digest(state)
    corrupted = old.model_copy(update={"state": state, "state_fingerprint": fingerprint,
        "accepted_checkpoint_token": _token(old.series, fingerprint, old.previous_token)})
    assert evaluate_predictive_alert(current(previous=corrupted)).status == AlertStatus.INVALID_INPUT


def test_timezone_equivalence_and_generation_uuid_change():
    old = checkpoint("earlier")
    offset = NOW.astimezone(timezone(timedelta(hours=5, minutes=30)))
    equivalent = evaluate_predictive_alert(current("earlier", old, generated_at=offset))
    assert equivalent.next_checkpoint == old
    changed = evaluate_predictive_alert(current("earlier", old, forecast_id=UUID(int=2)))
    assert changed.status == AlertStatus.SUPPRESS
    assert changed.next_checkpoint.state_fingerprint != old.state_fingerprint


@pytest.mark.parametrize("kind", ["blocked", "monitor"])
def test_non_actionable_evidence_change_advances_once(kind):
    old = checkpoint(kind)
    new = evaluate_predictive_alert(current(kind, old, backtest_mae=2))
    assert new.status == AlertStatus.SUPPRESS and new.signal_identity is None
    assert new.next_checkpoint.accepted_checkpoint_token != old.accepted_checkpoint_token
    assert evaluate_predictive_alert(current(kind, new.next_checkpoint, backtest_mae=2)).next_checkpoint == new.next_checkpoint


@pytest.mark.parametrize("cycle", [
    ("earlier", "blocked", "earlier"), ("later", "monitor", "later"),
    ("earlier", "later", "earlier"), ("earlier", "blocked", "later"),
])
def test_multiple_recurring_cycles_remain_distinguishable(cycle):
    previous = checkpoint("unavailable")
    signals = []
    tokens = []
    for kind in cycle*3:
        r = evaluate_predictive_alert(current(kind, previous))
        if r.status == AlertStatus.EMIT:
            signals.append(r.signal_identity)
        if r.next_checkpoint != previous:
            tokens.append(r.next_checkpoint.accepted_checkpoint_token)
        previous = r.next_checkpoint
    assert len(signals) >= 7 and len(set(signals)) == len(signals)
    assert len(set(tokens)) == len(tokens)


def test_intermediate_accepted_evidence_changes_chain():
    a = checkpoint("earlier")
    b = evaluate_predictive_alert(current("blocked", a)).next_checkpoint
    via_b = evaluate_predictive_alert(current("later", b))
    direct = evaluate_predictive_alert(current("later", a))
    assert via_b.next_checkpoint.state_fingerprint == direct.next_checkpoint.state_fingerprint
    assert via_b.next_checkpoint.accepted_checkpoint_token != direct.next_checkpoint.accepted_checkpoint_token
    assert via_b.signal_identity != direct.signal_identity


@pytest.mark.parametrize("text", [":|,", "\"\\\n\t", "🚢航运", "é", "e\u0301", "ЅCFI"])
def test_adversarial_series_text_is_exact_and_unambiguous(text):
    series = current().series.model_copy(update={"source": text})
    r = evaluate_predictive_alert(current(series=series))
    assert r.status == AlertStatus.BASELINE_ONLY and r.next_checkpoint.series == series
    other = current().series.model_copy(update={"trade_lane": text})
    assert checkpoint("earlier", series=other).accepted_checkpoint_token != r.next_checkpoint.accepted_checkpoint_token


@pytest.mark.parametrize("updates", [
    {"category": SignalCategory.OPERATIONAL}, {"status": AlertStatus.SUPPRESS},
    {"signal_identity": None}, {"evidence": None},
])
def test_result_invariant_validation(updates):
    r = evaluate_predictive_alert(current(previous=checkpoint("blocked")))
    data = r.model_dump(mode="python")
    data.update(updates)
    with pytest.raises(ValueError):
        PredictiveAlertResult.model_validate(data)


@pytest.mark.parametrize("fields,state", [
    ({"stored_live_decision_eligible": False}, None),
    ({}, {"current_input_freshness": "stale"}),
    ({}, {"source_superseded": True}),
    ({}, {"forecast_superseded": True}),
])
def test_initial_unsafe_state_is_baseline_without_signal(fields, state):
    r = evaluate_predictive_alert(current(state=state, **fields))
    assert r.status == AlertStatus.BASELINE_ONLY and r.next_checkpoint is not None
    assert r.signal_identity is None and r.category is None


def test_nonfinite_t09_descriptive_numbers_are_invalid():
    data = current(backtest_mae=float("inf"))
    a = data.evidence.model_copy(update={"historical_error": data.evidence.historical_error.model_copy(update={"mae": float("inf")})})
    result = evaluate_predictive_alert(data.model_copy(update={"evidence": a}))
    assert result.status == AlertStatus.INVALID_INPUT
    assert result.signal_identity is None and result.next_checkpoint is None


def test_bypassed_boolean_types_are_not_silently_repaired():
    data = current()
    r = data.decision.model_copy(update={"actionable": 1})
    a = data.evidence.model_copy(update={"decision_result": r})
    result = evaluate_predictive_alert(data.model_copy(update={"decision": r, "evidence": a}))
    assert result.status == AlertStatus.INVALID_INPUT


@pytest.mark.parametrize("missing", ["decision", "series", "evidence"])
def test_missing_constructed_input_fields_fail_closed(missing):
    values = {key: value for key, value in current().__dict__.items() if key != missing}
    data = PredictiveAlertInput.model_construct(**values)
    result = evaluate_predictive_alert(data)
    assert result.status == AlertStatus.INVALID_INPUT
    assert result.signal_identity is None and result.next_checkpoint is None


def test_unrepresentable_utc_generation_fails_closed():
    instant = datetime.max.replace(tzinfo=timezone(timedelta(hours=-1)))
    result = evaluate_predictive_alert(current(generated_at=instant))
    assert result.status == AlertStatus.INVALID_INPUT
    assert result.signal_identity is None and result.next_checkpoint is None


@pytest.mark.parametrize("field,updates", [
    ("sample_evidence", {"history_observations": 1}),
    ("historical_error", {"mae": 1.0}),
    ("directional_evidence", {"directional_accuracy": 50.0}),
])
def test_absent_forecast_cannot_have_copied_historical_evidence(field, updates):
    data = current("unavailable")
    a = data.evidence.model_copy(update={field: getattr(data.evidence, field).model_copy(update=updates)})
    result = evaluate_predictive_alert(data.model_copy(update={"evidence": a}))
    assert result.status == AlertStatus.INVALID_INPUT
    assert result.signal_identity is None and result.next_checkpoint is None


@pytest.mark.parametrize("location", ["provenance", "winner_generation", "evidence_decision"])
def test_dst_fold_does_not_hide_distinct_generation_instants(location):
    first = datetime(2026, 11, 1, 1, 30, tzinfo=ZoneInfo("America/New_York"), fold=0)
    second = first.replace(fold=1)
    assert first == second  # Python wall-time equality hides this distinction.
    assert first.astimezone(timezone.utc) != second.astimezone(timezone.utc)
    data = current(generated_at=first)
    r, a = data.decision, data.evidence
    if location == "provenance":
        a = a.model_copy(update={"provenance": a.provenance.model_copy(update={"generated_at": second})})
    elif location == "winner_generation":
        state = r.input_snapshot.current_state.model_copy(update={"latest_forecast_generated_at": second})
        r = r.model_copy(update={"input_snapshot": r.input_snapshot.model_copy(update={"current_state": state})})
        a = a.model_copy(update={"decision_result": r, "current_state": state})
    else:
        different = current(generated_at=second).decision
        a = a.model_copy(update={"decision_result": different})
    result = evaluate_predictive_alert(data.model_copy(update={"decision": r, "evidence": a}))
    assert result.status == AlertStatus.INVALID_INPUT
    assert result.next_checkpoint is None and result.signal_identity is None
