"""Real isolated PostgreSQL persistence, race, rollback and migration tests."""
import asyncio
import importlib.util
import uuid
from pathlib import Path
from decimal import Decimal
from datetime import date, timedelta
import pytest
from pydantic import ValidationError
from sqlalchemy import select, func, event, text, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.forecast_evaluation import EvaluationRun, EvaluationObservation, EvaluationPoint
from app.models.freight_rate import FreightRate
from app.schemas.forecast_evaluation import EvaluationConfig, Phase
from app.services.forecast_evaluation import evaluate, aggregate
from app.services.forecast_evaluation_persistence import EvaluationPersistenceService, EvaluationIntegrityError
from tests.test_forecast_evaluation import snapshot

pytestmark = pytest.mark.asyncio


async def counts(session):
    return tuple([await session.scalar(select(func.count()).select_from(m))
        for m in (EvaluationRun, EvaluationObservation, EvaluationPoint)])


async def test_complete_reload_exact_snapshot_and_aggregate(db_session):
    result = evaluate(snapshot()); service = EvaluationPersistenceService(db_session)
    stored = await service.persist(result)
    assert await counts(db_session) == (1, 31, 92)
    await db_session.commit()
    async with AsyncSession(bind=db_session.bind, expire_on_commit=False) as second:
        loaded = await EvaluationPersistenceService(second).load(stored.id)
        assert loaded.result == result
        assert all(type(o.rate) is Decimal for o in loaded.result.input_snapshot.observations)
        assert loaded.created_at.tzinfo is not None
        for candidate in loaded.result.candidate_summaries:
            points = [p for p in loaded.result.points if p.protocol_phase == Phase.SELECTION_WINDOW and p.candidate_name == candidate.candidate_name]
            assert aggregate(points) == candidate.metrics
        assert aggregate([p for p in loaded.result.points if p.protocol_phase == Phase.NESTED_OUTER]) == loaded.result.outer_metrics


async def test_idempotency_conflicting_evidence_and_correction(db_session):
    s = snapshot(); r = evaluate(s); service = EvaluationPersistenceService(db_session)
    a = await service.persist(r)
    b = await service.persist(r)
    assert a.id == b.id and await counts(db_session) == (1, 31, 92)
    bad = r.model_copy(update={'final_champion': 'Naive' if r.final_champion != 'Naive' else 'Drift'})
    with pytest.raises(EvaluationIntegrityError):
        await service.persist(bad)
    assert (await service.load(a.id)).result == r
    obs = list(s.observations); obs[-1] = obs[-1].model_copy(update={'rate': Decimal('123.45')})
    corrected = await service.persist(evaluate(s.model_copy(update={'observations': tuple(obs)})))
    changed_config = await service.persist(evaluate(s, EvaluationConfig(minimum_inner_evaluation_points=5)))
    assert len({a.id, corrected.id, changed_config.id}) == 3
    assert (await service.load(a.id)).result == r


async def test_caller_rollback_and_no_hidden_commit(db_session):
    stored = await EvaluationPersistenceService(db_session).persist(evaluate(snapshot()))
    async with AsyncSession(bind=db_session.bind) as second:
        assert await second.get(EvaluationRun, stored.id) is None
    await db_session.rollback()
    assert await counts(db_session) == (0, 0, 0)


@pytest.mark.parametrize('child', [EvaluationObservation, EvaluationPoint])
async def test_mid_child_failure_rolls_back_only_artifact(db_session, child):
    source = FreightRate(source='S', trade_lane='L', container_type='C', origin_port='P',
        dest_region='R', rate_date=date(2026, 1, 1), rate_usd=Decimal('100.01'))
    db_session.add(source)
    def fail(*args):
        raise RuntimeError('injected child failure')
    event.listen(child, 'before_insert', fail)
    try:
        with pytest.raises(RuntimeError):
            await EvaluationPersistenceService(db_session).persist(evaluate(snapshot()))
    finally:
        event.remove(child, 'before_insert', fail)
    assert await counts(db_session) == (0, 0, 0)
    assert await db_session.get(FreightRate, source.id) is not None
    await db_session.rollback()


async def test_concurrent_same_identity(db_session):
    r = evaluate(snapshot())
    async def worker():
        async with AsyncSession(bind=db_session.bind, expire_on_commit=False) as session:
            stored = await EvaluationPersistenceService(session).persist(r)
            await session.commit()
            return stored.id
    a, b = await asyncio.wait_for(asyncio.gather(worker(), worker()), timeout=15)
    assert a == b and await counts(db_session) == (1, 31, 92)


@pytest.mark.parametrize('kind', ['run', 'ordinal', 'date', 'point'])
async def test_database_unique_constraints(db_session, kind):
    stored = await EvaluationPersistenceService(db_session).persist(evaluate(snapshot()))
    table = {'run': EvaluationRun, 'ordinal': EvaluationObservation,
        'date': EvaluationObservation, 'point': EvaluationPoint}[kind]
    row = (await db_session.execute(select(table))).scalars().first()
    values = {c.name: getattr(row, c.name) for c in table.__table__.columns if c.name != 'id'}
    if kind == 'ordinal':
        values['observation_date'] += timedelta(days=100)
    if kind == 'date':
        values['ordinal'] = 100
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(table(**values))
            await db_session.flush()
    assert (await EvaluationPersistenceService(db_session).load(stored.id)).result == evaluate(snapshot())


@pytest.mark.parametrize('model', [EvaluationRun, EvaluationObservation, EvaluationPoint])
@pytest.mark.parametrize('action', ['update', 'delete'])
async def test_orm_append_only(db_session, model, action):
    await EvaluationPersistenceService(db_session).persist(evaluate(snapshot()))
    row = (await db_session.execute(select(model))).scalars().first()
    with pytest.raises(ValueError, match='append-only'):
        async with db_session.begin_nested():
            if action == 'delete':
                await db_session.delete(row)
            elif model is EvaluationRun:
                row.provenance = 'Other'
            elif model is EvaluationObservation:
                row.rate = Decimal('1.23')
            else:
                row.prediction = 999
            await db_session.flush()


@pytest.mark.parametrize('value', ['NaN', 'Infinity', '-Infinity', '1.001', '100000000'])
async def test_invalid_snapshot_never_persisted(db_session, value):
    with pytest.raises((EvaluationIntegrityError, ValidationError)):
        await EvaluationPersistenceService(db_session).persist(evaluate(snapshot([value] * 31)))
    assert await counts(db_session) == (0, 0, 0)


@pytest.mark.parametrize('field', ['rate', 'prediction'])
async def test_database_nonfinite_check(db_session, field):
    await EvaluationPersistenceService(db_session).persist(evaluate(snapshot()))
    table = EvaluationObservation.__tablename__ if field == 'rate' else EvaluationPoint.__tablename__
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.execute(text(f"UPDATE {table} SET {field} = 'NaN'"))


async def test_extract_exact_series_cutoff_without_autoflush(db_session):
    for source, lane, container, day in [('S', 'L', 'C', 2), ('S', 'L', 'C', 1),
        ('OTHER', 'L', 'C', 1), ('S', 'OTHER', 'C', 1), ('S', 'L', 'OTHER', 1)]:
        db_session.add(FreightRate(source=source, trade_lane=lane, container_type=container,
            origin_port='P', dest_region='R', rate_date=date(2026, 1, day), rate_usd=Decimal('100.01')))
    await db_session.commit()
    pending = FreightRate(source='PENDING', trade_lane='L', container_type='C', origin_port='P',
        dest_region='R', rate_date=date(2026, 1, 1), rate_usd=Decimal('1'))
    db_session.add(pending)
    extracted = await EvaluationPersistenceService(db_session).extract('S', 'L', 'C', date(2026, 1, 1))
    assert len(extracted.observations) == 1 and extracted.observations[0].rate == Decimal('100.01')
    assert pending in db_session.new
    assert extracted.provenance.value == 'UNVERIFIED'


async def test_flat_and_insufficient_completed_artifacts(db_session):
    service = EvaluationPersistenceService(db_session)
    for n in (0, 15, 16, 31):
        original = evaluate(snapshot([0] * n))
        stored = await service.persist(original)
        assert (await service.load(stored.id)).result == original
        assert original.outer_metrics.directional_accuracy is None


async def test_corrupt_storage_is_not_silently_reused(db_session):
    service = EvaluationPersistenceService(db_session); r = evaluate(snapshot())
    stored = await service.persist(r)
    # Raw administrative SQL bypasses ORM protection; loader detects corruption.
    await db_session.execute(text('UPDATE forecast_evaluation_points SET prediction = prediction + 1'))
    with pytest.raises(EvaluationIntegrityError):
        await service.persist(r)


async def test_migration_upgrade_downgrade_and_model_parity(db_session):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    file = Path(__file__).resolve().parents[1] / 'alembic/versions/c3d4e5f6a7b8_add_forecast_evaluation_tables.py'
    spec = importlib.util.spec_from_file_location('t11_migration', file)
    migration = importlib.util.module_from_spec(spec); spec.loader.exec_module(migration)
    assert migration.revision == 'c3d4e5f6a7b8' and migration.down_revision == 'b2c3d4e5f6a7'
    schema = 't11_' + uuid.uuid4().hex
    artifact = await EvaluationPersistenceService(db_session).persist(evaluate(snapshot()))
    await db_session.commit()
    def exercise(connection):
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
        connection.execute(text('CREATE TABLE sentinel (id INTEGER PRIMARY KEY)'))
        connection.execute(text('INSERT INTO sentinel VALUES (123)'))
        with Operations.context(MigrationContext.configure(connection)):
            scripts = ScriptDirectory.from_config(Config('alembic.ini'))
            for previous in reversed(list(scripts.walk_revisions(base='base', head=migration.down_revision))):
                previous.module.upgrade()
            baseline_tables = set(inspect(connection).get_table_names(schema=schema))
            assert 'rate_forecasts' in baseline_tables and 'rate_outlooks' in baseline_tables
            migration.upgrade()
            inspector = inspect(connection)
            for model in (EvaluationRun, EvaluationObservation, EvaluationPoint):
                name = model.__tablename__
                columns = {c['name']: c for c in inspector.get_columns(name, schema=schema)}
                assert set(columns) == set(model.__table__.columns.keys())
                for col in model.__table__.columns:
                    actual = columns[col.name]
                    assert actual['nullable'] == col.nullable
                    assert actual['type']._type_affinity == col.type._type_affinity
                    assert (actual['default'] is not None) == (col.server_default is not None)
                    if col.server_default is not None:
                        assert actual['default'] == str(col.server_default.arg)
                    if hasattr(col.type, 'scale'):
                        assert (actual['type'].precision, actual['type'].scale) == (col.type.precision, col.type.scale)
                expected_unique = {c.name: list(c.columns.keys()) for c in model.__table__.constraints if type(c).__name__ == 'UniqueConstraint'}
                assert {c['name']: c['column_names'] for c in inspector.get_unique_constraints(name, schema=schema)} == expected_unique
                expected_indexes = {i.name: list(i.columns.keys()) for i in model.__table__.indexes}
                assert {i['name']: i['column_names'] for i in inspector.get_indexes(name, schema=schema) if not i.get('duplicates_constraint')} == expected_indexes
                for index in inspector.get_indexes(name, schema=schema):
                    if index['name'] == 'uq_evaluation_outer_target':
                        assert index['unique'] is True
                        assert 'NESTED_OUTER' in str(index['dialect_options']['postgresql_where'])
                assert {c['name'] for c in inspector.get_check_constraints(name, schema=schema)} == {
                    c.name for c in model.__table__.constraints if type(c).__name__ == 'CheckConstraint'}
                if model is not EvaluationRun:
                    fk = inspector.get_foreign_keys(name, schema=schema)[0]
                    assert fk['referred_table'] == EvaluationRun.__tablename__
                    assert fk['constrained_columns'] == ['run_id'] and fk['referred_columns'] == ['id']
                    assert fk['options']['ondelete'] == 'CASCADE'
                columns_sql = ', '.join(model.__table__.columns.keys())
                connection.execute(text(f'INSERT INTO {name} ({columns_sql}) SELECT {columns_sql} FROM public.{name}'))
            assert connection.scalar(text('SELECT count(*) FROM forecast_evaluation_points')) == 92
            migration.downgrade()
            assert set(inspect(connection).get_table_names(schema=schema)) == baseline_tables
            assert connection.scalar(text('SELECT id FROM sentinel')) == 123
            assert connection.scalar(text('SELECT count(*) FROM public.forecast_evaluation_runs WHERE id = :id'), {'id': artifact.id}) == 1
    async with db_session.bind.connect() as connection:
        transaction = await connection.begin()
        try:
            await connection.run_sync(exercise)
        finally:
            await transaction.rollback()


async def test_date_correction_and_unsupported_version_identity(db_session):
    s = snapshot(); service = EvaluationPersistenceService(db_session)
    original = await service.persist(evaluate(s))
    obs = list(s.observations)
    obs[-1] = obs[-1].model_copy(update={'observation_date': date(2026, 2, 2)})
    corrected = await service.persist(evaluate(s.model_copy(update={'observations': tuple(obs)})))
    unsupported = await service.persist(evaluate(s, EvaluationConfig(evaluation_version='future-evaluation')))
    assert len({original.id, corrected.id, unsupported.id}) == 3
    assert (await service.load(unsupported.id)).result.selection_status.value == 'UNSUPPORTED'
    assert (await service.load(original.id)).result == evaluate(s)


async def test_numeric_representation_idempotency(db_session):
    service = EvaluationPersistenceService(db_session)
    a = await service.persist(evaluate(snapshot(['100.00'] * 31)))
    b = await service.persist(evaluate(snapshot(['1e2'] * 31)))
    assert a.id == b.id


async def test_missing_child_detected_on_reload(db_session):
    service = EvaluationPersistenceService(db_session)
    stored = await service.persist(evaluate(snapshot()))
    await db_session.execute(text('DELETE FROM forecast_evaluation_observations WHERE ordinal = 0'))
    with pytest.raises(EvaluationIntegrityError):
        await service.load(stored.id)


async def test_outer_target_unique_across_different_candidates(db_session):
    stored = await EvaluationPersistenceService(db_session).persist(evaluate(snapshot()))
    row = (await db_session.execute(select(EvaluationPoint).where(
        EvaluationPoint.protocol_phase == 'NESTED_OUTER'))).scalars().first()
    values = {c.name: getattr(row, c.name) for c in EvaluationPoint.__table__.columns if c.name != 'id'}
    values['candidate_name'] = 'Naive' if row.candidate_name != 'Naive' else 'Drift'
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(EvaluationPoint(**values)); await db_session.flush()
    assert (await EvaluationPersistenceService(db_session).load(stored.id)).result == evaluate(snapshot())


async def test_duplicate_outer_result_rejected_before_writing(db_session):
    r = evaluate(snapshot())
    outer = next(p for p in r.points if p.protocol_phase == Phase.NESTED_OUTER)
    extra = outer.model_copy(update={'candidate_name': 'Naive' if outer.candidate_name != 'Naive' else 'Drift'})
    with pytest.raises(EvaluationIntegrityError):
        await EvaluationPersistenceService(db_session).persist(r.model_copy(update={'points': r.points + (extra,)}))
    assert await counts(db_session) == (0, 0, 0)


@pytest.mark.parametrize('kind', ['point', 'observation', 'header', 'phase', 'inner', 'config'])
async def test_direct_sql_corruption_with_retained_identity_map(db_session, kind):
    service = EvaluationPersistenceService(db_session)
    stored = await service.persist(evaluate(snapshot()))
    held_obs = (await db_session.execute(select(EvaluationObservation))).scalars().all()
    held_points = (await db_session.execute(select(EvaluationPoint))).scalars().all()
    statements = {
        'point': 'UPDATE forecast_evaluation_points SET signed_residual = signed_residual + 1',
        'observation': 'UPDATE forecast_evaluation_observations SET rate = rate + 1',
        'header': 'UPDATE forecast_evaluation_runs SET outer_evaluation_count = 11',
        'phase': "DELETE FROM forecast_evaluation_points WHERE protocol_phase = 'NESTED_OUTER' AND target_ordinal = 30",
        'inner': "UPDATE forecast_evaluation_points SET inner_evaluation_count = 999 WHERE protocol_phase = 'NESTED_OUTER'",
        'config': "UPDATE forecast_evaluation_runs SET configuration = '{}'::jsonb",
    }
    await db_session.execute(text(statements[kind]))
    with pytest.raises(EvaluationIntegrityError):
        await service.load(stored.id)
    assert held_obs and held_points


async def test_structural_incompleteness_rejected_even_with_matching_content_hash(db_session):
    from app.services.forecast_evaluation import assemble
    from app.services.forecast_evaluation_persistence import content_fingerprint
    r = evaluate(snapshot()); service = EvaluationPersistenceService(db_session)
    stored = await service.persist(r)
    removed = next(p for p in r.points if p.protocol_phase == Phase.SELECTION_WINDOW and p.candidate_name == 'Naive')
    malformed = assemble(r.input_snapshot, r.configuration, tuple(p for p in r.points if p != removed), r.selection_status, r.outer_status)
    await db_session.execute(text("DELETE FROM forecast_evaluation_points WHERE protocol_phase = 'SELECTION_WINDOW' AND target_ordinal = :t AND candidate_name = 'Naive'"), {'t': removed.target_ordinal})
    await db_session.execute(text('UPDATE forecast_evaluation_runs SET content_fingerprint = :h, selection_evaluation_count = 15'), {'h': content_fingerprint(malformed)})
    with pytest.raises(EvaluationIntegrityError, match='phase populations'):
        await service.load(stored.id)


async def test_concurrent_conflicting_content_rejected_without_duplicate(db_session):
    r = evaluate(snapshot()); bad = r.model_copy(update={'outer_metrics': r.outer_metrics.model_copy(update={'mae': 999})})
    async def worker(result):
        async with AsyncSession(bind=db_session.bind, expire_on_commit=False) as session:
            try:
                stored = await EvaluationPersistenceService(session).persist(result)
                await session.commit(); return stored.result
            except EvaluationIntegrityError:
                await session.rollback(); return 'CONFLICT'
    results = await asyncio.wait_for(asyncio.gather(worker(r), worker(bad)), timeout=15)
    assert results == [r, 'CONFLICT']
    assert await counts(db_session) == (1, 31, 92)


async def test_caller_pending_work_not_committed_and_independent_failure_visibility(db_session):
    pending = FreightRate(source='Caller', trade_lane='L', container_type='C', origin_port='P',
        dest_region='R', rate_date=date(2026, 1, 1), rate_usd=Decimal('1.10'))
    db_session.add(pending)
    stored = await EvaluationPersistenceService(db_session).persist(evaluate(snapshot()))
    async with AsyncSession(bind=db_session.bind) as second:
        assert await second.get(FreightRate, pending.id) is None
        assert await second.get(EvaluationRun, stored.id) is None
    await db_session.rollback()
    async with AsyncSession(bind=db_session.bind) as second:
        assert await counts(second) == (0, 0, 0)
        assert await second.get(FreightRate, pending.id) is None


@pytest.mark.parametrize('value', ['1.10', '1.1', '0', '99999999.99'])
async def test_exact_numeric_boundary_and_caller_decimal_context(db_session, value):
    from decimal import localcontext, Inexact, Rounded, ROUND_DOWN
    result = evaluate(snapshot([value] * 31))
    with localcontext() as c:
        c.prec = 2; c.rounding = ROUND_DOWN
        c.traps[Inexact] = c.traps[Rounded] = True
        c.flags[Inexact] = c.flags[Rounded] = True
        before = (c.prec, c.rounding, dict(c.traps), dict(c.flags))
        stored = await EvaluationPersistenceService(db_session).persist(result)
        assert (c.prec, c.rounding, dict(c.traps), dict(c.flags)) == before
    assert all(o.rate == Decimal(value) for o in stored.result.input_snapshot.observations)


@pytest.mark.parametrize('model,field,value', [
    (EvaluationObservation, 'ordinal', 99), (EvaluationObservation, 'observation_date', date(2030, 1, 1)),
    (EvaluationPoint, 'absolute_error', 0), (EvaluationPoint, 'actual_direction', 'UNCHANGED')])
async def test_orm_additional_scalar_mutation_protection(db_session, model, field, value):
    await EvaluationPersistenceService(db_session).persist(evaluate(snapshot()))
    stmt = select(model) if model is EvaluationObservation else select(model).where(EvaluationPoint.absolute_error > 0)
    row = (await db_session.execute(stmt)).scalars().first()
    with pytest.raises(ValueError, match='append-only'):
        async with db_session.begin_nested():
            setattr(row, field, value); await db_session.flush()
