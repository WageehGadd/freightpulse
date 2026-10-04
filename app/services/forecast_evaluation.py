"""Pure, retrospective baseline procedure evaluation. No I/O imports."""
import hashlib
import json
import math
from decimal import Decimal
from collections import Counter
from app.schemas.forecast_evaluation import (
    EVALUATION_VERSION, CANDIDATES, EvaluationInput, EvaluationConfig,
    EvaluationResult, Phase, Availability, Direction, Point, Metrics,
    CandidateSummary, WinnerCount,
)
from app.services.baseline_forecasting import BaselineForecastingService, baseline_selection_key

LIMITATIONS = ('UNVERIFIED_MARKET_PROVENANCE', 'SAMPLE_SIZE_NOT_STATISTICALLY_VALIDATED',
    'SELECTION_WINDOW_REUSED', 'RETROSPECTIVE_DEPENDENT_OUTER_FOLDS',
    'EXPLORATORY_INNER_MINIMUM', 'FINAL_CHAMPION_NOT_INDEPENDENTLY_VALIDATED',
    'HISTORICAL_AVAILABILITY_UNKNOWN', 'NO_CALIBRATED_UNCERTAINTY')


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False)


def fingerprint(value):
    return hashlib.sha256(canonical_json(value).encode('utf-8')).hexdigest()


def decimal_text(value: Decimal):
    """Canonical numeric value without normalize(), rounding, or global context."""
    if not value.is_finite():
        return str(value)  # Invalid evidence identity; never permitted in persistence.
    if value == 0:
        return '0'
    text = format(value, 'f')
    return text.rstrip('0').rstrip('.') if '.' in text else text


def dataset_fingerprint(snapshot):
    return fingerprint({'source': snapshot.source, 'trade_lane': snapshot.trade_lane,
        'container_type': snapshot.container_type, 'observations': [
            [i, o.observation_date.isoformat(), decimal_text(o.rate)]
            for i, o in enumerate(snapshot.observations)]})


def configuration_document(config):
    windows = {'MA(2)': 2, 'MA(3)': 3, 'MA(4)': 4}
    return {**config.model_dump(mode='json'),
        'candidate_definitions': [{'name': n, 'window': windows.get(n),
            'methodology': 'baseline-v1-decimal'} for n in config.candidate_names],
        'selection_order': ['MAE_ASC', 'RMSE_ASC', 'MODEL_NAME_ASC'],
        'metric_version': 't04-float-errors-direction-v1',
        'protocol_phases': [p.value for p in Phase],
        'outer_selection': 'all_prior_selection_targets',
        'zero_direction_denominator': 'null'}


def configuration_fingerprint(config):
    return fingerprint(configuration_document(config))


def aggregate(points):
    """Same ordered float summation as T04; zero direction denominator is explicit."""
    n = len(points)
    valid = sum(p.direction_valid for p in points)
    correct = sum(p.direction_correct is True for p in points)
    return Metrics(evaluation_count=n,
        mae=sum(p.absolute_error for p in points) / n if n else None,
        rmse=math.sqrt(sum(p.squared_error for p in points) / n) if n else None,
        smape=sum(p.smape_component for p in points) / n if n else None,
        directional_valid_count=valid, directional_correct_count=correct,
        directional_accuracy=correct / valid * 100.0 if valid else None)


def direction(value):
    return {1: Direction.INCREASE, -1: Direction.DECREASE, 0: Direction.UNCHANGED}[value]


def score_point(service, snapshot, y, t, name, prediction, phase, inner=None):
    actual, previous = y[t], y[t-1]
    residual = actual - prediction
    actual_dir = service._direction(previous, actual)
    predicted_dir = service._direction(previous, prediction)
    valid = actual_dir != 0 or predicted_dir != 0
    return Point(protocol_phase=phase, target_ordinal=t,
        target_date=snapshot.observations[t].observation_date, candidate_name=name,
        training_observation_count=t, inner_evaluation_count=inner,
        previous_actual=previous, actual=actual, prediction=prediction,
        signed_residual=residual, absolute_error=abs(residual), squared_error=residual ** 2,
        smape_component=service._smape(actual, prediction),
        actual_direction=direction(actual_dir), predicted_direction=direction(predicted_dir),
        direction_valid=valid, direction_correct=(actual_dir == predicted_dir) if valid else None)


def assemble(snapshot, config, points, selection_status, outer_status):
    selection = tuple(p for p in points if p.protocol_phase == Phase.SELECTION_WINDOW)
    outer = tuple(p for p in points if p.protocol_phase == Phase.NESTED_OUTER)
    summaries = tuple(CandidateSummary(candidate_name=n,
        metrics=aggregate(tuple(p for p in selection if p.candidate_name == n)))
        for n in config.candidate_names) if selection else ()
    champion = min(summaries, key=lambda s: baseline_selection_key(
        s.candidate_name, s.metrics.mae, s.metrics.rmse)).candidate_name if summaries else None
    names = [p.candidate_name for p in outer]
    counts = Counter(names)
    return EvaluationResult(input_snapshot=snapshot, configuration=config,
        dataset_fingerprint=dataset_fingerprint(snapshot), configuration_fingerprint=configuration_fingerprint(config),
        selection_status=selection_status, outer_status=outer_status, points=tuple(points),
        candidate_summaries=summaries, final_champion=champion, outer_metrics=aggregate(outer),
        winner_counts=tuple(WinnerCount(candidate_name=n, count=counts[n]) for n in config.candidate_names if counts[n]),
        winner_switch_count=sum(a != b for a, b in zip(names, names[1:])) if names else None,
        limitations=LIMITATIONS)


def evaluate(snapshot: EvaluationInput, config: EvaluationConfig = EvaluationConfig()):
    # Revalidate even model_copy/model_construct callers; never repair ordering.
    snapshot = EvaluationInput.model_validate(snapshot.model_dump())
    config = EvaluationConfig.model_validate(config.model_dump())
    if (config.evaluation_version != EVALUATION_VERSION or config.forecast_horizon != 1
            or any(n not in CANDIDATES for n in config.candidate_names)):
        return assemble(snapshot, config, (), Availability.UNSUPPORTED, Availability.UNSUPPORTED)
    try:
        y = [float(o.rate) for o in snapshot.observations]
        if any(not math.isfinite(v) for v in y):
            raise ValueError('Nonfinite input')
        service = BaselineForecastingService(config.initial_train_size)
        points = []
        by_candidate = {n: [] for n in config.candidate_names}
        outer = []
        for t in range(config.initial_train_size, len(y)):
            # Only points for targets < t are visible during outer selection.
            if t >= config.initial_train_size + config.minimum_inner_evaluation_points:
                metrics = {n: aggregate(by_candidate[n]) for n in config.candidate_names}
                winner = min(config.candidate_names, key=lambda n: baseline_selection_key(
                    n, metrics[n].mae, metrics[n].rmse))
                prediction = service._predict(winner, y[:t], horizon=1)
                outer.append(score_point(service, snapshot, y, t, winner, prediction,
                    Phase.NESTED_OUTER, t - config.initial_train_size))
            for name in config.candidate_names:
                prediction = service._predict(name, y[:t], horizon=1)
                point = score_point(service, snapshot, y, t, name, prediction, Phase.SELECTION_WINDOW)
                by_candidate[name].append(point)
                points.append(point)
        return assemble(snapshot, config, tuple(points + outer),
            Availability.AVAILABLE if points else Availability.INSUFFICIENT_HISTORY,
            Availability.AVAILABLE if outer else Availability.INSUFFICIENT_HISTORY)
    except (ValueError, OverflowError):
        # Never expose partial/zero-filled metrics after invalid arithmetic.
        return assemble(snapshot, config, (), Availability.INVALID, Availability.INVALID)
