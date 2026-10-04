"""T10 public composition and independent-session currency regression tests."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.forecast_persistence import ForecastPersistenceService
from app.services.forecast_state import ForecastStateCollector, snapshot_forecast
from tests.test_grounded_rate_outlook import forecast, source_row

NOW = datetime(2026, 1, 2, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_cross_session_regeneration_refreshes_authoritative_winner(db_session):
    row = forecast()
    db_session.add_all([row, source_row(row)])
    await db_session.commit()
    service = ForecastPersistenceService(db_session)
    selected = (await service.get_latest_forecasts(row.source, row.trade_lane, row.container_type))[0]
    snapshot = snapshot_forecast(selected)
    async with AsyncSession(bind=db_session.bind, expire_on_commit=False) as session_b:
        external = await session_b.get(type(row), row.id)
        external.generated_at = row.generated_at + timedelta(seconds=1)
        external.predicted_rate = Decimal('999.00')
        await session_b.commit()
    winner = (await service.get_latest_forecasts(row.source, row.trade_lane, row.container_type))[0]
    assert winner.generated_at == snapshot.generated_at + timedelta(seconds=1)
    assert winner.predicted_rate == Decimal('999.00')
    state = await ForecastStateCollector(db_session).collect(snapshot, NOW)
    assert state.forecast_superseded
    assert snapshot.predicted_rate != winner.predicted_rate

import json
import subprocess
import sys
from unittest.mock import AsyncMock
from fastapi import HTTPException
from sqlalchemy import select, func

from app.main import app
from app.models import RateForecast, RateOutlook
from app.schemas.decision import Decision, DecisionPolicy, PolicyConfigurationError
from app.services.decision_api import DecisionAPIService, to_public_response
from app.services.reliability import EvidenceInputError, assess_evidence
from app.services.decision_engine import evaluate_decision
from tests.test_decision_engine import evidence as pure_evidence

PATH = '/api/v1/decisions/latest'
PARAMS = {'source': 'SCFI', 'trade_lane': 'T07-Lane', 'container_type': '40ft'}
pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def transport_and_time(monkeypatch):
    redis = AsyncMock()
    redis.incr.return_value = 1
    monkeypatch.setattr('app.auth.rate_limit.get_redis', lambda: redis)
    monkeypatch.setattr('app.services.decision_api.utc_now', lambda: NOW)
    return redis


@pytest.fixture
async def eligible(db_session):
    row = forecast(predicted_rate=Decimal('103.01'), history_observations=100,
                   evaluation_points=30, data_readiness='BASELINE_READY',
                   live_decision_eligible=True, backtest_mae=1.0, backtest_rmse=2.0,
                   warning='Private internal warning must never be exposed')
    db_session.add_all([row, source_row(row)])
    await db_session.commit()
    return row


async def test_registered_get_only_and_openapi():
    paths = app.openapi()['paths']
    assert set(paths[PATH]) == {'get'}
    operation = paths[PATH]['get']
    parameters = {p['name']: p for p in operation['parameters']}
    assert all(parameters[p]['required'] for p in PARAMS)
    assert 'requestBody' not in operation
    assert {'200', '401', '404', '422', '429', '500'} <= set(operation['responses'])
    assert operation['security']
    assert not any(p.startswith('/api/v1/decisions/') and p != PATH for p in paths)
    schemas = app.openapi()['components']['schemas']
    assert schemas['DecisionForecast']['properties']['predicted_rate']['anyOf'][0]['type'] == 'string'
    assert {'CONSIDER_EARLIER_BOOKING', 'WITHHOLD', 'MONITOR'} <= set(schemas['Decision']['enum'])


@pytest.mark.parametrize('headers', [{}, {'X-API-Key': 'invalid-isolated-key'}])
async def test_auth_required(client, headers):
    response = await client.get(PATH, params=PARAMS, headers=headers)
    assert response.status_code == 401
    assert response.json()['error']['code'] == 'UNAUTHORIZED'


async def test_post_not_supported(authenticated_client):
    assert (await authenticated_client.post(PATH, params=PARAMS)).status_code == 405


@pytest.mark.parametrize('field', list(PARAMS))
@pytest.mark.parametrize('value', [None, '', '   ', '\t\n'])
async def test_required_nonempty_selectors(authenticated_client, field, value):
    params = PARAMS.copy()
    if value is None:
        del params[field]
    else:
        params[field] = value
    response = await authenticated_client.get(PATH, params=params)
    assert response.status_code == 422


@pytest.mark.parametrize('updates', [{'source': 'scfi'}, {'trade_lane': 't07-lane'},
    {'container_type': '40FT'}, {'trade_lane': ' T07-Lane '}, {'source': 'MISSING'}])
async def test_exact_matching_no_normalization(authenticated_client, eligible, updates):
    response = await authenticated_client.get(PATH, params={**PARAMS, **updates})
    assert response.status_code == 404


async def test_absence_no_synthetic_decision_or_generation(authenticated_client, db_session, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('Decision read invoked generation/narration')
    monkeypatch.setattr(ForecastPersistenceService, 'generate_and_persist_all', forbidden)
    monkeypatch.setattr('app.services.rate_outlook.RateOutlookService.create', forbidden)
    monkeypatch.setattr('app.ai.rate_outlook_narrator.RateOutlookNarrator.narrate_grounded', forbidden)
    monkeypatch.setattr('app.tasks.rate_outlook_generation.generate_rate_outlook.delay', forbidden)
    response = await authenticated_client.get(PATH, params=PARAMS)
    assert response.status_code == 404
    assert response.json() == {'error': {'code': 'NOT_FOUND',
        'message': 'No persisted forecast exists for the requested exact series', 'details': {}}}
    assert await db_session.scalar(select(func.count()).select_from(RateForecast)) == 0
    assert await db_session.scalar(select(func.count()).select_from(RateOutlook)) == 0


@pytest.mark.parametrize('prediction,decision,actionable', [
    ('103.01', 'CONSIDER_EARLIER_BOOKING', True),
    ('97.01', 'CONSIDER_LATER_BOOKING', True), ('101.01', 'MONITOR', False),
])
async def test_real_composition_all_unblocked_decisions(authenticated_client, db_session, eligible,
                                                      prediction, decision, actionable):
    eligible.predicted_rate = Decimal(prediction)
    await db_session.commit()
    response = await authenticated_client.get(PATH, params=PARAMS)
    assert response.status_code == 200
    body = response.json()
    assert body['decision']['decision'] == decision
    assert body['decision']['actionable'] is actionable
    assert body['evidence']['historical_evidence_status'] == 'AVAILABLE'
    assert body['evidence']['sample_sufficiency_status'] == 'POLICY_MINIMUMS_MET'
    assert body['evidence']['decision_evidence_status'] == ('DIRECTIONAL_RULES_PASSED' if actionable else 'MONITOR_ONLY')
    assert response.headers['cache-control'] == 'no-store'


@pytest.mark.parametrize('case,reason', [('missing_source', 'SOURCE_UNAVAILABLE'),
    ('newer_source', 'SUPERSEDED_FORECAST'), ('stale', 'STALE_INPUT'),
    ('expired', 'EXPIRED_TARGET'), ('stored', 'MODEL_INELIGIBLE'),
    ('history', 'INSUFFICIENT_HISTORY'), ('evaluation', 'INSUFFICIENT_EVALUATION'),
    ('readiness', 'MINIMAL_READINESS')])
async def test_business_blockers_are_200(authenticated_client, db_session, eligible, monkeypatch, case, reason):
    from sqlalchemy import delete
    if case == 'missing_source':
        from app.models import FreightRate
        await db_session.execute(delete(FreightRate))
    elif case == 'newer_source':
        db_session.add(source_row(eligible, day=eligible.latest_observation_date + timedelta(days=1)))
    elif case == 'stale':
        monkeypatch.setattr('app.services.decision_api.utc_now', lambda: NOW + timedelta(days=30))
    elif case == 'expired':
        monkeypatch.setattr('app.services.decision_api.utc_now', lambda: NOW + timedelta(days=1))
    elif case == 'stored':
        eligible.live_decision_eligible = False
    elif case == 'history':
        eligible.history_observations = 31
    elif case == 'evaluation':
        eligible.evaluation_points = 16
    elif case == 'readiness':
        eligible.data_readiness = 'MINIMAL'
    await db_session.commit()
    response = await authenticated_client.get(PATH, params=PARAMS)
    assert response.status_code == 200
    body = response.json()
    assert body['decision']['decision'] == 'WITHHOLD' and not body['decision']['actionable']
    assert reason in body['decision']['reasons']
    assert body['evidence']['decision_evidence_status'] == 'BLOCKED'
    assert body['evidence']['historical_evidence_status'] == 'AVAILABLE'
    if case in ('missing_source', 'newer_source', 'stale', 'stored'):
        assert not body['current_state']['effective_live_decision_eligible']


@pytest.mark.parametrize('case', ['regeneration', 'new_winner'])
async def test_race_after_selection_blocks_old_snapshot(authenticated_client, db_session, eligible, monkeypatch, case):
    original = ForecastStateCollector.collect
    async def collect(collector, snapshot, evaluated_at, **kwargs):
        async with AsyncSession(bind=db_session.bind, expire_on_commit=False) as session_b:
            if case == 'regeneration':
                row = await session_b.get(RateForecast, snapshot.forecast_id)
                row.generated_at += timedelta(seconds=1)
                row.predicted_rate = Decimal('999.00')
            else:
                session_b.add(forecast(model_name='MA(4)', generated_at=NOW + timedelta(seconds=1)))
            await session_b.commit()
        return await original(collector, snapshot, evaluated_at, **kwargs)
    monkeypatch.setattr(ForecastStateCollector, 'collect', collect)
    response = await authenticated_client.get(PATH, params=PARAMS)
    assert response.status_code == 200
    body = response.json()
    assert body['forecast']['predicted_rate'] == '103.01'
    assert body['decision']['decision'] == 'WITHHOLD'
    assert body['current_state']['forecast_superseded']
    assert not body['current_state']['effective_live_decision_eligible']


async def test_series_isolation_and_latest_ties(authenticated_client, db_session, eligible):
    old = forecast(day=eligible.latest_observation_date - timedelta(days=1), generated_at=NOW + timedelta(days=2))
    losing = forecast(model_name='MA(4)', predicted_rate=Decimal('999.00'), generated_at=NOW)
    alien = forecast(source='OTHER', day=eligible.latest_observation_date + timedelta(days=10))
    db_session.add_all([old, losing, alien, source_row(alien)])
    await db_session.commit()
    body = (await authenticated_client.get(PATH, params=PARAMS)).json()
    assert body['forecast']['forecast_id'] == str(eligible.id)
    assert body['identity'] == PARAMS
    assert not body['current_state']['source_superseded']


@pytest.mark.parametrize('field,value', [('backtest_mae', float('nan')),
    ('backtest_rmse', float('inf')), ('backtest_smape', 201.0),
    ('backtest_directional_accuracy', -1.0)])
async def test_invalid_metrics_business_evidence_null(authenticated_client, db_session, eligible, field, value):
    setattr(eligible, field, value)
    await db_session.commit()
    response = await authenticated_client.get(PATH, params=PARAMS)
    assert response.status_code == 200
    body = response.json()
    assert body['evidence']['historical_evidence_status'] == 'INVALID_OR_INCOMPLETE'
    assert body['decision']['decision'] == 'WITHHOLD'
    assert 'NaN' not in response.text and 'Infinity' not in response.text
    metrics = {**body['evidence']['historical_error'], **body['evidence']['directional_evidence']}
    assert metrics[field.removeprefix('backtest_')] is None


async def test_unsupported_does_not_override_t08(authenticated_client, db_session, eligible):
    eligible.model_version = 'future-v2'
    await db_session.commit()
    body = (await authenticated_client.get(PATH, params=PARAMS)).json()
    assert body['evidence']['historical_evidence_status'] == 'UNSUPPORTED'
    assert body['decision']['decision'] == 'CONSIDER_EARLIER_BOOKING'
    assert body['decision']['actionable']
    assert not body['provenance']['methodology_supported']


@pytest.mark.parametrize('count,expected', [(-1, 'NOT_ASSESSABLE'), (31, 'LIMITED'), (100, 'POLICY_MINIMUMS_MET')])
async def test_public_sample_states(authenticated_client, db_session, eligible, count, expected):
    eligible.history_observations = count
    await db_session.commit()
    body = (await authenticated_client.get(PATH, params=PARAMS)).json()
    assert body['evidence']['sample_sufficiency_status'] == expected
    if expected != 'POLICY_MINIMUMS_MET':
        assert body['decision']['decision'] == 'WITHHOLD'
        assert not body['decision']['actionable']


async def test_json_contract_provenance_and_determinism(authenticated_client, eligible):
    first = await authenticated_client.get(PATH, params=PARAMS)
    second = await authenticated_client.get(PATH, params=PARAMS)
    assert first.status_code == 200 and first.json() == second.json()
    body = first.json()
    assert set(body) == {'identity', 'forecast', 'decision', 'evidence', 'current_state', 'policy', 'provenance'}
    assert body['forecast'] == {'forecast_id': str(eligible.id), 'predicted_rate': '103.01',
        'latest_actual_rate': '100.01', 'latest_observation_date': '2026-01-01',
        'forecast_for_date': '2026-01-02', 'forecast_horizon': 1}
    assert body['decision']['absolute_change'] == '3.00'
    assert isinstance(body['decision']['percentage_change'], str)
    assert isinstance(body['decision']['error_scale'], str)
    assert isinstance(body['evidence']['normalized_signals']['movement_to_mae_ratio'], str)
    assert body['policy'] == {'movement_threshold_pct': '2.0', 'min_history_observations': 100,
        'min_evaluation_points': 30, 'error_multiplier': '1.0', 'supported_horizons': [1]}
    assert body['provenance']['generated_at'] == '2026-01-02T00:00:00Z'
    assert body['provenance']['evaluated_at'] == '2026-01-02T00:00:00Z'
    assert body['provenance']['engine_version'] == 'decision-rules-v1'
    assert body['provenance']['assessment_version'] == 'evidence-v1'
    assert body['provenance']['model_version'] == 'baseline-v1-decimal'
    assert body['evidence']['directional_evidence']['valid_directional_sample_count'] is None
    assert body['decision']['reasons'] == ['FORECAST_INCREASE']
    assert body['evidence']['assessment_limitations'] == ['SELECTION_WINDOW_NOT_INDEPENDENT', 'DIRECTIONAL_DENOMINATOR_UNAVAILABLE']
    assert [f['reference'] for f in body['evidence']['factors']] == ['sample_counts',
        'mae_relative_to_latest_actual_pct', 'rmse_relative_to_latest_actual_pct',
        'movement_to_mae_ratio', 'backtest_protocol', 'valid_directional_sample_count']
    assert isinstance(body['evidence']['historical_error']['mae'], float)
    for forbidden in ('decision_result', 'input_snapshot', 'confidence', 'probability', 'decision_score',
                      'reliability_score', 'quality_score', 'Private internal warning'):
        assert forbidden not in first.text


async def test_single_evaluation_instant(authenticated_client, eligible, monkeypatch):
    calls = []
    def clock():
        calls.append(NOW)
        return NOW
    original_collect = ForecastStateCollector.collect
    original_evaluate = evaluate_decision
    def evaluate(snapshot, policy, instant):
        assert snapshot.current_state.evaluated_at == instant == NOW
        return original_evaluate(snapshot, policy, instant)
    async def collect(collector, snapshot, instant, **kwargs):
        assert instant == NOW
        return await original_collect(collector, snapshot, instant, **kwargs)
    monkeypatch.setattr('app.services.decision_api.utc_now', clock)
    monkeypatch.setattr('app.services.decision_api.evaluate_decision', evaluate)
    monkeypatch.setattr(ForecastStateCollector, 'collect', collect)
    response = await authenticated_client.get(PATH, params=PARAMS)
    assert response.status_code == 200 and calls == [NOW]
    assert response.json()['provenance']['evaluated_at'] == NOW.isoformat().replace('+00:00', 'Z')


@pytest.mark.parametrize('target,error', [
    ('assess_evidence', EvidenceInputError('PRIVATE internal snapshot')),
    ('evaluate_decision', PolicyConfigurationError('PRIVATE policy')),
    ('snapshot_forecast', ValueError('PRIVATE corrupt record')),
    ('evaluate_decision', RuntimeError('PRIVATE unexpected failure')),
])
async def test_integrity_errors_sanitized(authenticated_client, eligible, monkeypatch, target, error):
    def fail(*args, **kwargs):
        raise error
    monkeypatch.setattr('app.services.decision_api.' + target, fail)
    response = await authenticated_client.get(PATH, params=PARAMS)
    assert response.status_code == 500
    assert response.json() == {'error': {'code': 'ERROR',
        'message': 'Decision evaluation failed. Check server logs.', 'details': {}}}
    assert 'PRIVATE' not in response.text


async def test_database_failure_sanitized(authenticated_client, monkeypatch):
    async def fail(*args, **kwargs):
        raise RuntimeError('PRIVATE DB credentials')
    monkeypatch.setattr(ForecastPersistenceService, 'get_latest_forecasts', fail)
    response = await authenticated_client.get(PATH, params=PARAMS)
    assert response.status_code == 500 and 'PRIVATE' not in response.text


async def test_artifact_backed_unavailable_is_integrity_error(authenticated_client, eligible, monkeypatch):
    monkeypatch.setattr('app.services.decision_api.evaluate_decision',
        lambda *args: evaluate_decision(None, DecisionPolicy(), NOW))
    response = await authenticated_client.get(PATH, params=PARAMS)
    assert response.status_code == 500


async def test_naive_provenance_and_clock_rejected(authenticated_client, eligible, monkeypatch):
    original = snapshot_forecast
    monkeypatch.setattr('app.services.decision_api.snapshot_forecast', lambda row:
        original(row).model_copy(update={'generated_at': NOW.replace(tzinfo=None)}))
    assert (await authenticated_client.get(PATH, params=PARAMS)).status_code == 500
    monkeypatch.setattr('app.services.decision_api.snapshot_forecast', original)
    monkeypatch.setattr('app.services.decision_api.utc_now', lambda: NOW.replace(tzinfo=None))
    assert (await authenticated_client.get(PATH, params=PARAMS)).status_code == 500


async def test_real_snapshot_validation_failure(authenticated_client, eligible, monkeypatch):
    def corrupt(row):
        row.model_name = None
        return snapshot_forecast(row)
    monkeypatch.setattr('app.services.decision_api.snapshot_forecast', corrupt)
    response = await authenticated_client.get(PATH, params=PARAMS)
    assert response.status_code == 500


async def test_rate_limit_and_redis_failure(authenticated_client, transport_and_time):
    transport_and_time.incr.return_value = 101
    assert (await authenticated_client.get(PATH, params=PARAMS)).status_code == 429
    transport_and_time.incr.side_effect = RuntimeError('isolated Redis unavailable')
    assert (await authenticated_client.get(PATH, params=PARAMS)).status_code == 404


async def test_success_does_not_invoke_generation(authenticated_client, eligible, db_session, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('Generation/narration invoked')
    monkeypatch.setattr(ForecastPersistenceService, 'generate_and_persist_all', forbidden)
    monkeypatch.setattr('app.services.rate_outlook.RateOutlookService.create', forbidden)
    monkeypatch.setattr('app.ai.rate_outlook_narrator.RateOutlookNarrator.narrate_grounded', forbidden)
    monkeypatch.setattr('app.tasks.rate_outlook_generation.generate_rate_outlook.delay', forbidden)
    response = await authenticated_client.get(PATH, params=PARAMS)
    assert response.status_code == 200
    assert await db_session.scalar(select(func.count()).select_from(RateForecast)) == 1
    assert await db_session.scalar(select(func.count()).select_from(RateOutlook)) == 0


async def test_import_without_gpt_narration_or_workers():
    script = '''
import importlib.abc, sys
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in ('openai', 'azure', 'celery') or fullname.startswith(('app.ai', 'app.tasks', 'app.services.rate_outlook')):
            raise ImportError(fullname)
sys.meta_path.insert(0, Block())
from app.services.decision_api import DecisionAPIService
assert DecisionAPIService
'''
    subprocess.run([sys.executable, '-B', '-c', script], check=True, capture_output=True, text=True)


async def test_no_artifact_statuses_are_internal_not_public():
    r = evaluate_decision(None, DecisionPolicy(), NOW)
    a = assess_evidence(r)
    assert a.historical_evidence_status.value == a.decision_evidence_status.value == 'UNAVAILABLE'
    with pytest.raises(EvidenceInputError):
        to_public_response(r, a)


async def test_no_fallback_to_older_eligible_forecast(authenticated_client, db_session, eligible):
    newest = forecast(model_name='MA(4)', generated_at=NOW + timedelta(seconds=1),
                      live_decision_eligible=False)
    db_session.add(newest)
    await db_session.commit()
    body = (await authenticated_client.get(PATH, params=PARAMS)).json()
    assert body['forecast']['forecast_id'] == str(newest.id)
    assert body['decision']['decision'] == 'WITHHOLD'
    assert not body['decision']['actionable']


async def test_domain_queries_read_only_and_context_isolated(db_session, eligible):
    from sqlalchemy import event
    from decimal import localcontext, ROUND_DOWN
    statements = []
    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement.lstrip().split()[0].upper())
    event.listen(db_session.bind.sync_engine, 'before_cursor_execute', record)
    try:
        with localcontext() as context:
            context.prec = 3
            context.rounding = ROUND_DOWN
            context.clear_flags()
            before = str(context)
            result = await DecisionAPIService(db_session).latest(**PARAMS)
            assert result.decision.decision == Decision.CONSIDER_EARLIER_BOOKING
            assert str(context) == before
    finally:
        event.remove(db_session.bind.sync_engine, 'before_cursor_execute', record)
    assert statements == ['SELECT', 'SELECT', 'SELECT']


async def test_nonfinite_money_null_preserves_business_block(db_session, authenticated_client, eligible):
    eligible.latest_actual_rate = Decimal('NaN')
    await db_session.commit()
    response = await authenticated_client.get(PATH, params=PARAMS)
    assert response.status_code == 200
    body = response.json()
    assert body['forecast']['latest_actual_rate'] is None
    assert body['decision']['absolute_change'] is None
    assert body['decision']['decision'] == 'WITHHOLD'
    assert 'INVALID_RATE' in body['decision']['reasons']
    assert 'NaN' not in response.text


async def test_aging_copied_state_and_utc_normalization(db_session, eligible, monkeypatch):
    instant = NOW + timedelta(days=11)
    offset = timezone(timedelta(hours=3))
    monkeypatch.setattr('app.services.decision_api.utc_now', lambda: instant.astimezone(offset))
    result = await DecisionAPIService(db_session).latest(**PARAMS)
    assert result.current_state.current_input_freshness == 'aging'
    assert result.provenance.evaluated_at == instant
    assert result.provenance.evaluated_at.utcoffset() == timedelta(0)
    assert 'AGING_INPUT' in [r.value for r in result.decision.reasons]
    assert result.decision.decision == Decision.WITHHOLD  # Target expiry still blocks.


async def test_invalid_selector_never_queries_domain(authenticated_client, monkeypatch):
    async def forbidden(*args, **kwargs):
        pytest.fail('Invalid selector reached domain selection')
    monkeypatch.setattr(ForecastPersistenceService, 'get_latest_forecasts', forbidden)
    assert (await authenticated_client.get(PATH, params={**PARAMS, 'source': ' '})).status_code == 422


async def test_impossible_multiple_or_mismatched_winners(authenticated_client, eligible, monkeypatch):
    async def multiple(*args, **kwargs):
        return [eligible, eligible]
    monkeypatch.setattr(ForecastPersistenceService, 'get_latest_forecasts', multiple)
    assert (await authenticated_client.get(PATH, params=PARAMS)).status_code == 500
    async def mismatched(*args, **kwargs):
        return [forecast(source='OTHER')]
    monkeypatch.setattr(ForecastPersistenceService, 'get_latest_forecasts', mismatched)
    assert (await authenticated_client.get(PATH, params=PARAMS)).status_code == 500


async def test_caller_cannot_override_policy(authenticated_client, eligible):
    response = await authenticated_client.get(PATH, params={**PARAMS,
        'movement_threshold_pct': '99', 'min_history_observations': '0', 'error_multiplier': '0'})
    assert response.status_code == 200
    body = response.json()
    assert body['policy']['movement_threshold_pct'] == '2.0'
    assert body['policy']['min_history_observations'] == 100
    assert body['policy']['error_multiplier'] == '1.0'
    assert body['decision']['decision'] == 'CONSIDER_EARLIER_BOOKING'


@pytest.mark.parametrize('selector', list(PARAMS))
@pytest.mark.parametrize('value', ['\x1c', '\x1d', '\x1e', '\x1f', '\u00a0', '\u2003'])
async def test_all_python_whitespace_selectors_rejected(authenticated_client, selector, value):
    assert not value.strip()
    response = await authenticated_client.get(PATH, params={**PARAMS, selector: value})
    assert response.status_code == 422


async def test_standalone_mapper_preserves_decimal_context():
    from decimal import localcontext, ROUND_DOWN
    decision = evaluate_decision(pure_evidence(model_version='baseline-v1-decimal'), DecisionPolicy(), NOW)
    assessment = assess_evidence(decision)
    with localcontext() as context:
        context.prec = 3
        context.rounding = ROUND_DOWN
        context.clear_flags()
        before = str(context)
        response = to_public_response(decision, assessment)
        assert response.decision.decision == decision.decision
        assert str(context) == before


async def test_external_new_row_becomes_selected_winner(db_session):
    old = forecast()
    db_session.add_all([old, source_row(old)])
    await db_session.commit()
    service = ForecastPersistenceService(db_session)
    loaded = (await service.get_latest_forecasts(old.source, old.trade_lane, old.container_type))[0]
    copied = snapshot_forecast(loaded)
    new = forecast(model_name='MA(4)', generated_at=NOW + timedelta(seconds=1))
    async with AsyncSession(bind=db_session.bind, expire_on_commit=False) as session_b:
        session_b.add(new)
        await session_b.commit()
    winner = (await service.get_latest_forecasts(old.source, old.trade_lane, old.container_type))[0]
    assert winner.id == new.id != loaded.id
    assert copied.forecast_id == loaded.id
    assert (await ForecastStateCollector(db_session).collect(copied, NOW)).forecast_superseded


async def test_winner_refresh_preserves_normal_autoflush(db_session):
    row = forecast()
    db_session.add_all([row, source_row(row)])
    await db_session.commit()
    row.predicted_rate = Decimal('123.45')
    rows = await ForecastPersistenceService(db_session).get_latest_forecasts(
        row.source, row.trade_lane, row.container_type)
    assert rows[0].predicted_rate == Decimal('123.45')
    assert row not in db_session.dirty
    # Autoflush did not commit: another transaction still sees the original value.
    async with AsyncSession(bind=db_session.bind, expire_on_commit=False) as session_b:
        external = await session_b.get(RateForecast, row.id)
        assert external.predicted_rate == Decimal('101.03')
    await db_session.rollback()


@pytest.mark.parametrize('value', ['0', '-0', '0.000000000000000001', '9999999999.99', '123.4500'])
async def test_decimal_edges_exact_public_strings(value):
    from app.schemas.decision_api import DecisionForecast
    model = DecisionForecast(forecast_id=forecast().id, predicted_rate=Decimal(value),
        latest_actual_rate=Decimal(value), latest_observation_date=NOW.date(),
        forecast_for_date=NOW.date(), forecast_horizon=1)
    body = json.loads(model.model_dump_json())
    assert body['predicted_rate'] == str(Decimal(value))
    assert body['latest_actual_rate'] == str(Decimal(value))


@pytest.mark.parametrize('freshness', ['fresh', 'aging', 'stale', 'unknown'])
@pytest.mark.parametrize('stored', [False, True])
async def test_public_state_policy_and_decision_exact_parity(freshness, stored):
    from app.schemas.decision import DecisionInput
    input_snapshot = pure_evidence(model_version='baseline-v1-decimal', stored_live_decision_eligible=stored)
    input_snapshot = input_snapshot.model_copy(update={'current_state':
        input_snapshot.current_state.model_copy(update={'current_input_freshness': freshness,
            'stored_live_decision_eligible': stored,
            'effective_live_decision_eligible': stored and freshness in ('fresh', 'aging')})})
    policy = DecisionPolicy(supported_horizons=frozenset({2, 1}))
    decision = evaluate_decision(input_snapshot, policy, NOW)
    evidence = assess_evidence(decision)
    response = to_public_response(decision, evidence)
    state = input_snapshot.current_state
    for field in response.current_state.model_fields:
        if field == 'input_freshness_at_generation':
            assert getattr(response.current_state, field) == input_snapshot.forecast.input_freshness_at_generation
        else:
            assert getattr(response.current_state, field) == getattr(state, field)
    for field in ('decision', 'actionable', 'movement', 'reasons', 'limitations'):
        assert getattr(response.decision, field) == getattr(decision, field)
    assert response.policy.supported_horizons == (1, 2)
    assert response.policy.movement_threshold_pct == decision.policy.movement_threshold_pct
    assert response.evidence.historical_evidence_status == evidence.historical_evidence_status
    assert response.evidence.decision_evidence_status == evidence.decision_evidence_status


async def test_new_router_import_has_no_provider_or_connection_side_effects():
    script = '''
import importlib.abc, sys
from sqlalchemy.ext.asyncio import AsyncEngine
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in ('openai','azure','celery') or fullname.startswith(('app.ai','app.tasks','app.services.rate_outlook')):
            raise ImportError(fullname)
def forbidden(*args, **kwargs):
    raise AssertionError('Connection attempted while importing decision router')
AsyncEngine.connect = forbidden
sys.meta_path.insert(0, Block())
from app.routers.decisions import router
assert len(router.routes) == 1
'''
    subprocess.run([sys.executable, '-B', '-c', script], check=True, capture_output=True, text=True)


async def test_recursive_schema_has_only_approved_public_concepts():
    from app.schemas.decision_api import DecisionAPIResponse
    schema = DecisionAPIResponse.model_json_schema(mode='serialization')
    names = []
    def collect(node):
        if isinstance(node, dict):
            names.extend(node.get('properties', {}).keys())
            for item in node.values():
                collect(item)
        elif isinstance(node, list):
            for item in node:
                collect(item)
    collect(schema)
    assert not set(names) & {'confidence', 'confidence_score', 'probability',
        'reliability_score', 'decision_score', 'quality_score', 'is_reliable',
        'safe_to_book', 'decision_result', 'input_snapshot'}
    assert names.count('actionable') == names.count('policy') == names.count('current_state') == 1
    assert not {'DecisionResult', 'EvidenceAssessment', 'ForecastSnapshot'} & set(schema.get('$defs', {}))


async def test_t10_failure_logs_do_not_include_exception_or_evidence(authenticated_client, eligible, monkeypatch):
    from unittest.mock import MagicMock
    logger = MagicMock()
    monkeypatch.setattr('app.routers.decisions.logger', logger)
    def fail(*args, **kwargs):
        raise EvidenceInputError('PRIVATE credential and full internal snapshot')
    monkeypatch.setattr('app.services.decision_api.assess_evidence', fail)
    response = await authenticated_client.get(PATH, params=PARAMS)
    assert response.status_code == 500
    logger.error.assert_called_once()
    args, fields = logger.error.call_args
    assert args == ('decision_evaluation_failed',)
    assert fields['error_type'] == 'EvidenceInputError'
    assert set(fields) == {'endpoint', 'http_status', 'error_type', 'latency_ms'}
    assert 'PRIVATE' not in repr(logger.mock_calls)


@pytest.mark.parametrize('neighbor', [{'source': 'OTHER'}, {'lane': 'Other-Lane'}, {'container': '20ft'}])
async def test_each_neighbor_identity_dimension_is_isolated(authenticated_client, db_session, eligible, neighbor):
    other = forecast(day=eligible.latest_observation_date + timedelta(days=10), **neighbor)
    db_session.add_all([other, source_row(other)])
    await db_session.commit()
    response = await authenticated_client.get(PATH, params=PARAMS)
    assert response.status_code == 200
    body = response.json()
    assert body['identity'] == PARAMS
    assert body['forecast']['forecast_id'] == str(eligible.id)
    assert not body['current_state']['source_superseded']
