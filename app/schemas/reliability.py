"""Internal, immutable evidence descriptions; T08 alone owns decision safety."""
import math
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Literal
from uuid import UUID
from pydantic import field_serializer

from app.schemas.decision import DecisionResult, ForecastState, Frozen, Signals

ASSESSMENT_VERSION = "evidence-v1"


class HistoricalEvidenceStatus(str, Enum):
    UNAVAILABLE = "UNAVAILABLE"
    INVALID_OR_INCOMPLETE = "INVALID_OR_INCOMPLETE"
    UNSUPPORTED = "UNSUPPORTED"
    AVAILABLE = "AVAILABLE"


class SampleSufficiencyStatus(str, Enum):
    NOT_ASSESSABLE = "NOT_ASSESSABLE"
    LIMITED = "LIMITED"
    POLICY_MINIMUMS_MET = "POLICY_MINIMUMS_MET"


class DecisionEvidenceStatus(str, Enum):
    UNAVAILABLE = "UNAVAILABLE"
    BLOCKED = "BLOCKED"
    MONITOR_ONLY = "MONITOR_ONLY"
    DIRECTIONAL_RULES_PASSED = "DIRECTIONAL_RULES_PASSED"


class EvidenceDimension(str, Enum):
    METHODOLOGY = "METHODOLOGY"
    SAMPLE = "SAMPLE"
    HISTORICAL_ERROR = "HISTORICAL_ERROR"
    DIRECTIONAL = "DIRECTIONAL"


class FactorKind(str, Enum):
    SUPPORTING = "SUPPORTING"
    LIMITING = "LIMITING"
    INFORMATIONAL = "INFORMATIONAL"


class EvidenceFactorCode(str, Enum):
    METHODOLOGY_UNSUPPORTED = "METHODOLOGY_UNSUPPORTED"
    HISTORICAL_EVIDENCE_INVALID_OR_INCOMPLETE = "HISTORICAL_EVIDENCE_INVALID_OR_INCOMPLETE"
    POLICY_SAMPLE_MINIMUM_MET = "POLICY_SAMPLE_MINIMUM_MET"
    POLICY_SAMPLE_MINIMUM_NOT_MET = "POLICY_SAMPLE_MINIMUM_NOT_MET"
    SAMPLE_COUNTS_INVALID_OR_UNAVAILABLE = "SAMPLE_COUNTS_INVALID_OR_UNAVAILABLE"
    NORMALIZED_ERROR_AVAILABLE = "NORMALIZED_ERROR_AVAILABLE"
    NORMALIZED_ERROR_UNAVAILABLE = "NORMALIZED_ERROR_UNAVAILABLE"
    SELECTION_WINDOW_NOT_INDEPENDENT = "SELECTION_WINDOW_NOT_INDEPENDENT"
    DIRECTIONAL_DENOMINATOR_UNAVAILABLE = "DIRECTIONAL_DENOMINATOR_UNAVAILABLE"


class EvidenceFactor(Frozen):
    dimension: EvidenceDimension
    code: EvidenceFactorCode
    kind: FactorKind
    reference: str
    observed: Decimal | str | None = None
    requirement: str | None = None
    explanation: str


class SampleEvidence(Frozen):
    history_observations: int | None
    evaluation_points: int | None
    data_readiness: str | None
    sample_sufficiency_status: SampleSufficiencyStatus


class HistoricalErrorEvidence(Frozen):
    mae: float | None
    rmse: float | None
    smape: float | None
    mae_relative_to_latest_actual_pct: Decimal | None
    rmse_relative_to_latest_actual_pct: Decimal | None
    movement_to_mae_ratio: Decimal | None


class DirectionalEvidence(Frozen):
    directional_accuracy: float | None
    # T06/T08 do not record the T04 valid-direction denominator.
    valid_directional_sample_count: Literal[None] = None


class DecisionMarginEvidence(Frozen):
    signals: Signals
    movement_threshold_pct: Decimal
    error_multiplier: Decimal
    movement_within_error_scale: bool | None


class ModelProvenance(Frozen):
    model_config = {"frozen": True, "extra": "forbid", "protected_namespaces": ()}
    forecast_id: UUID
    model_name: str
    model_version: str
    generated_at: datetime
    latest_observation_date: date
    forecast_for_date: date
    forecast_horizon: int
    methodology_supported: bool


class EvidenceAssessment(Frozen):
    assessment_version: Literal["evidence-v1"] = ASSESSMENT_VERSION
    decision_result: DecisionResult
    evaluated_at: datetime
    historical_evidence_status: HistoricalEvidenceStatus
    sample_sufficiency_status: SampleSufficiencyStatus
    decision_evidence_status: DecisionEvidenceStatus
    sample_evidence: SampleEvidence
    historical_error: HistoricalErrorEvidence
    directional_evidence: DirectionalEvidence
    current_state: ForecastState | None
    decision_margin: DecisionMarginEvidence
    provenance: ModelProvenance | None
    factors: tuple[EvidenceFactor, ...]
    # T08 reasons/limitations are retained losslessly in decision_result, not recoded.
    assessment_limitations: tuple[EvidenceFactorCode, ...]


    @field_serializer("decision_result", "decision_margin", when_used="json")
    def json_safe_evidence(self, value):
        # Preserve the original frozen evidence in memory. Non-finite raw numbers
        # have no JSON numeric representation; expose null rather than sentinel strings.
        return _json_safe_numbers(value.model_dump(mode="python"))


def _json_safe_numbers(value):
    if isinstance(value, Decimal) and not value.is_finite():
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: _json_safe_numbers(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_safe_numbers(item) for item in value]
    return value
