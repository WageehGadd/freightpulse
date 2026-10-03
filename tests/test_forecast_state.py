from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch
import pytest
from tests.test_grounded_rate_outlook import forecast
from app.services.forecast_state import ForecastStateCollector, snapshot_forecast, freshness_and_eligibility
from app.services.data_quality import DataQualityService

NOW=datetime(2026,1,2,tzinfo=timezone.utc)

@pytest.mark.asyncio
@pytest.mark.parametrize('case,expected', [('current','current'),('missing','source_unavailable'),('source','superseded'),('winner','superseded'),('generation','superseded')])
async def test_collection(case,expected):
    row=forecast(); copied=snapshot_forecast(row)
    session=AsyncMock()
    session.scalar.return_value=None if case=='missing' else row.latest_observation_date+timedelta(days=1 if case=='source' else 0)
    winner=forecast() if case=='winner' else row
    if case=='generation': row.generated_at+=timedelta(seconds=1)
    with patch('app.services.forecast_state.ForecastPersistenceService.get_latest_forecasts',new=AsyncMock(return_value=[winner])) as latest:
        state=await ForecastStateCollector(session).collect(copied,NOW)
        if case in ('missing', 'source'):
            latest.assert_not_awaited()
        else:
            latest.assert_awaited_once_with(row.source,row.trade_lane,row.container_type)
    assert state.context_state==expected
    sql=str(session.scalar.call_args.args[0])
    assert all('freight_rates.'+key in sql for key in ('source','trade_lane','container_type'))
    assert copied.generated_at==NOW
    assert not state.effective_live_decision_eligible

@pytest.mark.parametrize('age',[1,11,22])
def test_shared_freshness_and_no_promotion(age):
    cutoff=(NOW-timedelta(days=age)).date()
    status,_=DataQualityService.evaluate_freight_rate_freshness(cutoff,NOW)
    assert freshness_and_eligibility(cutoff,False,'current',NOW)==(status,False)
    assert freshness_and_eligibility(cutoff,True,'current',NOW)==(status,status in ('fresh','aging'))
    assert freshness_and_eligibility(cutoff,True,'superseded',NOW)==(status,False)

@pytest.mark.asyncio
async def test_infrastructure_failure_propagates():
    session=AsyncMock(); session.scalar.side_effect=RuntimeError('database unavailable')
    with pytest.raises(RuntimeError): await ForecastStateCollector(session).collect(snapshot_forecast(forecast()),NOW)

@pytest.mark.asyncio
async def test_snapshot_copy_and_exact_expected_series():
    from app.schemas.decision import SeriesIdentity
    row=forecast(); copied=snapshot_forecast(row)
    original=copied.predicted_rate
    row.predicted_rate+=1
    assert copied.predicted_rate==original
    session=AsyncMock(); session.scalar.return_value=row.latest_observation_date
    with patch('app.services.forecast_state.ForecastPersistenceService.get_latest_forecasts',new=AsyncMock(return_value=[row])):
        state=await ForecastStateCollector(session).collect(copied,NOW,
            expected_series=SeriesIdentity(source='other',trade_lane=row.trade_lane,container_type=row.container_type))
    assert not state.series_matches and state.context_state=='series_mismatch'

@pytest.mark.asyncio
async def test_database_exact_series_and_latest_order(db_session):
    from tests.test_grounded_rate_outlook import source_row
    from decimal import Decimal
    row=forecast(model_name='MA(3)')
    # Same cutoff and generation: lexical model name is the deterministic tie breaker.
    other=forecast(model_name='MA(4)')
    alien=forecast(source='OTHER',container='20ft',day=row.latest_observation_date+timedelta(days=10))
    db_session.add_all([row,other,alien,source_row(row),source_row(alien)])
    await db_session.commit()
    collector=ForecastStateCollector(db_session)
    current=await collector.collect(snapshot_forecast(row),NOW)
    assert current.context_state=='current' and current.latest_source_date==row.latest_observation_date
    loser=await collector.collect(snapshot_forecast(other),NOW)
    assert loser.forecast_superseded
    old=snapshot_forecast(row)
    row.generated_at+=timedelta(seconds=1)
    row.predicted_rate=Decimal('999')
    await db_session.commit()
    regenerated=await collector.collect(old,NOW)
    assert regenerated.forecast_superseded and old.predicted_rate!=row.predicted_rate
    assert (await collector.collect(snapshot_forecast(row),NOW)).context_state=='current'
    db_session.add(source_row(row,day=row.latest_observation_date+timedelta(days=1)))
    await db_session.commit()
    assert (await collector.collect(snapshot_forecast(row),NOW)).source_superseded

@pytest.mark.asyncio
@pytest.mark.parametrize('case',['current','missing','source','winner','generation','historical'])
async def test_committed_t07_context_parity(case):
    import subprocess
    from types import SimpleNamespace
    from app.services.rate_outlook import RateOutlookService
    baseline={}
    exec(compile(subprocess.check_output(['git','show','f9fd2a71164eab578454f89cc354c9857fd9575d:app/services/rate_outlook.py'],text=True),
        '<committed-t07>', 'exec'),baseline)
    row=forecast(); trend=SimpleNamespace(trade_lane=row.trade_lane,computed_date=row.latest_observation_date)
    if case=='historical': trend.computed_date-=timedelta(days=1)
    generation=row.generated_at-timedelta(seconds=1) if case=='generation' else row.generated_at
    source_date=None if case=='missing' else row.latest_observation_date+timedelta(days=case=='source')
    winner=forecast() if case=='winner' else row
    outcomes=[]
    for service in (baseline['RateOutlookService'],RateOutlookService):
        session=AsyncMock(); session.scalar.side_effect=[source_date,row.latest_observation_date]
        with patch('app.services.forecast_persistence.ForecastPersistenceService.get_latest_forecasts',new=AsyncMock(return_value=[winner])) as latest:
            outcomes.append(await service(session).context_state(trend,row,generation))
            if case in ('missing','source'): latest.assert_not_awaited()
    assert outcomes[0]==outcomes[1]

@pytest.mark.parametrize('status',['fresh','aging','stale','unknown'])
@pytest.mark.parametrize('eligible',[True,False])
def test_t07_effective_formula_parity(status,eligible):
    with patch.object(DataQualityService,'evaluate_freight_rate_freshness',return_value=(status,0)):
        for context in ('current','superseded','historical_trend','source_unavailable'):
            actual=freshness_and_eligibility(NOW.date(),eligible,context,NOW)
            assert actual==(status,eligible and status in ('fresh','aging') and context=='current')
