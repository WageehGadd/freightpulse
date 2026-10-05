"""Synthetic evidence only; no fixture asserts live market/provider truth."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, localcontext
from enum import IntEnum
from pathlib import Path
from uuid import UUID
import ast
import json
import os
import subprocess
import sys
import pytest
from pydantic import ValidationError
from app.schemas.decision import DecisionInput, ForecastSnapshot, ForecastState, SeriesIdentity, DecisionPolicy
from app.schemas.route_intelligence import (
    MarketSeries, RouteEvidenceRequest, AdvisorySnapshot, ProvenanceClass, Availability,
)
from app.services import route_intelligence as core
from app.services.decision_engine import evaluate_decision
from app.services.reliability import assess_evidence

NOW = datetime(2026, 1, 2, tzinfo=timezone.utc)
SERIES = MarketSeries(source="SCFI", trade_lane="Synthetic-Lane", container_type="40ft")


def factual(**updates):
    identity = SeriesIdentity(**SERIES.model_dump())
    f = ForecastSnapshot(forecast_id=UUID(int=1), series=identity,
        forecast_for_date=NOW.date(), predicted_rate=Decimal("103"), model_name="MA(3)",
        model_version="baseline-v1-decimal", forecast_horizon=1,
        latest_observation_date=(NOW-timedelta(days=1)).date(), latest_actual_rate=Decimal("100"),
        history_observations=100, evaluation_points=30, backtest_mae=1.0, backtest_rmse=2.0,
        backtest_smape=2.0, backtest_directional_accuracy=50.0, data_readiness="BASELINE_READY",
        input_freshness_at_generation="fresh", stored_live_decision_eligible=True,
        warning=None, generated_at=NOW)
    f = f.model_copy(update=updates)
    s = ForecastState(series=identity, evaluated_at=NOW, latest_source_date=f.latest_observation_date,
        latest_forecast_id=f.forecast_id, latest_forecast_generated_at=f.generated_at,
        series_matches=True, source_superseded=False, forecast_superseded=False,
        current_input_freshness="fresh", stored_live_decision_eligible=f.stored_live_decision_eligible,
        effective_live_decision_eligible=f.stored_live_decision_eligible,
        context_state="current", context_warning=None)
    return DecisionInput(forecast=f, current_state=s)


def request(data=None, **kwargs):
    return RouteEvidenceRequest(series=SERIES, evaluated_at=NOW, decision_input=data, **kwargs)


def advisory(**kwargs):
    return AdvisorySnapshot(record_id="synthetic-record", carrier="Synthetic Carrier", series=SERIES,
        classification=ProvenanceClass.VERIFIED_SOURCE_DATA, source_url="https://example.test/advisory",
        source_text="Synthetic source text", published_at=NOW-timedelta(hours=1), **kwargs)


def test_absence_and_operational_gaps():
    r = core.compose_route_evidence(request())
    assert r.decision is r.assessment is None
    for status in (r.forecast_status, r.decision_status, r.assessment_status, r.advisory_status):
        assert status.availability == Availability.UNAVAILABLE
    assert "unknown" in r.advisory_status.reason
    assert all(v.availability == Availability.UNAVAILABLE for v in r.operational.__dict__.values())
    assert "Trade-lane evidence is not a physical-route model." in r.limitations
    assert not any(k in r.model_dump() for k in ("risk", "distance", "ETA", "actionable", "score"))


def test_authoritative_parity_and_call_counts(monkeypatch):
    data = factual()
    expected = evaluate_decision(data, DecisionPolicy(), NOW)
    counts = [0, 0]
    def decision(*args):
        counts[0] += 1
        return evaluate_decision(*args)
    def assessment(*args):
        counts[1] += 1
        return assess_evidence(*args)
    monkeypatch.setattr(core, "evaluate_decision", decision)
    monkeypatch.setattr(core, "assess_evidence", assessment)
    r = core.compose_route_evidence(request(data))
    assert r.decision == expected and r.assessment == assess_evidence(expected)
    assert counts == [1, 1]
    core.compose_route_evidence(request())
    assert counts == [1, 1]


@pytest.mark.parametrize("field", ["source", "trade_lane", "container_type"])
@pytest.mark.parametrize("target", ["forecast", "current_state", "advisory"])
def test_exact_series_mismatch(field, target):
    altered = SERIES.model_copy(update={field: SERIES.__dict__[field] + " "})
    if target == "advisory":
        req = request(advisories=(advisory().model_copy(update={"series": altered}),))
    else:
        data = factual()
        nested = getattr(data, target).model_copy(update={"series": SeriesIdentity(**altered.model_dump())})
        req = request(data.model_copy(update={target: nested}))
    with pytest.raises(core.RouteEvidenceInputError):
        core.compose_route_evidence(req)


@pytest.mark.parametrize("value", ["", " ", "\t", "\x00", "a\nb"])
def test_invalid_identity(value):
    with pytest.raises(ValidationError):
        MarketSeries(source=value, trade_lane="L", container_type="40ft")


def test_exact_printable_identity_preserved():
    s = MarketSeries(source=" SCFI ", trade_lane="Lé", container_type="40FT")
    assert core.compose_route_evidence(RouteEvidenceRequest(series=s, evaluated_at=NOW)).series == s


@pytest.mark.parametrize("classification", list(ProvenanceClass))
def test_advisory_qualification_and_no_decision_effect(classification):
    a = advisory().model_copy(update={"classification": classification})
    r = core.compose_route_evidence(request(factual(), advisories=(a,)))
    expected = Availability.AVAILABLE if classification == ProvenanceClass.VERIFIED_SOURCE_DATA else Availability.EXCLUDED_UNVERIFIED
    assert r.advisories[0].status.availability == expected
    baseline = core.compose_route_evidence(request(factual()))
    assert r.decision == baseline.decision and r.assessment == baseline.assessment


@pytest.mark.parametrize("field", ["series", "source_url", "source_text"])
def test_missing_advisory_provenance(field):
    a = advisory().model_copy(update={field: None})
    assert core.compose_route_evidence(request(advisories=(a,))).advisory_status.availability == Availability.EXCLUDED_UNVERIFIED


def test_conflict_and_order():
    a = advisory()
    b = a.model_copy(update={"source_text": "Different synthetic source text"})
    first = core.compose_route_evidence(request(advisories=(a,b)))
    second = core.compose_route_evidence(request(advisories=(b,a)))
    assert first == second and len(first.advisory_conflicts) == 1
    assert len(first.advisories) == 2


@pytest.mark.parametrize("extra", ["decision_result", "evidence_assessment", "confidence", "probability",
    "risk", "score", "recommendation", "best_route", "ETA", "distance", "port_congestion", "scenario_result",
    "predicted_rate_override", "policy", "movement_threshold", "MAE_multiplier", "freshness_override", "eligibility_override"])
def test_extra_request_rejected(extra):
    with pytest.raises(ValidationError):
        RouteEvidenceRequest(**{**request().model_dump(), extra: 1})
    with pytest.raises(core.RouteEvidenceInputError):
        core.compose_route_evidence(request().model_copy(update={extra: 1}))


@pytest.mark.parametrize("field,value", [
    ("forecast_horizon", True), ("history_observations", "100"), ("evaluation_points", 30.0),
    ("backtest_mae", True), ("backtest_rmse", "2"), ("stored_live_decision_eligible", 1),
    ("predicted_rate", 103.0), ("latest_observation_date", NOW), ("generated_at", NOW.replace(tzinfo=None)),
    ("model_name", 3),
])
def test_unsafe_nested_primitives(field,value):
    with pytest.raises(core.RouteEvidenceInputError):
        core.compose_route_evidence(request(factual(**{field:value})))


def test_construct_missing_extra_subclass_and_mapping():
    cases = [RouteEvidenceRequest.model_construct(series=SERIES), request().model_copy(update={"advisories": []}),
             request().model_copy(update={"decision_input": factual().model_dump()})]
    data = factual()
    del data.forecast.__dict__["warning"]
    cases.append(request(data))
    data = factual()
    data.forecast.__dict__["scenario_rate"] = Decimal("999")
    cases.append(request(data))
    for req in cases:
        with pytest.raises(core.RouteEvidenceInputError):
            core.compose_route_evidence(req)
    with pytest.raises(core.RouteEvidenceInputError):
        core.compose_route_evidence(request().model_dump())
    class Horizon(IntEnum):
        ONE = 1
    with pytest.raises(core.RouteEvidenceInputError):
        core.compose_route_evidence(request(factual(forecast_horizon=Horizon.ONE)))


@pytest.mark.parametrize("field", ["published_at", "observed_at"])
def test_future_advisory(field):
    with pytest.raises(core.RouteEvidenceInputError):
        core.compose_route_evidence(request(advisories=(advisory().model_copy(update={field: NOW+timedelta(seconds=1)}),)))


def test_future_effective_is_scheduled_context_not_expired():
    a = advisory(source_effective_at=NOW+timedelta(days=3))
    assert core.compose_route_evidence(request(advisories=(a,))).advisories[0].snapshot.source_effective_at == a.source_effective_at


@pytest.mark.parametrize("case", ["naive", "future_generation", "state_time", "eligibility"])
def test_temporal_and_lineage_rejection(case):
    data = factual()
    req = request(data)
    if case == "naive":
        req = req.model_copy(update={"evaluated_at": NOW.replace(tzinfo=None)})
    elif case == "future_generation":
        req = request(factual(generated_at=NOW+timedelta(seconds=1)))
    elif case == "state_time":
        req = request(data.model_copy(update={"current_state": data.current_state.model_copy(update={"evaluated_at": NOW-timedelta(seconds=1)})}))
    else:
        req = request(data.model_copy(update={"current_state": data.current_state.model_copy(update={"stored_live_decision_eligible": False})}))
    with pytest.raises(core.RouteEvidenceInputError):
        core.compose_route_evidence(req)


def test_stale_source_not_refreshed_by_generation():
    data = factual(input_freshness_at_generation="stale")
    data = data.model_copy(update={"current_state": data.current_state.model_copy(update={"current_input_freshness": "stale"})})
    r = core.compose_route_evidence(request(data))
    assert not r.decision.actionable
    assert r.decision == evaluate_decision(data, DecisionPolicy(), NOW)


def test_timezone_decimal_equivalence_and_ambient_context():
    first = core.compose_route_evidence(request(factual(predicted_rate=Decimal("103.000"))))
    data = factual()
    zone = timezone(timedelta(hours=3))
    data = data.model_copy(update={"forecast": data.forecast.model_copy(update={"generated_at": NOW.astimezone(zone)}),
        "current_state": data.current_state.model_copy(update={"evaluated_at": NOW.astimezone(zone), "latest_forecast_generated_at": NOW.astimezone(zone)})})
    with localcontext() as ctx:
        ctx.prec = 2
        second = core.compose_route_evidence(request(data).model_copy(update={"evaluated_at": NOW.astimezone(zone)}))
        assert ctx.prec == 2
    assert first.fingerprint == second.fingerprint
    assert second.decision.forecast_identity.predicted_rate == Decimal("103")


@pytest.mark.parametrize("field,value", [("warning","Synthetic warning"), ("predicted_rate",Decimal("104")),
    ("history_observations",101), ("model_name","MA(4)"), ("backtest_mae",1.1)])
def test_factual_fingerprint_mutations(field,value):
    assert core.compose_route_evidence(request(factual())).fingerprint != core.compose_route_evidence(request(factual(**{field:value}))).fingerprint


@pytest.mark.parametrize("field,value", [("record_id","other"), ("source_url","https://example.test/other"),
    ("classification",ProvenanceClass.SEEDED_DEMO_DATA), ("published_at",NOW-timedelta(hours=2)),
    ("derived_summary","Synthetic interpretation"), ("source_text","Other synthetic text")])
def test_advisory_fingerprint_mutations(field,value):
    a = advisory()
    assert core.compose_route_evidence(request(advisories=(a,))).fingerprint != core.compose_route_evidence(request(advisories=(a.model_copy(update={field:value}),))).fingerprint


def test_presence_time_generation_and_series_fingerprints():
    baseline = core.compose_route_evidence(request())
    variants = [request(factual()), request().model_copy(update={"evaluated_at":NOW+timedelta(seconds=1)}),
                request().model_copy(update={"series":SERIES.model_copy(update={"source":"Other"})})]
    assert all(core.compose_route_evidence(v).fingerprint != baseline.fingerprint for v in variants)
    data = factual(generated_at=NOW-timedelta(seconds=1))
    assert core.compose_route_evidence(request(data)).fingerprint != core.compose_route_evidence(request(factual())).fingerprint


def test_immutability():
    r = core.compose_route_evidence(request(factual(), advisories=(advisory(),)))
    for obj, field, value in [(r,"fingerprint","x"),(r.series,"source","x"),
        (r.decision.signals,"absolute_change",Decimal(0)),(r.advisories[0].snapshot,"source_text","x")]:
        with pytest.raises(ValidationError):
            setattr(obj,field,value)
    assert type(r.advisories) is tuple and type(r.limitations) is tuple


def test_cross_process_host_independence():
    script = '''from datetime import datetime, timezone
from app.schemas.route_intelligence import MarketSeries, RouteEvidenceRequest
from app.services.route_intelligence import compose_route_evidence
r=compose_route_evidence(RouteEvidenceRequest(series=MarketSeries(source="S",trade_lane="L",container_type="40ft"),evaluated_at=datetime(2026,1,2,tzinfo=timezone.utc)))
print(r.fingerprint)'''
    outputs = []
    for seed,zone in [("1","UTC"),("91","Asia/Tokyo")]:
        env = {**os.environ, "PYTHONHASHSEED":seed,"TZ":zone,"LC_ALL":"C","T18_UNUSED":"different"+seed}
        outputs.append(subprocess.check_output([sys.executable,"-c",script],env=env,text=True).strip())
    assert outputs[0] == outputs[1]


def test_import_isolation_and_no_shadow_rules():
    forbidden = ("sqlalchemy","redis","celery","fastapi","socket","subprocess","random","os", "pathlib",
                 "openai","azure","predictive_alert","scenario_intelligence","route_brief","forecast_evaluation")
    for module in ("app/schemas/route_intelligence.py","app/services/route_intelligence.py"):
        text = Path(module).read_text()
        tree = ast.parse(text)
        imports = [n.module or "" for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]
        imports += [a.name for n in ast.walk(tree) if isinstance(n,ast.Import) for a in n.names]
        assert not any(any(part in name.split(".") for part in forbidden) for name in imports)
        assert not any(token in text for token in ("datetime.now", "utcnow", "getenv", "Decimal(float", "min_history_observations", "movement_threshold_pct"))


def test_actual_scenario_result_not_accepted():
    from app.schemas.scenario import ScenarioResult
    fake = ScenarioResult.model_construct()
    with pytest.raises(core.RouteEvidenceInputError):
        core.compose_route_evidence(request().model_copy(update={"decision_input": fake}))


@pytest.mark.parametrize("field,value", [("predicted_rate",None),("backtest_mae",None),
    ("backtest_mae",float("nan")),("backtest_rmse",float("inf")),("predicted_rate",Decimal("NaN")),
    ("predicted_rate",Decimal("Infinity")),("history_observations",-1),
    ("stored_live_decision_eligible",False),("forecast_horizon",2)])
def test_valid_deficient_evidence_preserves_authoritative_blockers(field,value):
    data=factual(**{field:value})
    expected=evaluate_decision(data,DecisionPolicy(),NOW)
    result=core.compose_route_evidence(request(data))
    assert result.decision.decision == expected.decision
    assert result.decision.reasons == expected.reasons
    assert not result.decision.actionable
    assert len(result.fingerprint)==64


@pytest.mark.parametrize("field", ["series", "evaluated_at", "decision_input", "advisories"])
def test_missing_request_field_even_defaulted(field):
    req=request()
    del req.__dict__[field]
    with pytest.raises(core.RouteEvidenceInputError):
        core.compose_route_evidence(req)


@pytest.mark.parametrize("field", ["published_at","observed_at","source_effective_at","derived_effective_at"])
def test_advisory_naive_datetime(field):
    with pytest.raises(core.RouteEvidenceInputError):
        core.compose_route_evidence(request(advisories=(advisory().model_copy(update={field:NOW.replace(tzinfo=None)}),)))


def test_policy_and_methodology_are_fingerprinted_without_request_overrides(monkeypatch):
    original=core.compose_route_evidence(request(factual()))
    def alternative_policy():
        return DecisionPolicy(movement_threshold_pct=Decimal("4"))
    monkeypatch.setattr(core,"DecisionPolicy",alternative_policy)
    changed=core.compose_route_evidence(request(factual()))
    assert original.fingerprint != changed.fingerprint
    assert changed.decision.policy.movement_threshold_pct==Decimal("4")


def test_no_io_clock_environment_or_random_during_composition(monkeypatch):
    import builtins
    import socket
    import random
    def fail(*args,**kwargs):
        raise AssertionError("Infrastructure access")
    req=request(factual(),advisories=(advisory(),))
    monkeypatch.setattr(builtins,"open",fail)
    monkeypatch.setattr(socket,"socket",fail)
    monkeypatch.setattr(os,"getenv",fail)
    monkeypatch.setattr(random,"random",fail)
    assert core.compose_route_evidence(req).decision is not None


def test_signed_zero_scale_and_advisory_timezone_canonicalization():
    a=advisory()
    shifted=a.model_copy(update={"published_at":a.published_at.astimezone(timezone(timedelta(hours=-5)))})
    first=core.compose_route_evidence(request(factual(predicted_rate=Decimal("-0.000")),advisories=(a,)))
    second=core.compose_route_evidence(request(factual(predicted_rate=Decimal("0")),advisories=(shifted,)))
    assert first.fingerprint==second.fingerprint


def test_semantic_subclasses_are_rejected():
    class ForgedRequest(RouteEvidenceRequest):
        pass
    with pytest.raises(core.RouteEvidenceInputError):
        core.compose_route_evidence(ForgedRequest(**request().model_dump()))


def test_declared_hypothetical_mapping_is_rejected():
    from app.schemas.scenario import ScenarioResult
    with pytest.raises(ValidationError):
        RouteEvidenceRequest(series=SERIES,evaluated_at=NOW,decision_input={"scenario_result":ScenarioResult.model_construct()})


def test_factual_cross_process_complete_output():
    script='''import runpy, json
from decimal import getcontext
from app.services.route_intelligence import compose_route_evidence
fixtures=runpy.run_path("tests/test_route_intelligence.py")
getcontext().prec=3
r=compose_route_evidence(fixtures["request"](fixtures["factual"](),advisories=(fixtures["advisory"](),)))
print(r.model_dump_json())'''
    results=[]
    for seed,zone in [("2","UTC"),("83","America/New_York")]:
        results.append(subprocess.check_output([sys.executable,"-c",script],env={**os.environ,
            "PYTHONHASHSEED":seed,"TZ":zone,"LC_ALL":"C"},text=True).strip())
    assert json.loads(results[0])==json.loads(results[1])


@pytest.mark.parametrize("amount", ["103.123456789012345678901234567", "0.000000000000000000000000001"])
def test_monetary_snapshot_never_rounded(amount):
    value=Decimal(amount)
    result=core.compose_route_evidence(request(factual(predicted_rate=value)))
    assert result.decision.input_snapshot.forecast.predicted_rate.as_tuple()==value.as_tuple()


# Hardening: upstream truth, semantic transport identity and complete boundaries.
def test_repackaged_hypothetical_cannot_be_authenticated():
    # Normal-shaped counterfactual input is indistinguishable here. This is a
    # documented trust limitation, not a numerical-plausibility detector.
    repackaged = factual(predicted_rate=Decimal("125"))
    r = core.compose_route_evidence(request(repackaged))
    assert r.decision == evaluate_decision(repackaged, DecisionPolicy(), NOW)
    assert any("source lineage" in note for note in r.provenance)
    assert any("hypothetical" in note for note in r.limitations)


def test_authoritative_policy_defaults_and_every_field_identity(monkeypatch):
    from app.schemas.decision import DecisionPolicy as AuthoritativePolicy
    assert core.DecisionPolicy is AuthoritativePolicy
    base = core.compose_route_evidence(request(factual()))
    changes = {"movement_threshold_pct":Decimal("3"), "min_history_observations":101,
               "min_evaluation_points":31,"error_multiplier":Decimal("2"),
               "supported_horizons":frozenset({1,2})}
    assert set(changes) == set(AuthoritativePolicy.model_fields)
    for field, value in changes.items():
        monkeypatch.setattr(core,"DecisionPolicy",lambda field=field,value=value: AuthoritativePolicy(**{field:value}))
        altered = core.compose_route_evidence(request(factual()))
        assert altered.fingerprint != base.fingerprint
        assert getattr(altered.decision.policy,field) == value


def test_failure_call_contract_and_exact_instant(monkeypatch):
    calls=[]
    def failing(data,policy,instant):
        calls.append((data,policy,instant))
        raise ValueError("Synthetic evaluator failure")
    def unexpected(*args):
        pytest.fail("T09 called after T08 failure")
    monkeypatch.setattr(core,"evaluate_decision",failing)
    monkeypatch.setattr(core,"assess_evidence",unexpected)
    with pytest.raises(core.RouteEvidenceInputError):
        core.compose_route_evidence(request(factual()))
    assert len(calls)==1 and calls[0][2]==NOW


@pytest.mark.parametrize("classification",list(ProvenanceClass))
@pytest.mark.parametrize("linked",[True,False])
@pytest.mark.parametrize("source_authored",[True,False])
@pytest.mark.parametrize("url_present",[True,False])
def test_advisory_support_full_matrix(classification,linked,source_authored,url_present):
    a=advisory().model_copy(update={"classification":classification,"series":SERIES if linked else None,
        "source_text":"Synthetic source" if source_authored else None,
        "derived_summary":None if source_authored else "Synthetic GPT interpretation",
        "source_url":"https://example.test/notice" if url_present else None})
    r=core.compose_route_evidence(request(factual(),advisories=(a,)))
    qualifies=classification==ProvenanceClass.VERIFIED_SOURCE_DATA and linked and source_authored and url_present
    assert r.advisories[0].status.availability==(Availability.AVAILABLE if qualifies else Availability.EXCLUDED_UNVERIFIED)
    assert r.decision==evaluate_decision(factual(),DecisionPolicy(),NOW)
    assert r.assessment==assess_evidence(r.decision)
    assert all(v.availability==Availability.UNAVAILABLE for v in r.operational.__dict__.values())


def test_identical_and_timezone_equivalent_advisories_deduplicate():
    a=advisory()
    equivalent=a.model_copy(update={"published_at":a.published_at.astimezone(timezone(timedelta(hours=5)))})
    original=core.compose_route_evidence(request(advisories=(a,)))
    assert core.compose_route_evidence(request(advisories=(a,a,equivalent)))==original
    assert original.advisory_conflicts==()
    distinct=a.model_copy(update={"record_id":"different-record"})
    assert len(core.compose_route_evidence(request(advisories=(a,distinct))).advisories)==2


@pytest.mark.parametrize("field,value", [("source_text","changed"),("derived_summary","changed"),
    ("classification",ProvenanceClass.UNVERIFIED),("published_at",NOW-timedelta(hours=2))])
def test_same_id_distinct_snapshots_are_not_discarded(field,value):
    a=advisory(); changed=a.model_copy(update={field:value})
    r=core.compose_route_evidence(request(advisories=(a,changed)))
    assert len(r.advisories)==2 and len(r.advisory_conflicts)==1


def test_all_advisory_permutations_semantic_identity():
    from itertools import permutations
    a=advisory()
    values=(a,a.model_copy(update={"source_text":"conflict"}),a.model_copy(update={"record_id":"second"}))
    outputs=[core.compose_route_evidence(request(advisories=order)) for order in permutations(values)]
    assert all(r==outputs[0] for r in outputs)


@pytest.mark.parametrize("extra", ["scenario_id","hypothetical","counterfactual_rate","scenario_result",
    "policy_override","brief_markdown","route_brief_id","recommendation","risk_level","ship_now","wait","reroute",
    "checkpoint_id","transition_type","signal_id","delivery_state","predictive_alert",
    "congestion_index","waiting_vessels","dwell_time","port_delay","port_risk","port_activity","PortWatch","metadata",
    "operational","availability"])
@pytest.mark.parametrize("target",["request","advisory"])
def test_cross_feature_extra_injection(extra,target):
    obj=request() if target=="request" else advisory()
    forged=obj.model_copy(update={extra:{"value":1}})
    req=forged if target=="request" else request(advisories=(forged,))
    with pytest.raises(core.RouteEvidenceInputError):
        core.compose_route_evidence(req)
    with pytest.raises(ValidationError):
        type(obj).model_validate({**obj.model_dump(),extra:1})


@pytest.mark.parametrize("value", [b"SCFI",1,1.0,True,None,object()])
def test_identity_unsafe_types(value):
    forged=SERIES.model_copy(update={"source":value})
    with pytest.raises(core.RouteEvidenceInputError):
        core.compose_route_evidence(request().model_copy(update={"series":forged}))


def test_identity_subclasses_custom_string_and_unicode_distinctions():
    class S(str): pass
    class Stringable:
        def __str__(self): return "SCFI"
    for value in (S("SCFI"),Stringable()):
        with pytest.raises(core.RouteEvidenceInputError):
            core.compose_route_evidence(request().model_copy(update={"series":SERIES.model_copy(update={"source":value})}))
    values=("SCFI","scfi"," SCFI","SCFI ","é","e\u0301","СCFI")
    results=[core.compose_route_evidence(request().model_copy(update={"series":SERIES.model_copy(update={"source":v})})) for v in values]
    assert len({r.fingerprint for r in results})==len(values)
    assert [r.series.source for r in results]==list(values)


@pytest.mark.parametrize("section",["forecast","current_state"])
def test_every_factual_field_missing_or_extra(section):
    model=getattr(factual(),section)
    for name in model.model_fields:
        data=factual(); nested=getattr(data,section)
        del nested.__dict__[name]
        with pytest.raises(core.RouteEvidenceInputError):
            core.compose_route_evidence(request(data))
    data=factual(); getattr(data,section).__dict__["metadata"]={}
    with pytest.raises(core.RouteEvidenceInputError):
        core.compose_route_evidence(request(data))


@pytest.mark.parametrize("section",["forecast","current_state"])
def test_factual_models_subclasses_and_custom_mappings(section):
    from collections import UserDict
    data=factual(); nested=getattr(data,section)
    subclass=type("Forged",(type(nested),),{})
    for value in (subclass(**nested.model_dump()),nested.model_dump(),UserDict(nested.model_dump())):
        forged=data.model_copy(update={section:value})
        with pytest.raises(core.RouteEvidenceInputError):
            core.compose_route_evidence(request(forged))


@pytest.mark.parametrize("field",list(AdvisorySnapshot.model_fields))
def test_every_advisory_field_fingerprinted(field):
    changes={"record_id":"other","carrier":"Other carrier","series":None,
        "classification":ProvenanceClass.UNVERIFIED,"source_url":"https://example.test/other",
        "source_text":"Other text","derived_summary":"Derived text","published_at":NOW-timedelta(hours=2),
        "observed_at":NOW-timedelta(hours=2),"source_effective_at":NOW+timedelta(days=2),
        "derived_effective_at":NOW+timedelta(days=3)}
    assert set(changes)==set(AdvisorySnapshot.model_fields)
    a=advisory()
    assert core.compose_route_evidence(request(advisories=(a,))).fingerprint!=core.compose_route_evidence(request(advisories=(a.model_copy(update={field:changes[field]}),))).fingerprint


def test_complete_result_fingerprint_inventory():
    from hashlib import sha256
    from app.schemas.route_intelligence import RouteEvidenceResult
    r=core.compose_route_evidence(request(factual(),advisories=(advisory(),)))
    document=r.model_dump(mode="python",exclude={"fingerprint"})
    assert set(document)==set(RouteEvidenceResult.model_fields)-{"fingerprint"}
    expected=sha256(core._serialize(core._canonical(document)).encode()).hexdigest()
    assert r.fingerprint==expected
    # Every top-level semantic field, including constants/status/reasons, contributes.
    for field in document:
        changed={**document,field:{"synthetic_mutation":True}}
        assert sha256(core._serialize(core._canonical(changed)).encode()).hexdigest()!=r.fingerprint


@pytest.mark.parametrize("field",["published_at","observed_at","source_effective_at","derived_effective_at"])
def test_all_advisory_timestamp_offsets_microseconds_and_folds(field):
    from zoneinfo import ZoneInfo
    instant=datetime(2025,11,2,6,30,0,123456,tzinfo=timezone.utc)
    a=advisory().model_copy(update={field:instant})
    baseline=core.compose_route_evidence(request(advisories=(a,)))
    for zone in (timezone(timedelta(hours=3)),timezone(timedelta(hours=-5)),ZoneInfo("America/New_York")):
        equivalent=a.model_copy(update={field:instant.astimezone(zone)})
        assert core.compose_route_evidence(request(advisories=(equivalent,)))==baseline
    different=a.model_copy(update={field:instant+timedelta(microseconds=1)})
    assert core.compose_route_evidence(request(advisories=(different,))).fingerprint!=baseline.fingerprint


def test_datetime_bounds_and_controlled_overflow():
    for instant in (datetime.min.replace(tzinfo=timezone.utc),datetime.max.replace(tzinfo=timezone.utc)):
        r=core.compose_route_evidence(request().model_copy(update={"evaluated_at":instant}))
        assert r.evaluated_at==instant
    for instant in (datetime.min.replace(tzinfo=timezone(timedelta(hours=1))),
                    datetime.max.replace(tzinfo=timezone(timedelta(hours=-1)))):
        with pytest.raises(core.RouteEvidenceInputError):
            core.compose_route_evidence(request().model_copy(update={"evaluated_at":instant}))


def test_hostile_decimal_context_restored_exactly():
    from decimal import ROUND_DOWN, Inexact, Rounded, InvalidOperation
    with localcontext() as ctx:
        ctx.prec=2; ctx.rounding=ROUND_DOWN
        ctx.traps[Inexact]=True; ctx.traps[Rounded]=True
        ctx.flags[InvalidOperation]=True
        before=(ctx.prec,ctx.rounding,dict(ctx.traps),dict(ctx.flags))
        actual=core.compose_route_evidence(request(factual()))
        assert (ctx.prec,ctx.rounding,dict(ctx.traps),dict(ctx.flags))==before
    assert actual==core.compose_route_evidence(request(factual()))


@pytest.mark.parametrize("left,right",[("0","-0"),("0","0.0"),("1","1.0"),("1.0","1.00"),
    ("1E-27","0.000000000000000000000000001"),("1E30","1000000000000000000000000000000")])
def test_decimal_semantic_equivalence(left,right):
    assert core.compose_route_evidence(request(factual(predicted_rate=Decimal(left)))).fingerprint==core.compose_route_evidence(request(factual(predicted_rate=Decimal(right)))).fingerprint


def test_serialization_detachment_and_nested_immutability():
    r=core.compose_route_evidence(request(factual(),advisories=(advisory(),)))
    before=r.model_dump_json()
    detached=r.model_dump(mode="json")
    detached["advisories"][0]["snapshot"]["source_text"]="changed"
    detached["decision"]["policy"]["supported_horizons"].append(99)
    detached["assessment"].clear()
    detached["operational"].clear()
    detached["limitations"].append("changed")
    detached["provenance"].clear()
    assert r.model_dump_json()==before
    for collection in (r.advisories,r.advisory_conflicts,r.limitations,r.provenance,r.decision.reasons,r.decision.limitations):
        assert type(collection) is tuple
    assert type(r.decision.policy.supported_horizons) is frozenset
    with pytest.raises(ValidationError):
        r.operational.distance.reason="changed"
    with pytest.raises(ValidationError):
        r.assessment.methodology="changed"


def test_serialized_gaps_never_numeric_or_boolean():
    r=core.compose_route_evidence(request())
    doc=json.loads(r.model_dump_json())
    assert doc["decision"] is doc["assessment"] is None
    for section in doc["operational"].values():
        assert set(section)=={"availability","reason"}
        assert all(type(v) is str for v in section.values())
    assert "actionable" not in doc and "movement" not in doc
    assert len(r.limitations)==len(set(r.limitations))


def test_semantic_error_order_independent():
    a=advisory().model_copy(update={"series":SERIES.model_copy(update={"source":"Other"})})
    b=advisory().model_copy(update={"published_at":NOW+timedelta(days=1)})
    messages=[]
    for order in ((a,b),(b,a)):
        with pytest.raises(core.RouteEvidenceInputError) as exc:
            core.compose_route_evidence(request(advisories=order))
        messages.append(str(exc.value))
    assert messages[0]==messages[1]


def test_fresh_process_import_and_execution_infrastructure_guard():
    script='''import sys, builtins, socket, os, random, time
from datetime import datetime,timezone
from app.schemas.route_intelligence import MarketSeries,RouteEvidenceRequest
from app.services.route_intelligence import compose_route_evidence
assert not any(name in sys.modules for name in ("app.database","app.main","redis","celery","openai","sqlalchemy"))
req=RouteEvidenceRequest(series=MarketSeries(source="S",trade_lane="L",container_type="40ft"),evaluated_at=datetime(2026,1,2,tzinfo=timezone.utc))
def fail(*args,**kwargs): raise AssertionError("Infrastructure access")
builtins.open=socket.socket=os.getenv=random.random=time.time=fail
print(compose_route_evidence(req).fingerprint)'''
    results=[]
    for seed,zone in (("4","UTC"),("99","Asia/Tokyo")):
        results.append(subprocess.check_output([sys.executable,"-c",script],env={**os.environ,
            "PYTHONHASHSEED":seed,"TZ":zone,"LC_ALL":"C"},text=True).strip())
    assert results[0]==results[1]


def test_complete_factual_field_mutation_inventory():
    changes_f={"forecast_id":UUID(int=2),"series":SeriesIdentity(source="Other",trade_lane="Synthetic-Lane",container_type="40ft"),
        "forecast_for_date":NOW.date()+timedelta(days=1),"predicted_rate":Decimal("104"),"model_name":"MA(4)",
        "model_version":"other-methodology","forecast_horizon":2,"latest_observation_date":NOW.date(),
        "latest_actual_rate":Decimal("101"),"history_observations":101,"evaluation_points":31,
        "backtest_mae":1.1,"backtest_rmse":2.1,"backtest_smape":2.1,"backtest_directional_accuracy":51.0,
        "data_readiness":"MINIMAL","input_freshness_at_generation":"aging",
        "stored_live_decision_eligible":False,"warning":"Synthetic warning","generated_at":NOW-timedelta(seconds=1)}
    changes_s={"series":SeriesIdentity(source="Other",trade_lane="Synthetic-Lane",container_type="40ft"),
        "evaluated_at":NOW-timedelta(seconds=1),"latest_source_date":None,"latest_forecast_id":UUID(int=2),
        "latest_forecast_generated_at":NOW-timedelta(seconds=1),"series_matches":False,
        "source_superseded":True,"forecast_superseded":True,"current_input_freshness":"stale",
        "stored_live_decision_eligible":False,"effective_live_decision_eligible":False,
        "context_state":"superseded","context_warning":"Synthetic warning"}
    baseline=core.compose_route_evidence(request(factual()))
    for section,changes in (("forecast",changes_f),("current_state",changes_s)):
        assert set(changes)==set(getattr(factual(),section).model_fields)
        for field,value in changes.items():
            data=factual()
            data=data.model_copy(update={section:getattr(data,section).model_copy(update={field:value})})
            try:
                result=core.compose_route_evidence(request(data))
            except core.RouteEvidenceInputError:
                # Fatal inconsistent linkage is not silently fingerprinted as valid.
                continue
            assert result.fingerprint!=baseline.fingerprint, (section,field)


def test_no_programming_error_hidden(monkeypatch):
    def broken(*args): raise AttributeError("Synthetic programming defect")
    monkeypatch.setattr(core,"evaluate_decision",broken)
    with pytest.raises(AttributeError,match="Synthetic programming defect"):
        core.compose_route_evidence(request(factual()))


def test_unavailable_authoritative_result_is_not_remapped(monkeypatch):
    # Current T08 cannot return UNAVAILABLE for a non-null forecast. A valid
    # authoritative no-artifact result nevertheless passes through unchanged.
    unavailable=evaluate_decision(None,DecisionPolicy(),NOW)
    monkeypatch.setattr(core,"evaluate_decision",lambda *args:unavailable)
    r=core.compose_route_evidence(request(factual()))
    assert r.decision==unavailable and r.assessment==assess_evidence(unavailable)
    assert r.decision_status.availability==Availability.AVAILABLE


@pytest.mark.parametrize("value",[Decimal("NaN"),Decimal("Infinity"),Decimal("-Infinity"),Decimal("-1"),Decimal("0.001")])
def test_authoritative_monetary_schema_compatibility(value):
    data=factual(predicted_rate=value)
    # These values intentionally survive the copied-evidence schema; T08 owns
    # deficient-value blocking. T18 adds no cents/plausibility business rule.
    validated=DecisionInput.model_validate(data.model_dump(),strict=True)
    r=core.compose_route_evidence(request(validated))
    expected=evaluate_decision(validated,DecisionPolicy(),NOW)
    assert r.decision.decision==expected.decision and r.decision.reasons==expected.reasons
