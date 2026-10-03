"""Deterministic T07 evidence, identity, degradation and HTTP regression coverage."""
import copy
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select, func
from app.models import RateTrend, RateForecast, RateOutlook, FreightRate
from app.services.rate_outlook import RateOutlookService
from app.tasks.rate_outlook_generation import generate_rate_outlook_async
from app.schemas.ai_outputs import GroundedRateOutlookOutput
from app.ai.rate_outlook_narrator import RateOutlookNarrator
from app.ai.openai_client import AITimeoutError, AIValidationError
from app.ai.budget_guard import AIBudgetExceededError, AIRateLimitExceededError

TEXT = "This historical baseline has limited evidence and is not eligible for live decisions."
pytestmark = pytest.mark.asyncio

def forecast(lane="T07-Lane", source="SCFI", container="40ft", day=None, **kwargs):
    day = day or date(2026, 1, 1)
    values = dict(id=uuid.uuid4(), source=source, trade_lane=lane, container_type=container,
        forecast_for_date=day+timedelta(days=1), predicted_rate=Decimal("101.03"), model_name="MA(3)",
        model_version="baseline-v1-decimal", forecast_horizon=1, latest_observation_date=day,
        latest_actual_rate=Decimal("100.01"), history_observations=31, evaluation_points=16,
        backtest_mae=2.1, backtest_rmse=3.2, backtest_smape=1.3, backtest_directional_accuracy=55.0,
        data_readiness="MINIMAL", input_freshness="fresh", live_decision_eligible=False,
        warning="Historical-only baseline.", generated_at=datetime(2026, 1, 2, tzinfo=timezone.utc))
    values.update(kwargs)
    return RateForecast(**values)

def source_row(row, day=None):
    return FreightRate(source=row.source, trade_lane=row.trade_lane, container_type=row.container_type,
        rate_date=day or row.latest_observation_date, rate_usd=row.latest_actual_rate,
        origin_port="Test", dest_region="Test")

@pytest.fixture
async def evidence(db_session):
    row=forecast()
    trend=RateTrend(id=uuid.uuid4(), trade_lane=row.trade_lane, computed_date=row.latest_observation_date,
        recommendation="book_now", confidence=99, outlook_text="Legacy advice", status="completed")
    db_session.add_all([row, trend, source_row(row)])
    await db_session.commit()
    return trend,row

def factory(session):
    @asynccontextmanager
    async def session_factory():
        yield session
    return session_factory

async def run_worker(session, row, narrator=None):
    narrator=narrator or AsyncMock()
    if narrator.narrate_grounded.return_value is None or isinstance(narrator.narrate_grounded.return_value, AsyncMock):
        narrator.narrate_grounded.return_value=GroundedRateOutlookOutput(outlook_text=TEXT)
    result=await generate_rate_outlook_async(str(row.id), session_factory=factory(session), narrator_factory=lambda:narrator)
    return result,narrator

async def test_explicit_and_auto_resolution_idempotent(db_session,evidence):
    trend,fc=evidence
    svc=RateOutlookService(db_session)
    explicit=await svc.create(trend.id,"SCFI","40ft")
    auto=await svc.create(trend.id)
    assert explicit.id==auto.id
    assert explicit.forecast_id==fc.id and explicit.trend_id==trend.id
    assert explicit.prompt_version=="v2"
    assert await db_session.scalar(select(func.count()).select_from(RateOutlook))==1

async def test_ambiguous_series_and_explicit_isolation(db_session,evidence):
    trend,fc=evidence
    other=forecast(container="20ft")
    db_session.add_all([other,source_row(other)])
    await db_session.commit()
    with pytest.raises(HTTPException) as exc: await RateOutlookService(db_session).create(trend.id)
    assert exc.value.status_code==409
    row=await RateOutlookService(db_session).create(trend.id,"SCFI","20ft")
    assert row.forecast_id==other.id

@pytest.mark.parametrize("source,container",[("MISSING","40ft"),("SCFI","20ft")])
async def test_missing_selection_does_not_create_job(db_session,evidence,source,container):
    trend,_=evidence
    with pytest.raises(HTTPException) as exc: await RateOutlookService(db_session).create(trend.id,source,container)
    assert exc.value.status_code==404
    assert await db_session.scalar(select(func.count()).select_from(RateOutlook))==0

async def test_partial_selection_rejected(db_session,evidence):
    with pytest.raises(HTTPException) as exc: await RateOutlookService(db_session).create(evidence[0].id,"SCFI")
    assert exc.value.status_code==422

async def test_evidence_decimal_and_model_preserved(db_session,evidence):
    trend,fc=evidence
    row=await RateOutlookService(db_session).create(trend.id)
    before=copy.deepcopy(row.evidence_snapshot)
    result,narrator=await run_worker(db_session,row)
    read=await RateOutlookService(db_session).read(row.id)
    assert result["status"]=="completed"
    assert read.exact_values.expected_change==Decimal("1.02")
    assert read.exact_values.expected_change_pct==Decimal("1.0199")
    assert read.exact_values.predicted_rate==fc.predicted_rate
    assert read.quantitative.forecast.model==fc.model_name
    assert read.quantitative.forecast.model_version==fc.model_version
    assert read.quantitative.evidence.mae==fc.backtest_mae
    assert read.quantitative.evidence.data_readiness=="MINIMAL"
    assert read.quantitative.provenance.current_input_freshness=="stale"
    assert read.quantitative.provenance.input_freshness_at_generation=="fresh"
    assert not read.effective_live_decision_eligible
    assert row.evidence_snapshot==before
    context=narrator.narrate_grounded.call_args.args[0]
    assert context["exact_values"]["predicted_rate"]=="101.03"
    assert context["provenance"]["current_input_freshness"]=="stale"
    assert not context["safety"]["live_decision_eligible"]
    await db_session.refresh(trend)
    assert trend.confidence==99 and trend.recommendation=="book_now" and trend.outlook_text=="Legacy advice"

@pytest.mark.parametrize("extra",["predicted_rate","confidence","recommendation","booking_probability","expected_change"])
async def test_gpt_cannot_add_authoritative_fields(extra):
    with pytest.raises(ValidationError): GroundedRateOutlookOutput.model_validate({"outlook_text":TEXT,extra:80})

async def test_prompt_v2_narrative_only_and_no_custom_temperature():
    client=MagicMock();client.generate_structured=AsyncMock(return_value=GroundedRateOutlookOutput(outlook_text=TEXT))
    narrator=RateOutlookNarrator(client)
    evidence={"forecast":{"predicted_rate":"101.03"},"safety":{"live_decision_eligible":False}}
    before=copy.deepcopy(evidence)
    output=await narrator.narrate_grounded(evidence)
    args=client.generate_structured.call_args.kwargs
    assert args["prompt_version"]=="v2" and args["temperature"]==1.0
    assert args["output_schema"]==GroundedRateOutlookOutput
    assert '101.03' in args["user_content"]
    assert "Never calculate, replace" in args["system_prompt"]
    assert evidence==before
    assert set(output.model_dump())=={"outlook_text"}

@pytest.mark.parametrize("fresh",[False,True])
async def test_superseded_no_azure_even_fresh_by_age(db_session,evidence,fresh):
    trend,fc=evidence
    if fresh:
        fc.latest_observation_date=date.today()-timedelta(days=1)
        fc.forecast_for_date=date.today()
        trend.computed_date=date.today()
        old=(await db_session.execute(select(FreightRate))).scalar_one()
        old.rate_date=fc.latest_observation_date
        await db_session.commit()
    row=await RateOutlookService(db_session).create(trend.id)
    db_session.add(source_row(fc,fc.latest_observation_date+timedelta(days=1)))
    await db_session.commit()
    narrator=AsyncMock()
    result,_=await run_worker(db_session,row,narrator)
    assert result["status"]=="unavailable"
    narrator.narrate_grounded.assert_not_awaited()
    read=await RateOutlookService(db_session).read(row.id)
    assert read.context_state=="superseded"
    if fresh: assert read.quantitative.provenance.current_input_freshness=="fresh"
    with pytest.raises(HTTPException) as exc: await RateOutlookService(db_session).create(trend.id)
    assert exc.value.status_code==409

async def test_other_series_source_does_not_supersede(db_session,evidence):
    trend,fc=evidence
    other=forecast(lane="Other",day=fc.latest_observation_date+timedelta(days=10))
    db_session.add(source_row(other))
    await db_session.commit()
    row=await RateOutlookService(db_session).create(trend.id)
    assert (await RateOutlookService(db_session).read(row.id)).context_state=="current"

async def test_historical_trend_conflict(db_session,evidence):
    trend,fc=evidence
    trend.computed_date=fc.latest_observation_date-timedelta(days=1)
    await db_session.commit()
    with pytest.raises(HTTPException) as exc: await RateOutlookService(db_session).create(trend.id)
    assert exc.value.status_code==409

async def test_older_trend_even_after_cutoff_conflict(db_session,evidence):
    trend,fc=evidence
    db_session.add(RateTrend(trade_lane=fc.trade_lane,computed_date=trend.computed_date+timedelta(days=1)))
    await db_session.commit()
    with pytest.raises(HTTPException) as exc: await RateOutlookService(db_session).create(trend.id)
    assert exc.value.status_code==409

async def test_model_version_tie_determinism(db_session,evidence):
    trend,fc=evidence
    other=forecast(model_version="baseline-v2",generated_at=fc.generated_at)
    db_session.add(other);await db_session.commit()
    row=await RateOutlookService(db_session).create(trend.id)
    assert row.forecast_id==fc.id
    other.generated_at=fc.generated_at+timedelta(seconds=1)
    await db_session.commit()
    newer=await RateOutlookService(db_session).create(trend.id)
    assert newer.forecast_id==other.id and newer.id!=row.id
    assert (await RateOutlookService(db_session).read(row.id)).context_state=="superseded"

async def test_same_forecast_regeneration_preserves_snapshot(db_session,evidence):
    trend,fc=evidence
    svc=RateOutlookService(db_session);row=await svc.create(trend.id)
    fc.predicted_rate=Decimal("999.99");fc.generated_at+=timedelta(seconds=1)
    await db_session.commit()
    newer=await svc.create(trend.id)
    assert newer.id!=row.id
    old=await svc.read(row.id)
    assert old.exact_values.predicted_rate==Decimal("101.03") and old.context_state=="superseded"

@pytest.mark.parametrize("error",[RuntimeError("secret diagnostic"),AIBudgetExceededError("budget"),AIRateLimitExceededError("rate"),AIValidationError("refusal"),AITimeoutError("timeout")])
async def test_narration_failures_preserve_evidence(db_session,evidence,error):
    row=await RateOutlookService(db_session).create(evidence[0].id)
    narrator=AsyncMock();narrator.narrate_grounded.side_effect=error
    result,_=await run_worker(db_session,row,narrator)
    assert result["status"]=="failed"
    read=await RateOutlookService(db_session).read(row.id)
    assert read.exact_values.predicted_rate==Decimal("101.03")
    assert read.narration.text is None and "secret diagnostic" not in read.narration.error_message
    await run_worker(db_session,row,narrator)
    assert narrator.narrate_grounded.await_count==1

async def test_invalid_structured_worker_output_fails(db_session,evidence):
    row=await RateOutlookService(db_session).create(evidence[0].id)
    narrator=AsyncMock();narrator.narrate_grounded.return_value={"outlook_text":TEXT,"confidence":99}
    result,_=await run_worker(db_session,row,narrator)
    assert result["status"]=="failed"
    assert (await RateOutlookService(db_session).read(row.id)).exact_values.predicted_rate==Decimal("101.03")

async def test_persisted_reuse_validates_and_never_reads_legacy_redis(db_session,evidence,monkeypatch):
    from app import redis_client
    redis=AsyncMock();redis.get.return_value='{"outlook_text":"legacy", "confidence":99}'
    monkeypatch.setattr(redis_client,"get_redis",lambda:redis)
    row=await RateOutlookService(db_session).create(evidence[0].id)
    _,narrator=await run_worker(db_session,row)
    await run_worker(db_session,row,narrator)
    narrator.narrate_grounded.assert_awaited_once()
    redis.get.assert_not_awaited();redis.setex.assert_not_awaited()
    row.outlook_text="bad";await db_session.commit()
    read=await RateOutlookService(db_session).read(row.id)
    assert read.narration.status=="failed" and read.narration.text is None
    assert read.exact_values.predicted_rate==Decimal("101.03")

async def test_post_and_read_contract_and_queue_identity(db_session,evidence,authenticated_client,monkeypatch):
    from app.routers import rates
    queue=MagicMock();monkeypatch.setattr(rates.generate_rate_outlook,"delay",queue)
    trend,fc=evidence
    response=await authenticated_client.post(f"/api/v1/rates/trends/{trend.id}/outlook?source=SCFI&container_type=40ft")
    assert response.status_code==202
    payload=response.json();queue.assert_called_once_with(payload["outlook_id"])
    assert payload["forecast_id"]==str(fc.id) and payload["trend_id"]==str(trend.id)
    read=await authenticated_client.get('/api/v1/rates/outlooks/'+payload['outlook_id'])
    assert read.status_code==200
    data=read.json()
    assert data['quantitative']['evidence']['data_readiness']=='MINIMAL'
    assert data['exact_values']['predicted_rate']=='101.03'
    assert data['narration']['status']=='pending'
    assert 'confidence' not in data and 'recommendation' not in data

async def test_http_missing_forecast_no_queue(db_session,evidence,authenticated_client,monkeypatch):
    from app.routers import rates
    queue=MagicMock();monkeypatch.setattr(rates.generate_rate_outlook,"delay",queue)
    response=await authenticated_client.post(f'/api/v1/rates/trends/{evidence[0].id}/outlook?source=Other&container_type=40ft')
    assert response.status_code==404 and 'error' in response.json()
    queue.assert_not_called()

async def test_enqueue_failure_evidence_available(db_session,evidence,authenticated_client,monkeypatch):
    from app.routers import rates
    monkeypatch.setattr(rates.generate_rate_outlook,"delay",MagicMock(side_effect=RuntimeError("private")))
    response=await authenticated_client.post(f'/api/v1/rates/trends/{evidence[0].id}/outlook')
    assert response.status_code==202 and response.json()['status']=='failed'
    read=await authenticated_client.get('/api/v1/rates/outlooks/'+response.json()['outlook_id'])
    assert read.status_code==200 and read.json()['exact_values']['predicted_rate']=='101.03'
    assert 'private' not in read.text

async def test_auth_and_rate_limit_regression(db_session,evidence,client,authenticated_client,monkeypatch):
    from app.auth import rate_limit
    trend,_=evidence;row=await RateOutlookService(db_session).create(trend.id)
    for method,path in [('post',f'/api/v1/rates/trends/{trend.id}/outlook'),('get',f'/api/v1/rates/outlooks/{row.id}')]:
        response=await getattr(client,method)(path)
        assert response.status_code==401
    redis=AsyncMock();redis.incr.return_value=101
    monkeypatch.setattr(rate_limit,'get_redis',lambda:redis)
    for method,path in [('post',f'/api/v1/rates/trends/{trend.id}/outlook'),('get',f'/api/v1/rates/outlooks/{row.id}')]:
        response=await getattr(authenticated_client,method)(path)
        assert response.status_code==429

async def test_freshness_does_not_promote_model(db_session,evidence):
    trend,fc=evidence;day=date.today()
    fc.latest_observation_date=day;fc.forecast_for_date=day+timedelta(days=1);trend.computed_date=day
    rate=(await db_session.execute(select(FreightRate))).scalar_one();rate.rate_date=day
    await db_session.commit()
    row=await RateOutlookService(db_session).create(trend.id)
    read=await RateOutlookService(db_session).read(row.id)
    assert read.quantitative.provenance.current_input_freshness=='fresh'
    assert not read.effective_live_decision_eligible

async def test_worker_rechecks_supersession_during_azure(db_session,evidence):
    trend,fc=evidence;row=await RateOutlookService(db_session).create(trend.id)
    async def advance(*args):
        db_session.add(source_row(fc,fc.latest_observation_date+timedelta(days=1)))
        await db_session.commit()
        return GroundedRateOutlookOutput(outlook_text=TEXT)
    narrator=AsyncMock();narrator.narrate_grounded.side_effect=advance
    result,_=await run_worker(db_session,row,narrator)
    assert result['status']=='unavailable' and row.outlook_text is None

async def test_prompt_generation_and_series_reuse_isolation(db_session,evidence,monkeypatch):
    import app.services.rate_outlook as service
    trend,fc=evidence
    first=await RateOutlookService(db_session).create(trend.id)
    monkeypatch.setattr(service,'PROMPT_VERSION','v2-review-test')
    second=await RateOutlookService(db_session).create(trend.id)
    assert second.id!=first.id and second.forecast_id==first.forecast_id
    other=forecast(container='20ft')
    db_session.add_all([other,source_row(other)]);await db_session.commit()
    third=await RateOutlookService(db_session).create(trend.id,'SCFI','20ft')
    assert third.id!=second.id and third.forecast_id==other.id

async def test_source_unavailable_no_narration(db_session,evidence):
    from sqlalchemy import delete
    row=await RateOutlookService(db_session).create(evidence[0].id)
    await db_session.execute(delete(FreightRate));await db_session.commit()
    narrator=AsyncMock();result,_=await run_worker(db_session,row,narrator)
    assert result['status']=='unavailable'
    narrator.narrate_grounded.assert_not_awaited()
    assert (await RateOutlookService(db_session).read(row.id)).context_state=='source_unavailable'

async def test_legacy_read_never_exposes_old_ai_advice(db_session,evidence,authenticated_client):
    trend,fc=evidence
    trend.computed_date=date.today()
    rate=(await db_session.execute(select(FreightRate))).scalar_one();rate.rate_date=date.today()
    await db_session.commit()
    response=await authenticated_client.get('/api/v1/rates/'+trend.trade_lane)
    assert response.status_code==200
    legacy=response.json()['trend']
    assert legacy['confidence'] is None and legacy['recommendation'] is None and legacy['outlook_text'] is None
    assert legacy['status']=='none' and legacy['error_message'] is None

async def test_additive_migration_matches_model_and_scoped_downgrade(db_session):
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import text,inspect
    from sqlalchemy.ext.asyncio import create_async_engine
    from app.config import settings
    file=Path(__file__).resolve().parents[1]/'alembic/versions/b2c3d4e5f6a7_add_rate_outlooks_table.py'
    spec=importlib.util.spec_from_file_location('t07_migration',file)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    assert module.revision=='b2c3d4e5f6a7' and module.down_revision=='a1b2c3d4e5f6'
    schema='t07_'+uuid.uuid4().hex
    def apply(conn,operation):
        with Operations.context(MigrationContext.configure(conn)): operation()
    def verify(conn):
        inspector=inspect(conn)
        actual={c['name']:c for c in inspector.get_columns('rate_outlooks',schema=schema)}
        expected=RateOutlook.__table__.columns
        assert set(actual)==set(expected.keys())
        for c in expected:
            assert actual[c.name]['nullable']==c.nullable
            assert actual[c.name]['type']._type_affinity is c.type._type_affinity
        uniques=inspector.get_unique_constraints('rate_outlooks',schema=schema)
        assert [(u['name'],u['column_names']) for u in uniques]==[('uq_rate_outlook_generation',['trend_id','forecast_id','forecast_generated_at','prompt_version'])]
        indexes={i['name']:i['column_names'] for i in inspector.get_indexes('rate_outlooks',schema=schema) if not i.get('duplicates_constraint')}
        assert indexes=={'idx_outlook_trend':['trend_id'],'idx_outlook_forecast':['forecast_id']}
        fks=inspector.get_foreign_keys('rate_outlooks',schema=schema)
        assert {(fk['constrained_columns'][0],fk['referred_table']) for fk in fks}=={('trend_id','rate_trends'),('forecast_id','rate_forecasts')}
    engine=create_async_engine(settings.DATABASE_URL)
    try:
        async with engine.connect() as conn:
            transaction=await conn.begin()
            try:
                await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
                await conn.execute(text(f'SET LOCAL search_path TO "{schema}"'))
                await conn.execute(text('CREATE TABLE rate_trends (id UUID PRIMARY KEY)'))
                await conn.execute(text('CREATE TABLE rate_forecasts (id UUID PRIMARY KEY)'))
                trend_id,fc_id=uuid.uuid4(),uuid.uuid4()
                await conn.execute(text('INSERT INTO rate_trends VALUES (:id)'),{'id':trend_id})
                await conn.execute(text('INSERT INTO rate_forecasts VALUES (:id)'),{'id':fc_id})
                await conn.run_sync(lambda sync:apply(sync,module.upgrade))
                await conn.run_sync(verify)
                for prompt in ['v2','v3-test']:
                    await conn.execute(text("INSERT INTO rate_outlooks (id,trend_id,forecast_id,forecast_generated_at,prompt_version,evidence_snapshot) VALUES (:id,:trend,:forecast,now(),:prompt,'{}')"),{'id':uuid.uuid4(),'trend':trend_id,'forecast':fc_id,'prompt':prompt})
                assert await conn.scalar(text('SELECT count(*) FROM rate_outlooks'))==2
                await conn.run_sync(lambda sync:apply(sync,module.downgrade))
                assert await conn.scalar(text("SELECT to_regclass('rate_outlooks')")) is None
                assert await conn.scalar(text('SELECT count(*) FROM rate_trends'))==1
                assert await conn.scalar(text('SELECT count(*) FROM rate_forecasts'))==1
                await conn.run_sync(lambda sync:apply(sync,module.upgrade))
                await conn.run_sync(verify)
            finally: await transaction.rollback()
    finally: await engine.dispose()

async def test_v2_ignores_legacy_configuration_and_rejects_v1(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings,'AI_RATE_OUTLOOK_PROMPT_VERSION','v1')
    client=MagicMock();client.generate_structured=AsyncMock(return_value=GroundedRateOutlookOutput(outlook_text=TEXT))
    narrator=RateOutlookNarrator(client,prompt_version='v1')
    await narrator.narrate_grounded({'forecast':{'predicted_rate':'101.03'}})
    assert client.generate_structured.call_args.kwargs['prompt_version']=='v2'
    client.generate_structured.reset_mock()
    with pytest.raises(AIValidationError): await narrator.narrate_grounded({},'v1')
    client.generate_structured.assert_not_awaited()

async def test_missing_v2_registry_does_not_fallback(monkeypatch):
    from app.ai.prompts import registry,PromptVersionNotFoundError
    monkeypatch.setitem(registry._prompts,'rate_outlook',{'v1':registry.get_prompt('rate_outlook','v1')})
    client=MagicMock();client.generate_structured=AsyncMock()
    with pytest.raises(PromptVersionNotFoundError): await RateOutlookNarrator(client).narrate_grounded({})
    client.generate_structured.assert_not_awaited()

async def test_worker_rejects_non_v2_artifact(db_session,evidence):
    row=await RateOutlookService(db_session).create(evidence[0].id)
    row.prompt_version='v1';await db_session.commit()
    narrator=AsyncMock();result,_=await run_worker(db_session,row,narrator)
    assert result['status']=='failed' and row.failure_code=='validation'
    narrator.narrate_grounded.assert_not_awaited()

async def test_explicit_transient_retry_same_identity_bounded(db_session,evidence):
    svc=RateOutlookService(db_session);row=await svc.create(evidence[0].id)
    original=copy.deepcopy(row.evidence_snapshot)
    narrator=AsyncMock();narrator.narrate_grounded.side_effect=AITimeoutError('private')
    await run_worker(db_session,row,narrator)
    assert row.attempt_count==1
    assert (await svc.read(row.id)).narration.retryable
    # Default POST never retries; explicit immediate retry respects cooldown.
    assert (await svc.create(evidence[0].id)).status=='failed'
    assert (await svc.create(evidence[0].id,retry=True)).status=='failed'
    for expected in [2,3]:
        row.retry_after=datetime.now(timezone.utc)-timedelta(seconds=1)
        await db_session.commit()
        reused=await svc.create(evidence[0].id,retry=True)
        assert reused.id==row.id and reused.status=='pending'
        await run_worker(db_session,row,narrator)
        assert row.attempt_count==expected
    row.retry_after=datetime.now(timezone.utc)-timedelta(seconds=1);await db_session.commit()
    assert (await svc.create(evidence[0].id,retry=True)).status=='failed'
    assert not (await svc.read(row.id)).narration.retryable
    assert row.evidence_snapshot==original
    assert narrator.narrate_grounded.await_count==3
    assert await db_session.scalar(select(func.count()).select_from(RateOutlook))==1

async def test_transient_retry_can_complete_after_recovery(db_session,evidence,authenticated_client,monkeypatch):
    from app.routers import rates
    svc=RateOutlookService(db_session);row=await svc.create(evidence[0].id)
    narrator=AsyncMock();narrator.narrate_grounded.side_effect=AITimeoutError('private')
    await run_worker(db_session,row,narrator)
    row.retry_after=datetime.now(timezone.utc)-timedelta(seconds=1);await db_session.commit()
    queue=MagicMock();monkeypatch.setattr(rates.generate_rate_outlook,'delay',queue)
    response=await authenticated_client.post(f'/api/v1/rates/trends/{evidence[0].id}/outlook?retry=true')
    assert response.status_code==202 and response.json()['outlook_id']==str(row.id)
    queue.assert_called_once_with(str(row.id))
    narrator.narrate_grounded.side_effect=None
    narrator.narrate_grounded.return_value=GroundedRateOutlookOutput(outlook_text=TEXT)
    result,_=await run_worker(db_session,row,narrator)
    assert result['status']=='completed' and row.attempt_count==2
    assert (await svc.create(evidence[0].id,retry=True)).status=='completed'
    await run_worker(db_session,row,narrator)
    assert narrator.narrate_grounded.await_count==2

@pytest.mark.parametrize('error',[AIBudgetExceededError('private'),AIRateLimitExceededError('private'),AIValidationError('private')])
async def test_budget_and_validation_never_requeue(db_session,evidence,authenticated_client,monkeypatch,error):
    from app.routers import rates
    svc=RateOutlookService(db_session);row=await svc.create(evidence[0].id)
    narrator=AsyncMock();narrator.narrate_grounded.side_effect=error
    await run_worker(db_session,row,narrator)
    queue=MagicMock();monkeypatch.setattr(rates.generate_rate_outlook,'delay',queue)
    for _ in range(2):
        response=await authenticated_client.post(f'/api/v1/rates/trends/{evidence[0].id}/outlook?retry=true')
        assert response.status_code==202 and response.json()['status']=='failed'
        await run_worker(db_session,row,narrator)
    queue.assert_not_called()
    assert narrator.narrate_grounded.await_count==1 and row.attempt_count==1
    assert not (await svc.read(row.id)).narration.retryable

async def test_pending_generating_and_completed_reuse(db_session,evidence):
    svc=RateOutlookService(db_session);row=await svc.create(evidence[0].id)
    for status in ['pending','generating','completed']:
        row.status=status;await db_session.commit()
        reused=await svc.create(evidence[0].id,retry=True)
        assert reused.id==row.id and reused.status==status and reused.attempt_count==0

async def test_concurrent_duplicate_worker_does_not_call_azure(db_session,evidence):
    import asyncio
    from sqlalchemy.ext.asyncio import async_sessionmaker
    row=await RateOutlookService(db_session).create(evidence[0].id)
    started=asyncio.Event();release=asyncio.Event()
    async def hold(*args):
        started.set();await release.wait()
        return GroundedRateOutlookOutput(outlook_text=TEXT)
    narrator=AsyncMock();narrator.narrate_grounded.side_effect=hold
    first=asyncio.create_task(run_worker(db_session,row,narrator))
    await asyncio.wait_for(started.wait(),5)
    second_narrator=AsyncMock()
    try:
        sessions=async_sessionmaker(db_session.bind,expire_on_commit=False)
        result=await generate_rate_outlook_async(str(row.id),session_factory=sessions,narrator_factory=lambda:second_narrator)
        assert result['status']=='generating'
        second_narrator.narrate_grounded.assert_not_awaited()
    finally:
        release.set();await first
    assert row.attempt_count==1 and narrator.narrate_grounded.await_count==1

async def test_old_queued_trend_uuid_rejected_without_mutation(db_session,evidence):
    trend,_=evidence
    row=await RateOutlookService(db_session).create(trend.id)
    before=copy.deepcopy(row.evidence_snapshot)
    narrator=AsyncMock()
    with pytest.raises(ValueError,match='legacy trend jobs'):
        await generate_rate_outlook_async(str(trend.id),session_factory=factory(db_session),narrator_factory=lambda:narrator)
    narrator.narrate_grounded.assert_not_awaited()
    await db_session.refresh(row);await db_session.refresh(trend)
    assert row.status=='pending' and row.evidence_snapshot==before
    assert trend.confidence==99 and trend.recommendation=='book_now'

async def test_completed_narration_input_immutable_after_forecast_mutation(db_session,evidence):
    trend,fc=evidence;svc=RateOutlookService(db_session);row=await svc.create(trend.id)
    _,narrator=await run_worker(db_session,row)
    original=copy.deepcopy(row.evidence_snapshot)
    actual_input=copy.deepcopy(row.narration_input)
    assert actual_input==narrator.narrate_grounded.call_args.args[0]
    fc.predicted_rate=Decimal('999.99');fc.latest_actual_rate=Decimal('800.00')
    fc.model_name='MA(4)';fc.model_version='modified';fc.backtest_mae=88
    fc.backtest_rmse=99;fc.backtest_smape=90;fc.backtest_directional_accuracy=100
    fc.history_observations=100;fc.evaluation_points=80;fc.data_readiness='OTHER'
    fc.input_freshness='stale';fc.live_decision_eligible=True;fc.warning='changed'
    fc.generated_at+=timedelta(seconds=1);await db_session.commit()
    read=await svc.read(row.id)
    assert read.context_state=='superseded' and not read.effective_live_decision_eligible
    assert read.narration.text==TEXT and read.narration.input_evidence==actual_input
    assert row.evidence_snapshot==original
    assert read.exact_values.predicted_rate==Decimal('101.03')
    assert read.exact_values.latest_actual_rate==Decimal('100.01')
    assert read.exact_values.expected_change==Decimal('1.02')
    assert read.quantitative.forecast.model=='MA(3)'
    assert read.quantitative.forecast.model_version=='baseline-v1-decimal'
    assert read.quantitative.evidence.mae==2.1 and read.quantitative.evidence.rmse==3.2
    assert read.quantitative.evidence.smape==1.3 and read.quantitative.evidence.directional_accuracy==55
    assert read.quantitative.evidence.data_readiness=='MINIMAL'
    assert read.quantitative.provenance.input_freshness_at_generation=='fresh'
    assert not read.quantitative.safety.live_decision_eligible

async def test_exact_source_and_container_recency_isolation(db_session,evidence):
    trend,fc=evidence
    for other in [forecast(source='OTHER'),forecast(container='20ft')]:
        db_session.add(source_row(other,fc.latest_observation_date+timedelta(days=30)))
    await db_session.commit()
    row=await RateOutlookService(db_session).create(trend.id,'SCFI','40ft')
    assert (await RateOutlookService(db_session).read(row.id)).context_state=='current'
