"""Explicit T10 public DTOs; decimal values serialize as exact JSON strings."""
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import ConfigDict, field_validator, model_validator

from app.schemas.decision import Decision, Movement, Reason, Limitation, Frozen
from app.schemas.reliability import (
    HistoricalEvidenceStatus, SampleSufficiencyStatus, DecisionEvidenceStatus,
    EvidenceDimension, EvidenceFactorCode, FactorKind,
)


class PublicModel(Frozen):
    model_config = ConfigDict(frozen=True, extra='forbid', allow_inf_nan=False,
                              protected_namespaces=())


class DecisionSeries(PublicModel):
    source: str
    trade_lane: str
    container_type: str


class DecisionForecast(PublicModel):
    forecast_id: UUID
    predicted_rate: Decimal | None
    latest_actual_rate: Decimal | None
    latest_observation_date: date
    forecast_for_date: date
    forecast_horizon: int


class PublicDecision(PublicModel):
    decision: Decision
    actionable: bool
    movement: Movement
    absolute_change: Decimal | None
    percentage_change: Decimal | None
    error_scale: Decimal | None
    movement_within_error_scale: bool | None
    reasons: tuple[Reason, ...]
    limitations: tuple[Limitation, ...]

    @model_validator(mode='after')
    def valid_actionability(self):
        if self.actionable != (self.decision in (
                Decision.CONSIDER_EARLIER_BOOKING, Decision.CONSIDER_LATER_BOOKING)):
            raise ValueError('Actionability contradicts the authoritative decision')
        return self


class PublicSampleEvidence(PublicModel):
    history_observations: int | None
    evaluation_points: int | None
    data_readiness: str | None


class PublicHistoricalError(PublicModel):
    mae: float | None
    rmse: float | None
    smape: float | None


class PublicDirectionalEvidence(PublicModel):
    directional_accuracy: float | None
    valid_directional_sample_count: Literal[None] = None


class PublicNormalizedSignals(PublicModel):
    mae_relative_to_latest_actual_pct: Decimal | None
    rmse_relative_to_latest_actual_pct: Decimal | None
    movement_to_mae_ratio: Decimal | None


class PublicEvidenceFactor(PublicModel):
    dimension: EvidenceDimension
    code: EvidenceFactorCode
    kind: FactorKind
    reference: str
    observed: Decimal | str | None
    requirement: str | None
    explanation: str


class PublicEvidence(PublicModel):
    historical_evidence_status: HistoricalEvidenceStatus
    sample_sufficiency_status: SampleSufficiencyStatus
    decision_evidence_status: DecisionEvidenceStatus
    sample_evidence: PublicSampleEvidence
    historical_error: PublicHistoricalError
    directional_evidence: PublicDirectionalEvidence
    normalized_signals: PublicNormalizedSignals
    factors: tuple[PublicEvidenceFactor, ...]
    assessment_limitations: tuple[EvidenceFactorCode, ...]


class PublicCurrentState(PublicModel):
    current_input_freshness: str
    input_freshness_at_generation: str
    latest_source_date: date | None
    context_state: str
    source_superseded: bool
    forecast_superseded: bool
    stored_live_decision_eligible: bool
    effective_live_decision_eligible: bool


class PublicPolicy(PublicModel):
    movement_threshold_pct: Decimal
    min_history_observations: int
    min_evaluation_points: int
    error_multiplier: Decimal
    supported_horizons: tuple[int, ...]


class DecisionProvenance(PublicModel):
    model_name: str
    model_version: str
    methodology_supported: bool
    generated_at: datetime
    evaluated_at: datetime
    engine_version: Literal['decision-rules-v1']
    assessment_version: Literal['evidence-v1']

    @field_validator('generated_at', 'evaluated_at')
    @classmethod
    def authoritative_utc(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError('Authoritative timestamps must be timezone-aware')
        return value.astimezone(timezone.utc)


class DecisionAPIResponse(PublicModel):
    identity: DecisionSeries
    forecast: DecisionForecast
    decision: PublicDecision
    evidence: PublicEvidence
    current_state: PublicCurrentState
    policy: PublicPolicy
    provenance: DecisionProvenance
