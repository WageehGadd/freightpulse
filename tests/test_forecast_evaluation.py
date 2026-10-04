"""T11 causality, authoritative T04 parity, and immutable pure evidence."""
from datetime import date, timedelta
from decimal import Decimal, localcontext, ROUND_DOWN
from types import SimpleNamespace
import json
import subprocess
import sys
import pytest
from pydantic import ValidationError
from app.schemas.forecast_evaluation import (
    EvaluationInput, EvaluationConfig, Observation, Phase, Availability, CANDIDATES,
)
from app.services.forecast_evaluation import (
    evaluate, aggregate, dataset_fingerprint, configuration_fingerprint,
)
from app.services.baseline_forecasting import BaselineForecastingService


def snapshot(values=None, **identity):
    values = values if values is not None else [100 + (i % 7) * 3 - i / 10 for i in range(31)]
    return EvaluationInput(source=identity.get('source', 'SCFI'),
        trade_lane=identity.get('trade_lane', 'EvaluationLane'),
        container_type=identity.get('container_type', '40ft'),
        observations=tuple(Observation(observation_date=date(2026, 1, 1) + timedelta(days=i),
            rate=Decimal(str(v))) for i, v in enumerate(values)))


def legacy_report(s, config=EvaluationConfig()):
    ds = SimpleNamespace(metadata=SimpleNamespace(series_id='fixture'), observations=[
        SimpleNamespace(date=o.observation_date, target_rate=float(o.rate)) for o in s.observations])
    return BaselineForecastingService(config.initial_train_size).backtest(ds)


@pytest.mark.parametrize('values', [list(range(31)), [100] * 31,
    [100 + (i % 4) * 3 for i in range(31)], [100 - i for i in range(31)]])
def test_all_candidate_and_final_champion_parity(values):
    s = snapshot(values); result = evaluate(s); legacy = legacy_report(s)
    assert tuple(BaselineForecastingService().models) == CANDIDATES
    assert result.final_champion == legacy.champion_model
    for old in legacy.results:
        points = [p for p in result.points if p.protocol_phase == Phase.SELECTION_WINDOW and p.candidate_name == old.model_name]
        summary = next(x.metrics for x in result.candidate_summaries if x.candidate_name == old.model_name)
        assert (summary.mae, summary.rmse, summary.smape) == (old.metrics.mae, old.metrics.rmse, old.metrics.smape)
        for new, previous in zip(points, old.observations):
            assert (new.prediction, new.actual, new.absolute_error, new.squared_error, new.smape_component) == (
                previous.predicted_value, previous.actual_value, previous.absolute_error,
                previous.squared_error, previous.percentage_error)
            assert new.direction_correct == (bool(previous.directional_accuracy) if previous.directional_accuracy is not None else None)


def test_default_counts_order_and_inner_selection():
    result = evaluate(snapshot())
    selection = [p for p in result.points if p.protocol_phase == Phase.SELECTION_WINDOW]
    outer = [p for p in result.points if p.protocol_phase == Phase.NESTED_OUTER]
    assert len(selection) == 80 and len(outer) == 12
    assert [(p.target_ordinal, p.candidate_name) for p in selection] == [(t, n) for t in range(15, 31) for n in CANDIDATES]
    assert [p.target_ordinal for p in outer] == list(range(19, 31))
    for p in outer:
        candidates = [(aggregate([x for x in selection if x.candidate_name == n and x.target_ordinal < p.target_ordinal]), n) for n in CANDIDATES]
        expected = min(candidates, key=lambda v: (v[0].mae, v[0].rmse, v[1]))[1]
        assert p.candidate_name == expected
        assert p.inner_evaluation_count == p.target_ordinal - 15
        assert p.training_observation_count == p.target_ordinal
    assert result.outer_metrics == aggregate(outer)
    assert result.winner_switch_count == sum(a.candidate_name != b.candidate_name for a, b in zip(outer, outer[1:]))
    assert sum(w.count for w in result.winner_counts) == 12
    for summary in result.candidate_summaries:
        assert summary.metrics == aggregate([p for p in selection if p.candidate_name == summary.candidate_name])


@pytest.mark.parametrize('target', [19, 23, 30])
@pytest.mark.parametrize('change_later', [False, True])
def test_future_target_causality(target, change_later):
    s = snapshot(); old = evaluate(s)
    obs = list(s.observations)
    for i in range(target, len(obs)):
        if i == target or change_later:
            obs[i] = obs[i].model_copy(update={'rate': Decimal('9000') + i})
    new = evaluate(s.model_copy(update={'observations': tuple(obs)}))
    before = lambda r: [p for p in r.points if p.target_ordinal < target]
    assert before(old) == before(new)
    a = next(p for p in old.points if p.protocol_phase == Phase.NESTED_OUTER and p.target_ordinal == target)
    b = next(p for p in new.points if p.protocol_phase == Phase.NESTED_OUTER and p.target_ordinal == target)
    assert (a.candidate_name, a.prediction) == (b.candidate_name, b.prediction)
    assert a.actual != b.actual and a.signed_residual != b.signed_residual


@pytest.mark.parametrize('previous,actual,predicted,valid,correct', [
    (10, 11, 12, True, True), (10, 9, 8, True, True),
    (10, 11, 9, True, False), (10, 9, 11, True, False),
    (10, 10, 10, False, None), (10, 10, 11, True, False),
    (10, 11, 10, True, False)])
def test_direction_and_residual(previous, actual, predicted, valid, correct):
    from app.services.forecast_evaluation import score_point
    s = snapshot([previous, actual])
    p = score_point(BaselineForecastingService(), s, [float(previous), float(actual)], 1,
        'Naive', float(predicted), Phase.SELECTION_WINDOW)
    assert p.direction_valid is valid and p.direction_correct is correct
    assert p.signed_residual == actual - predicted
    assert p.absolute_error == abs(actual - predicted)
    assert p.squared_error == (actual - predicted) ** 2


def test_all_flat_null_direction_zero_errors():
    r = evaluate(snapshot([0] * 31))
    assert r.final_champion == 'Drift'
    for s in (*[x.metrics for x in r.candidate_summaries], r.outer_metrics):
        assert (s.mae, s.rmse, s.smape) == (0, 0, 0)
        assert s.directional_valid_count == s.directional_correct_count == 0
        assert s.directional_accuracy is None


@pytest.mark.parametrize('n,selection,outer', [(0, 0, 0), (15, 0, 0), (16, 5, 0), (19, 20, 0), (20, 25, 1)])
def test_short_history(n, selection, outer):
    r = evaluate(snapshot([100] * n))
    assert sum(p.protocol_phase == Phase.SELECTION_WINDOW for p in r.points) == selection
    assert r.outer_metrics.evaluation_count == outer
    assert r.outer_status == (Availability.AVAILABLE if outer else Availability.INSUFFICIENT_HISTORY)
    if not selection:
        assert r.final_champion is None and not r.candidate_summaries
    if not outer:
        assert r.outer_metrics.mae is None and r.winner_switch_count is None


@pytest.mark.parametrize('value', ['NaN', 'sNaN', 'Infinity', '-Infinity', '1e400', '1e200'])
def test_invalid_nonfinite_or_overflow(value):
    if not Decimal(value).is_finite():
        with pytest.raises(ValidationError):
            snapshot([value] * 31)
        return
    r = evaluate(snapshot([value if i % 2 else 0 for i in range(31)]))
    assert r.selection_status == r.outer_status == Availability.INVALID
    assert not r.points and r.outer_metrics.mae is None


@pytest.mark.parametrize('value', ['-10', '1e-150', '1e100'])
def test_finite_synthetic_values(value):
    r = evaluate(snapshot([value] * 31))
    assert r.selection_status == Availability.AVAILABLE
    assert all(p.absolute_error == 0 for p in r.points)


@pytest.mark.parametrize('updates', [{'evaluation_version': 'future'}, {'forecast_horizon': 2}, {'candidate_names': ('Other',)}])
def test_unsupported(updates):
    r = evaluate(snapshot(), EvaluationConfig(**updates))
    assert r.selection_status == r.outer_status == Availability.UNSUPPORTED
    assert not r.points


@pytest.mark.parametrize('updates', [{'initial_train_size': 0}, {'minimum_inner_evaluation_points': 0}, {'candidate_names': ()}, {'candidate_names': ('Naive', 'Naive')}])
def test_bad_configuration(updates):
    with pytest.raises(ValidationError):
        EvaluationConfig(**updates)


def test_fingerprints_decimal_context_and_corrections():
    a = snapshot(['100.00'] * 31); b = snapshot(['1e2'] * 31)
    assert dataset_fingerprint(a) == dataset_fingerprint(b)
    with localcontext() as c:
        c.prec = 2; c.rounding = ROUND_DOWN; c.clear_flags()
        before = str(c)
        assert dataset_fingerprint(a) == dataset_fingerprint(b)
        assert str(c) == before
    changes = list(a.observations)
    changes[-1] = changes[-1].model_copy(update={'rate': Decimal('100.01')})
    assert dataset_fingerprint(a) != dataset_fingerprint(a.model_copy(update={'observations': tuple(changes)}))
    changes[-1] = a.observations[-1].model_copy(update={'observation_date': date(2026, 2, 2)})
    assert dataset_fingerprint(a) != dataset_fingerprint(a.model_copy(update={'observations': tuple(changes)}))
    for field in ('source', 'trade_lane', 'container_type'):
        assert dataset_fingerprint(a) != dataset_fingerprint(a.model_copy(update={field: 'OTHER'}))
    assert configuration_fingerprint(EvaluationConfig()) == configuration_fingerprint(EvaluationConfig())
    for config in [EvaluationConfig(minimum_inner_evaluation_points=5),
        EvaluationConfig(candidate_names=tuple(reversed(CANDIDATES))), EvaluationConfig(initial_train_size=16)]:
        assert configuration_fingerprint(config) != configuration_fingerprint(EvaluationConfig())


def test_duplicates_order_immutability_and_determinism():
    s = snapshot(); r = evaluate(s)
    assert r == evaluate(s)
    for obs in [(s.observations[0], s.observations[0]), tuple(reversed(s.observations))]:
        with pytest.raises(ValidationError):
            EvaluationInput(source='S', trade_lane='L', container_type='C', observations=obs)
    with pytest.raises(ValidationError):
        r.points[0].prediction = 999
    with pytest.raises(TypeError):
        r.points[0] = r.points[1]
    with pytest.raises(ValidationError):
        r.configuration.initial_train_size = 1
    assert r.input_snapshot.provenance.value == 'UNVERIFIED'


def test_source_float_rejected_and_evaluation_context_independent():
    with pytest.raises(ValidationError):
        Observation(observation_date=date(2026, 1, 1), rate=100.01)
    s = snapshot(); expected = evaluate(s)
    with localcontext() as context:
        context.prec = 2; context.rounding = ROUND_DOWN; context.clear_flags()
        before = str(context)
        assert evaluate(s) == expected
        assert str(context) == before


def test_no_forbidden_output_fields():
    r = evaluate(snapshot())
    def keys(v):
        if isinstance(v, dict):
            return set(v) | set().union(*(keys(x) for x in v.values()))
        if isinstance(v, list):
            return set().union(*(keys(x) for x in v))
        return set()
    assert not keys(r.model_dump(mode='json')) & {'confidence', 'probability', 'score', 'interval', 'coverage', 'savings'}


def test_fresh_process_without_infrastructure_or_network():
    script = '''
import importlib.abc, sys, socket
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in ('sqlalchemy','redis','fastapi','openai','azure','celery') or fullname.startswith(('app.database','app.ai','app.tasks')):
            raise ImportError(fullname)
sys.meta_path.insert(0, Block())
def forbidden(*a, **k): raise AssertionError('network attempted')
socket.socket = forbidden
from app.services.forecast_evaluation import evaluate
from app.schemas.forecast_evaluation import EvaluationInput
r = evaluate(EvaluationInput(source='S', trade_lane='L', container_type='C', observations=()))
assert not r.points
'''
    subprocess.run([sys.executable, '-B', '-c', script], check=True, capture_output=True, text=True)


def test_seeded_adversarial_candidate_and_champion_parity():
    import random
    import math
    rng = random.Random(1109)
    for n in (16, 20, 31, 47):
        sequences = [[7] * n, list(range(n)), list(range(n, 0, -1)),
            [(-1) ** i * (i + 1) for i in range(n)], [i % 3 for i in range(n)],
            [Decimal('1e90') * (1 + i % 3) for i in range(n)],
            [Decimal('1e-90') * (1 + i % 3) for i in range(n)],
            [Decimal(rng.randrange(-10000, 10000)) / 100 for _ in range(n)],
            [Decimal('100') + Decimal(i % 2) / Decimal('1e10') for i in range(n)]]
        for values in sequences:
            s = snapshot(values); r = evaluate(s); legacy = legacy_report(s)
            assert r.final_champion == legacy.champion_model
            summaries = []
            for name in CANDIDATES:
                points = [p for p in r.points if p.protocol_phase == Phase.SELECTION_WINDOW and p.candidate_name == name]
                for p in points:
                    history = [float(o.rate) for o in s.observations[:p.target_ordinal]]
                    if name == 'Naive':
                        expected = history[-1]
                    elif name == 'Drift':
                        expected = history[-1] + (history[-1] - history[0]) / (len(history) - 1)
                    else:
                        window = int(name[3]); expected = sum(history[-window:]) / window
                    assert p.prediction == expected
                mae = sum(abs(p.actual-p.prediction) for p in points) / len(points)
                rmse = math.sqrt(sum((p.actual-p.prediction) ** 2 for p in points) / len(points))
                smape = sum(0 if abs(p.actual)+abs(p.prediction) == 0 else
                    abs(p.actual-p.prediction) / ((abs(p.actual)+abs(p.prediction))/2) * 100 for p in points) / len(points)
                metrics = next(x.metrics for x in r.candidate_summaries if x.candidate_name == name)
                old = next(x for x in legacy.results if x.model_name == name)
                assert (metrics.mae, metrics.rmse, metrics.smape) == (mae, rmse, smape)
                assert (mae, rmse, smape) == (old.metrics.mae, old.metrics.rmse, old.metrics.smape)
                valid = [p for p in points if p.actual != p.previous_actual or p.prediction != p.previous_actual]
                sign = lambda x: (x > 0) - (x < 0)
                correct = sum(sign(p.actual-p.previous_actual) == sign(p.prediction-p.previous_actual) for p in valid)
                assert metrics.directional_valid_count == len(valid)
                assert metrics.directional_correct_count == correct
                assert metrics.directional_accuracy == (100 * (correct/len(valid)) if valid else None)
                summaries.append((mae, rmse, name))
            assert r.final_champion == min(summaries)[2]


def test_every_outer_target_current_future_and_previous_perturbation():
    s = snapshot(); original = evaluate(s); prior_changes = 0
    for t in range(19, 31):
        original_outer = next(p for p in original.points if p.protocol_phase == Phase.NESTED_OUTER and p.target_ordinal == t)
        for indices in ((t,), tuple(range(t+1, 31)), (t-1,)):
            obs = list(s.observations)
            for i in indices:
                obs[i] = obs[i].model_copy(update={'rate': Decimal('100000') + i})
            changed = evaluate(s.model_copy(update={'observations': tuple(obs)}))
            new_outer = next(p for p in changed.points if p.protocol_phase == Phase.NESTED_OUTER and p.target_ordinal == t)
            if indices == (t-1,):
                prior_changes += new_outer.prediction != original_outer.prediction
            else:
                old_inner = [p for p in original.points if p.protocol_phase == Phase.SELECTION_WINDOW and p.target_ordinal < t]
                new_inner = [p for p in changed.points if p.protocol_phase == Phase.SELECTION_WINDOW and p.target_ordinal < t]
                assert old_inner == new_inner
                assert (new_outer.prediction, new_outer.candidate_name) == (original_outer.prediction, original_outer.candidate_name)
                if indices != (t,):
                    assert new_outer == original_outer
                else:
                    assert new_outer.actual != original_outer.actual
        assert original_outer.inner_evaluation_count == t-15
    assert prior_changes > 0


@pytest.mark.parametrize('n', [0, 1, 14, 15, 16, 18, 19, 20, 31])
def test_complete_short_history_boundary_matrix(n):
    r = evaluate(snapshot([1] * n))
    assert len(r.points) == max(n-15, 0)*5 + max(n-19, 0)
    assert r.selection_status == ('AVAILABLE' if n > 15 else 'INSUFFICIENT_HISTORY')
    assert r.outer_status == ('AVAILABLE' if n > 19 else 'INSUFFICIENT_HISTORY')
    assert r.outer_metrics.evaluation_count == max(n-19, 0)


def test_irregular_dates_exact_identity_and_canonical_fingerprint_oracle():
    import hashlib
    s = snapshot(source='源|SCFI', trade_lane='A,"B\\C', container_type=' 40ft ')
    dates = [date(2025, 1, 1) + timedelta(days=i*i+3*i) for i in range(31)]
    s = s.model_copy(update={'observations': tuple(o.model_copy(update={'observation_date': d}) for o, d in zip(s.observations, dates))})
    r = evaluate(s)
    assert all(p.target_date == dates[p.target_ordinal] for p in r.points)
    assert r.input_snapshot.container_type == ' 40ft '
    doc = {'source': s.source, 'trade_lane': s.trade_lane, 'container_type': s.container_type,
        'observations': [[i, o.observation_date.isoformat(), format(o.rate, 'f').rstrip('0').rstrip('.') if '.' in format(o.rate, 'f') else format(o.rate, 'f')]
            for i, o in enumerate(s.observations)]}
    expected = hashlib.sha256(json.dumps(doc, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()).hexdigest()
    assert r.dataset_fingerprint == expected
    assert dataset_fingerprint(snapshot(source='A|B', trade_lane='C')) != dataset_fingerprint(snapshot(source='A', trade_lane='B|C'))
    for field in ('source', 'trade_lane', 'container_type'):
        with pytest.raises(ValidationError):
            EvaluationInput.model_validate({**s.model_dump(), field: '  '})


def test_config_hash_complete_document_and_independent_mutations():
    import copy
    import hashlib
    from app.services.forecast_evaluation import configuration_document, fingerprint
    config = EvaluationConfig(); doc = configuration_document(config)
    assert configuration_fingerprint(config) == hashlib.sha256(json.dumps(doc, sort_keys=True,
        separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()).hexdigest()
    for field, value in [('minimum_inner_evaluation_points', 5), ('initial_train_size', 14),
        ('forecast_horizon', 2), ('evaluation_version', 'future'), ('candidate_names', ('Naive', 'MA(3)'))]:
        assert configuration_fingerprint(config.model_copy(update={field: value})) != configuration_fingerprint(config)
    mutations = [lambda d: d['candidate_definitions'][1].update(window=5),
        lambda d: d.update(selection_order=['RMSE_ASC', 'MAE_ASC', 'MODEL_NAME_ASC']),
        lambda d: d.update(metric_version='future-direction-v2'),
        lambda d: d.update(zero_direction_denominator='zero')]
    for change in mutations:
        modified = copy.deepcopy(doc); change(modified)
        assert fingerprint(modified) != configuration_fingerprint(config)


def test_decimal_serializer_and_validation_preserve_context_traps_flags():
    from decimal import Inexact, Rounded, InvalidOperation
    from app.services.forecast_evaluation import decimal_text
    s = snapshot(['1.10'] * 31)
    with localcontext() as c:
        c.prec = 2; c.rounding = ROUND_DOWN
        c.traps[Inexact] = c.traps[Rounded] = c.traps[InvalidOperation] = True
        c.flags[Inexact] = c.flags[Rounded] = True
        before = (c.prec, c.rounding, dict(c.traps), dict(c.flags))
        assert decimal_text(Decimal('1.10')) == decimal_text(Decimal('1.1')) == '1.1'
        assert EvaluationInput.model_validate(s.model_dump()) == s
        dataset_fingerprint(s); evaluate(s)
        assert (c.prec, c.rounding, dict(c.traps), dict(c.flags)) == before
