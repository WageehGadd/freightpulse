"""Immutable internal evaluation evidence; no public API or probabilistic output."""
from datetime import date
from decimal import Decimal
from enum import Enum
from pydantic import BaseModel, ConfigDict, StrictInt, model_validator, field_validator

EVALUATION_VERSION = 'baseline-evaluation-v1'
CANDIDATES = ('Naive', 'MA(2)', 'MA(3)', 'MA(4)', 'Drift')


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra='forbid', protected_namespaces=())


class Phase(str, Enum):
    SELECTION_WINDOW = 'SELECTION_WINDOW'
    NESTED_OUTER = 'NESTED_OUTER'


class Availability(str, Enum):
    AVAILABLE = 'AVAILABLE'
    INSUFFICIENT_HISTORY = 'INSUFFICIENT_HISTORY'
    UNSUPPORTED = 'UNSUPPORTED'
    INVALID = 'INVALID'


class Direction(str, Enum):
    INCREASE = 'INCREASE'
    DECREASE = 'DECREASE'
    UNCHANGED = 'UNCHANGED'


class Provenance(str, Enum):
    UNVERIFIED = 'UNVERIFIED'


class Observation(Frozen):
    observation_date: date
    rate: Decimal

    @field_validator('rate', mode='before')
    @classmethod
    def exact_source_money(cls, value):
        if isinstance(value, (float, bool)):
            raise ValueError('Source snapshot requires exact money, not float')
        return value


class EvaluationInput(Frozen):
    source: str
    trade_lane: str
    container_type: str
    observations: tuple[Observation, ...]
    provenance: Provenance = Provenance.UNVERIFIED

    @model_validator(mode='after')
    def ordered_unique(self):
        if any(not s.strip() for s in (self.source, self.trade_lane, self.container_type)):
            raise ValueError('Exact nonblank series identity required')
        dates = [o.observation_date for o in self.observations]
        if any(a >= b for a, b in zip(dates, dates[1:])):
            raise ValueError('Observation dates must be strictly increasing and unique')
        return self


class EvaluationConfig(Frozen):
    evaluation_version: str = EVALUATION_VERSION
    initial_train_size: StrictInt = 15
    minimum_inner_evaluation_points: StrictInt = 4
    forecast_horizon: StrictInt = 1
    candidate_names: tuple[str, ...] = CANDIDATES

    @model_validator(mode='after')
    def meaningful_config(self):
        if self.initial_train_size < 1 or self.minimum_inner_evaluation_points < 1:
            raise ValueError('Training and inner counts must be positive')
        if not self.candidate_names or len(set(self.candidate_names)) != len(self.candidate_names):
            raise ValueError('A nonempty unique candidate sequence is required')
        return self


class Point(Frozen):
    model_config = ConfigDict(frozen=True, extra='forbid', allow_inf_nan=False)
    protocol_phase: Phase
    target_ordinal: StrictInt
    target_date: date
    candidate_name: str
    training_observation_count: StrictInt
    inner_evaluation_count: StrictInt | None = None
    previous_actual: float
    actual: float
    prediction: float
    signed_residual: float
    absolute_error: float
    squared_error: float
    smape_component: float
    predicted_direction: Direction
    actual_direction: Direction
    direction_valid: bool
    direction_correct: bool | None


class Metrics(Frozen):
    model_config = ConfigDict(frozen=True, extra='forbid', allow_inf_nan=False)
    evaluation_count: int
    mae: float | None
    rmse: float | None
    smape: float | None
    directional_valid_count: int
    directional_correct_count: int
    directional_accuracy: float | None


class CandidateSummary(Frozen):
    candidate_name: str
    metrics: Metrics


class WinnerCount(Frozen):
    candidate_name: str
    count: int


class EvaluationResult(Frozen):
    input_snapshot: EvaluationInput
    configuration: EvaluationConfig
    dataset_fingerprint: str
    configuration_fingerprint: str
    selection_status: Availability
    outer_status: Availability
    points: tuple[Point, ...]
    candidate_summaries: tuple[CandidateSummary, ...]
    final_champion: str | None
    outer_metrics: Metrics
    winner_counts: tuple[WinnerCount, ...]
    winner_switch_count: int | None
    limitations: tuple[str, ...]
