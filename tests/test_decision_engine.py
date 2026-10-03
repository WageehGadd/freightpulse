from datetime import datetime, timezone, timedelta
from decimal import Decimal
from uuid import UUID
import pytest
from app.schemas.decision import *
from app.services.decision_engine import evaluate_decision

NOW = datetime(2026, 1, 2, tzinfo=timezone.utc)

def evidence(**changes):
    f = ForecastSnapshot(forecast_id=UUID(int=1), series=SeriesIdentity(source="SCFI", trade_lane="L", container_type="40ft"),
        forecast_for_date=NOW.date(), predicted_rate=Decimal("103"), model_name="MA(3)", model_version="baseline-v1",
        forecast_horizon=1, latest_observation_date=(NOW-timedelta(days=1)).date(), latest_actual_rate=Decimal("100"),
        history_observations=100, evaluation_points=30, backtest_mae=1, backtest_rmse=2, backtest_smape=2,
        backtest_directional_accuracy=50, data_readiness="BASELINE_READY", input_freshness_at_generation="fresh",
        stored_live_decision_eligible=True, warning=None, generated_at=NOW)
    f = f.model_copy(update=changes)
    s = ForecastState(series=f.series, evaluated_at=NOW, latest_source_date=f.latest_observation_date,
        latest_forecast_id=f.forecast_id, latest_forecast_generated_at=f.generated_at, series_matches=True,
        source_superseded=False, forecast_superseded=False, current_input_freshness="fresh",
        stored_live_decision_eligible=True, effective_live_decision_eligible=True, context_state="current", context_warning=None)
    return DecisionInput(forecast=f, current_state=s)

def run(i=None, **policy):
    return evaluate_decision(i or evidence(), DecisionPolicy(**policy), NOW)

@pytest.mark.parametrize('predicted,movement,decision',[
    ('103',Movement.INCREASE,Decision.CONSIDER_EARLIER_BOOKING),('97',Movement.DECREASE,Decision.CONSIDER_LATER_BOOKING),
    ('101',Movement.NEGLIGIBLE,Decision.MONITOR),('102',Movement.INCREASE,Decision.CONSIDER_EARLIER_BOOKING),
    ('98',Movement.DECREASE,Decision.CONSIDER_LATER_BOOKING),('101.999999',Movement.NEGLIGIBLE,Decision.MONITOR),
    ('102.000001',Movement.INCREASE,Decision.CONSIDER_EARLIER_BOOKING)])
def test_movement(predicted,movement,decision):
    r=run(evidence(predicted_rate=Decimal(predicted)))
    assert (r.movement,r.decision)==(movement,decision)
    assert r == run(evidence(predicted_rate=Decimal(predicted)))

@pytest.mark.parametrize('field,value,reason',[
    ('stored_live_decision_eligible',False,Reason.MODEL_INELIGIBLE),('data_readiness','MINIMAL',Reason.MINIMAL_READINESS),
    ('data_readiness','unknown',Reason.INSUFFICIENT_READINESS),('history_observations',99,Reason.INSUFFICIENT_HISTORY),
    ('history_observations',-1,Reason.INSUFFICIENT_HISTORY),('evaluation_points',29,Reason.INSUFFICIENT_EVALUATION),
    ('evaluation_points',-1,Reason.INSUFFICIENT_EVALUATION),('latest_actual_rate',Decimal(0),Reason.INVALID_RATE),
    ('latest_actual_rate',Decimal(-1),Reason.INVALID_RATE),('predicted_rate',Decimal(-1),Reason.INVALID_RATE),
    ('predicted_rate',Decimal('NaN'),Reason.INVALID_RATE),('latest_actual_rate',Decimal('Infinity'),Reason.INVALID_RATE),
    ('predicted_rate',None,Reason.INVALID_RATE),('backtest_mae',None,Reason.INVALID_METRICS),
    ('backtest_mae',float('nan'),Reason.INVALID_METRICS),('backtest_rmse',float('inf'),Reason.INVALID_METRICS),
    ('backtest_mae',-1,Reason.INVALID_METRICS),('backtest_rmse',-1,Reason.INVALID_METRICS),
    ('backtest_smape',201,Reason.INVALID_METRICS),('backtest_smape',-1,Reason.INVALID_METRICS),
    ('backtest_directional_accuracy',101,Reason.INVALID_METRICS),('backtest_directional_accuracy',-1,Reason.INVALID_METRICS),
    ('forecast_horizon',2,Reason.UNSUPPORTED_HORIZON),('forecast_for_date',NOW.date()-timedelta(days=1),Reason.EXPIRED_TARGET),
    ('latest_observation_date',NOW.date()+timedelta(days=1),Reason.INVALID_TEMPORAL_CONTEXT)])
def test_blockers(field,value,reason):
    for threshold in ('0.000000000001','1','2','3'):
        r=run(evidence(**{field:value}),movement_threshold_pct=Decimal(threshold))
        assert r.decision==Decision.WITHHOLD and not r.actionable and reason in r.reasons

@pytest.mark.parametrize('updates,reason',[
    ({'current_input_freshness':'stale'},Reason.STALE_INPUT),({'current_input_freshness':'unknown'},Reason.UNKNOWN_FRESHNESS),
    ({'source_superseded':True},Reason.SUPERSEDED_FORECAST),({'forecast_superseded':True},Reason.SUPERSEDED_FORECAST),
    ({'latest_source_date':None},Reason.SOURCE_UNAVAILABLE),({'series_matches':False},Reason.SERIES_MISMATCH)])
def test_state_blockers(updates,reason):
    i=evidence(); i=i.model_copy(update={'current_state':i.current_state.model_copy(update=updates)})
    for threshold in ('0.000000000001','1','2','3'):
        result=run(i,movement_threshold_pct=Decimal(threshold))
        assert reason in result.reasons and not result.actionable

def test_aging_and_complete_contract():
    i=evidence(); i=i.model_copy(update={'current_state':i.current_state.model_copy(update={'current_input_freshness':'aging'})})
    r=run(i)
    assert r.actionable and r.reasons==(Reason.FORECAST_INCREASE,Reason.AGING_INPUT)
    assert r.engine_version=='decision-rules-v1' and r.policy==DecisionPolicy()
    assert not {'confidence','probability','decision_score'} & r.model_fields.keys()
    assert not set(r.reasons) & set(r.limitations)
    with pytest.raises(ValueError): r.policy.error_multiplier=Decimal(2)

def test_accumulation_order():
    r=run(evidence(stored_live_decision_eligible=False,data_readiness='MINIMAL',history_observations=31,evaluation_points=16))
    assert r.reasons==(Reason.MODEL_INELIGIBLE,Reason.MINIMAL_READINESS,Reason.INSUFFICIENT_HISTORY,Reason.INSUFFICIENT_EVALUATION)

@pytest.mark.parametrize('multiplier,actionable',[('0.5',True),('1',False),('1.5',False)])
def test_error_sensitivity(multiplier,actionable):
    r=run(evidence(backtest_mae=3),error_multiplier=Decimal(multiplier))
    assert r.actionable==actionable
    if not actionable: assert Reason.MOVEMENT_WITHIN_ERROR_SCALE in r.reasons

def test_threshold_sensitivity_symmetry():
    for sign in (1,-1):
        actions=[run(evidence(predicted_rate=Decimal(100)+Decimal('2.5')*sign),movement_threshold_pct=Decimal(t)).actionable for t in ('1','2','3')]
        assert actions==[True,True,False]

def test_unavailable():
    r=evaluate_decision(None,DecisionPolicy(),NOW)
    assert r.decision==Decision.UNAVAILABLE and r.reasons==(Reason.NO_FORECAST,)

@pytest.mark.parametrize('policy',[{'movement_threshold_pct':0},{'error_multiplier':-1},{'movement_threshold_pct':'NaN'},
    {'min_history_observations':-1},{'min_evaluation_points':-1},{'supported_horizons':set()}])
def test_invalid_policy(policy):
    with pytest.raises(PolicyConfigurationError): DecisionPolicy(**policy)

def test_purity():
    import ast
    from pathlib import Path
    source=Path('app/services/decision_engine.py').read_text()
    imports=[n.module for n in ast.walk(ast.parse(source)) if isinstance(n,ast.ImportFrom)]
    assert imports==['datetime','decimal','app.schemas.decision']
    assert run().input_snapshot==evidence()

def test_utc_date_and_state_clock():
    i=evidence()
    assert run(i).actionable  # target-date equality
    later=NOW+timedelta(days=1)
    r=evaluate_decision(i,DecisionPolicy(),later)
    assert Reason.EXPIRED_TARGET in r.reasons and Reason.INVALID_TEMPORAL_CONTEXT in r.reasons
    with pytest.raises(ValueError): evaluate_decision(i,DecisionPolicy(),NOW.replace(tzinfo=None))

def test_decimal_unrounded_boundary_and_metric_endpoints():
    i=evidence(latest_actual_rate=Decimal('123.45'), predicted_rate=Decimal('125.919'),
        backtest_smape=200,backtest_directional_accuracy=100)
    r=run(i)
    assert r.signals.percentage_change==Decimal('2.00') and r.actionable
    assert run(evidence(backtest_directional_accuracy=0)).actionable

def test_nested_immutability():
    i=evidence()
    with pytest.raises(ValueError): i.forecast.series.source='other'
    with pytest.raises(ValueError): i.current_state.current_input_freshness='stale'
    assert isinstance(run(i).reasons,tuple)

@pytest.mark.parametrize('predicted,expected',[('97.999999',Movement.DECREASE),('98.000001',Movement.NEGLIGIBLE)])
def test_negative_neighbors(predicted,expected):
    assert run(evidence(predicted_rate=Decimal(predicted))).movement==expected

@pytest.mark.parametrize('predicted,actionable',[('102.999999',False),('103',False),('103.000001',True)])
def test_mae_neighbors(predicted,actionable):
    r=run(evidence(predicted_rate=Decimal(predicted),backtest_mae=3.0))
    assert r.actionable==actionable
    assert r.signals.error_scale==Decimal('3.0')
    assert Reason.MOVEMENT_BELOW_THRESHOLD not in r.reasons

@pytest.mark.parametrize('field',['backtest_mae','backtest_rmse','backtest_smape','backtest_directional_accuracy'])
def test_boolean_metrics(field):
    raw=evidence().forecast.model_dump(); raw[field]=True
    f=ForecastSnapshot(**raw)
    assert getattr(f,field) is None
    i=evidence().model_copy(update={'forecast':f})
    assert run(i).decision==Decision.WITHHOLD and Reason.INVALID_METRICS in run(i).reasons

@pytest.mark.parametrize('config',[{'supported_horizons':{0}},{'supported_horizons':{-1}},
    {'supported_horizons':{True}},{'supported_horizons':{'1'}},{'min_history_observations':True},
    {'min_evaluation_points':1.5},{'error_multiplier':'Infinity'},{'movement_threshold_pct':'Infinity'},
    {'engine_version':'fake'}])
def test_policy_hardening(config):
    with pytest.raises(PolicyConfigurationError): DecisionPolicy(**config)

def test_policy_copy_and_duplicate_horizon_set():
    caller_horizons=[1,1]
    policy=DecisionPolicy(supported_horizons=caller_horizons)
    r=evaluate_decision(evidence(),policy,NOW)
    caller_horizons.append(2)
    assert r.policy.supported_horizons==frozenset({1}) and r.policy is not policy
    with pytest.raises(ValueError): r.policy.min_history_observations=0

def test_stale_combination_precedence():
    i=evidence(stored_live_decision_eligible=False,data_readiness='MINIMAL',history_observations=31)
    i=i.model_copy(update={'current_state':i.current_state.model_copy(update={'current_input_freshness':'stale'})})
    r=run(i,movement_threshold_pct=Decimal('0.000000000001'))
    assert r.decision==Decision.WITHHOLD and r.movement==Movement.INCREASE
    assert r.reasons==(Reason.STALE_INPUT,Reason.MODEL_INELIGIBLE,Reason.MINIMAL_READINESS,Reason.INSUFFICIENT_HISTORY)

def test_result_enforces_actionable_invariant():
    r=run()
    for decision in Decision:
        raw=r.model_dump(); raw['decision']=decision
        raw['actionable']=decision not in (Decision.CONSIDER_EARLIER_BOOKING,Decision.CONSIDER_LATER_BOOKING)
        with pytest.raises(ValueError): DecisionResult(**raw)
    raw=r.model_dump(); raw['reasons']=(Reason.STALE_INPUT,)
    with pytest.raises(ValueError): DecisionResult(**raw)

def test_offset_date_and_negligible_precedence():
    offset=timezone(timedelta(hours=-5))
    same_instant=NOW.astimezone(offset)
    assert evaluate_decision(evidence(),DecisionPolicy(),same_instant)==run()
    assert same_instant.date()!=NOW.date()
    r=run(evidence(predicted_rate=Decimal('101'),backtest_mae=100))
    assert r.decision==Decision.MONITOR and r.reasons==(Reason.MOVEMENT_BELOW_THRESHOLD,)

def test_snapshot_evaluation_after_orm_mutation():
    from tests.test_grounded_rate_outlook import forecast
    from app.services.forecast_state import snapshot_forecast
    row=forecast(history_observations=100,evaluation_points=30,data_readiness='BASELINE_READY',
        live_decision_eligible=True,predicted_rate=Decimal('103'),latest_actual_rate=Decimal('100'),backtest_mae=1)
    copied=snapshot_forecast(row)
    i=evidence().model_copy(update={'forecast':copied,'current_state':evidence().current_state.model_copy(update={
        'series':copied.series,'latest_forecast_id':copied.forecast_id})})
    before=run(i)
    row.predicted_rate=Decimal('1'); row.live_decision_eligible=False; row.history_observations=0
    assert run(i)==before and before.actionable
