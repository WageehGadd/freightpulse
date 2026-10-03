"""Immutable internal decision evidence; no public API or persistence contract."""
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID
from typing import Literal
from pydantic import BaseModel, ConfigDict, model_validator, field_validator, StrictInt

ENGINE_VERSION = "decision-rules-v1"

class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

class Decision(str, Enum):
    CONSIDER_EARLIER_BOOKING = "CONSIDER_EARLIER_BOOKING"
    CONSIDER_LATER_BOOKING = "CONSIDER_LATER_BOOKING"
    MONITOR = "MONITOR"
    WITHHOLD = "WITHHOLD"
    UNAVAILABLE = "UNAVAILABLE"

class Movement(str, Enum):
    INCREASE = "INCREASE"
    DECREASE = "DECREASE"
    NEGLIGIBLE = "NEGLIGIBLE"
    UNDEFINED = "UNDEFINED"

class Reason(str, Enum):
    NO_FORECAST = "NO_FORECAST"
    SERIES_MISMATCH = "SERIES_MISMATCH"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    SUPERSEDED_FORECAST = "SUPERSEDED_FORECAST"
    STALE_INPUT = "STALE_INPUT"
    UNKNOWN_FRESHNESS = "UNKNOWN_FRESHNESS"
    MODEL_INELIGIBLE = "MODEL_INELIGIBLE"
    MINIMAL_READINESS = "MINIMAL_READINESS"
    INSUFFICIENT_READINESS = "INSUFFICIENT_READINESS"
    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"
    INSUFFICIENT_EVALUATION = "INSUFFICIENT_EVALUATION"
    INVALID_RATE = "INVALID_RATE"
    INVALID_METRICS = "INVALID_METRICS"
    UNSUPPORTED_HORIZON = "UNSUPPORTED_HORIZON"
    EXPIRED_TARGET = "EXPIRED_TARGET"
    INVALID_TEMPORAL_CONTEXT = "INVALID_TEMPORAL_CONTEXT"
    FORECAST_INCREASE = "FORECAST_INCREASE"
    FORECAST_DECREASE = "FORECAST_DECREASE"
    MOVEMENT_BELOW_THRESHOLD = "MOVEMENT_BELOW_THRESHOLD"
    MOVEMENT_WITHIN_ERROR_SCALE = "MOVEMENT_WITHIN_ERROR_SCALE"
    AGING_INPUT = "AGING_INPUT"

class Limitation(str, Enum):
    HEURISTIC_MOVEMENT_THRESHOLD = "HEURISTIC_MOVEMENT_THRESHOLD"
    HEURISTIC_EVALUATION_MINIMUM = "HEURISTIC_EVALUATION_MINIMUM"
    HEURISTIC_ERROR_SCALE = "HEURISTIC_ERROR_SCALE"
    BASELINE_MODEL_ONLY = "BASELINE_MODEL_ONLY"
    SAME_DATE_CORRECTIONS_UNDETECTED = "SAME_DATE_CORRECTIONS_UNDETECTED"
    LOCAL_TARGET_CADENCE = "LOCAL_TARGET_CADENCE"

class PolicyConfigurationError(ValueError):
    """Invalid rule configuration, distinct from deficient forecast evidence."""

class DecisionPolicy(Frozen):
    movement_threshold_pct: Decimal = Decimal("2.0")
    min_history_observations: StrictInt = 100
    min_evaluation_points: StrictInt = 30
    error_multiplier: Decimal = Decimal("1.0")
    supported_horizons: frozenset[StrictInt] = frozenset({1})

    def __init__(self, **data):
        try:
            super().__init__(**data)
        except ValueError as exc:
            raise PolicyConfigurationError(str(exc)) from exc

    @model_validator(mode="after")
    def valid_policy(self):
        if any(not v.is_finite() or v <= 0 for v in (self.movement_threshold_pct, self.error_multiplier)):
            raise ValueError("Threshold and multiplier must be finite and positive")
        if self.min_history_observations < 0 or self.min_evaluation_points < 0:
            raise ValueError("Evidence minimums cannot be negative")
        if not self.supported_horizons or any(h <= 0 for h in self.supported_horizons):
            raise ValueError("Supported horizons must be positive")
        return self

class SeriesIdentity(Frozen):
    source: str
    trade_lane: str
    container_type: str

class ForecastSnapshot(Frozen):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=True, protected_namespaces=())
    forecast_id: UUID
    series: SeriesIdentity
    forecast_for_date: date
    predicted_rate: Decimal | None
    model_name: str
    model_version: str
    forecast_horizon: int
    latest_observation_date: date
    latest_actual_rate: Decimal | None
    history_observations: int
    evaluation_points: int
    backtest_mae: float | None
    backtest_rmse: float | None
    backtest_smape: float | None
    backtest_directional_accuracy: float | None
    data_readiness: str
    input_freshness_at_generation: str
    stored_live_decision_eligible: bool
    warning: str | None
    generated_at: datetime

    @field_validator("backtest_mae", "backtest_rmse", "backtest_smape",
                     "backtest_directional_accuracy", mode="before")
    @classmethod
    def boolean_metrics_are_missing(cls, value):
        # A corrupt boolean is deficient evidence, not a numerical metric.
        return None if isinstance(value, bool) else value

class ForecastState(Frozen):
    series: SeriesIdentity
    evaluated_at: datetime
    latest_source_date: date | None
    latest_forecast_id: UUID | None
    latest_forecast_generated_at: datetime | None
    series_matches: bool
    source_superseded: bool
    forecast_superseded: bool
    current_input_freshness: str
    stored_live_decision_eligible: bool
    effective_live_decision_eligible: bool
    context_state: str
    context_warning: str | None

class DecisionInput(Frozen):
    forecast: ForecastSnapshot
    current_state: ForecastState

class Signals(Frozen):
    absolute_change: Decimal | None = None
    percentage_change: Decimal | None = None
    error_scale: Decimal | None = None

class DecisionResult(Frozen):
    decision: Decision
    actionable: bool
    movement: Movement
    reasons: tuple[Reason, ...]
    signals: Signals
    limitations: tuple[Limitation, ...]
    forecast_identity: ForecastSnapshot | None
    evaluated_at: datetime
    engine_version: Literal["decision-rules-v1"] = ENGINE_VERSION
    policy: DecisionPolicy
    input_snapshot: DecisionInput | None

    @model_validator(mode="after")
    def actionable_matches_decision(self):
        directional = self.decision in (Decision.CONSIDER_EARLIER_BOOKING, Decision.CONSIDER_LATER_BOOKING)
        if self.actionable != directional:
            raise ValueError("Actionable must exactly match a directional decision")
        if directional and any(reason in HARD_BLOCKERS for reason in self.reasons):
            raise ValueError("Hard blockers prohibit directional decisions")
        return self

# Explicit contract order: blockers, outcome reasons, then aging information.
REASON_ORDER = tuple(Reason)
HARD_BLOCKERS = frozenset((Reason.NO_FORECAST, Reason.SERIES_MISMATCH,
    Reason.SOURCE_UNAVAILABLE, Reason.SUPERSEDED_FORECAST, Reason.STALE_INPUT,
    Reason.UNKNOWN_FRESHNESS, Reason.MODEL_INELIGIBLE, Reason.MINIMAL_READINESS,
    Reason.INSUFFICIENT_READINESS, Reason.INSUFFICIENT_HISTORY,
    Reason.INSUFFICIENT_EVALUATION, Reason.INVALID_RATE, Reason.INVALID_METRICS,
    Reason.UNSUPPORTED_HORIZON, Reason.EXPIRED_TARGET, Reason.INVALID_TEMPORAL_CONTEXT))
