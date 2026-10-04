"""Frozen internal T14 contracts; checkpoint proposals are not accepted writes."""
from datetime import datetime
from enum import Enum
from typing import Literal
from uuid import UUID

from pydantic import Field, StrictBool, field_validator, model_validator

from app.schemas.decision import Decision, DecisionResult, Frozen, SeriesIdentity
from app.schemas.reliability import (
    DecisionEvidenceStatus, EvidenceAssessment, HistoricalEvidenceStatus,
    SampleSufficiencyStatus,
)

POLICY_VERSION = "predictive-alerts-v1"
DIRECTIONS = frozenset((Decision.CONSIDER_EARLIER_BOOKING,
                        Decision.CONSIDER_LATER_BOOKING))
Digest = str


def expected_evidence_status(decision):
    """Existing T09 outcome/status correspondence, not a decision policy."""
    return {
        Decision.UNAVAILABLE: DecisionEvidenceStatus.UNAVAILABLE,
        Decision.WITHHOLD: DecisionEvidenceStatus.BLOCKED,
        Decision.MONITOR: DecisionEvidenceStatus.MONITOR_ONLY,
        Decision.CONSIDER_EARLIER_BOOKING: DecisionEvidenceStatus.DIRECTIONAL_RULES_PASSED,
        Decision.CONSIDER_LATER_BOOKING: DecisionEvidenceStatus.DIRECTIONAL_RULES_PASSED,
    }[decision]


class AlertStatus(str, Enum):
    BASELINE_ONLY = "BASELINE_ONLY"
    EMIT = "EMIT"
    SUPPRESS = "SUPPRESS"
    INVALID_INPUT = "INVALID_INPUT"


class Transition(str, Enum):
    DIRECTIONAL_ENTERED = "DIRECTIONAL_ENTERED"
    DIRECTION_REVERSED = "DIRECTION_REVERSED"
    ACTIONABILITY_WITHDRAWN = "ACTIONABILITY_WITHDRAWN"


class SignalCategory(str, Enum):
    DIRECTIONAL = "DIRECTIONAL"
    OPERATIONAL = "OPERATIONAL"


class AlertReason(str, Enum):
    INVALID_STRUCTURE = "INVALID_STRUCTURE"
    SERIES_MISMATCH = "SERIES_MISMATCH"
    PAIR_MISMATCH = "PAIR_MISMATCH"
    GENERATION_MISMATCH = "GENERATION_MISMATCH"
    SAFETY_CONTRADICTION = "SAFETY_CONTRADICTION"
    INVALID_CHECKPOINT = "INVALID_CHECKPOINT"
    PREVIOUS_CHECKPOINT_ABSENT = "PREVIOUS_CHECKPOINT_ABSENT"
    UNCHANGED_DIRECTION = "UNCHANGED_DIRECTION"
    NO_DIRECTIONAL_TRANSITION = "NO_DIRECTIONAL_TRANSITION"
    EVIDENCE_NOT_AVAILABLE = "EVIDENCE_NOT_AVAILABLE"
    STATE_TRANSITION = "STATE_TRANSITION"


class ForecastGeneration(Frozen):
    forecast_id: UUID
    generated_at: datetime

    @field_validator("generated_at")
    @classmethod
    def aware_generation(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Generation must have an explicit timezone")
        return value


class CheckpointState(Frozen):
    # Preserve T08 outcome separately from the evidence-supported direction.
    decision: Decision
    actionable: StrictBool
    eligible_direction: Decision | None
    generation: ForecastGeneration | None
    historical_evidence_status: HistoricalEvidenceStatus
    sample_sufficiency_status: SampleSufficiencyStatus
    decision_evidence_status: DecisionEvidenceStatus
    evidence_fingerprint: Digest = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def consistent(self):
        if self.actionable != (self.decision in DIRECTIONS):
            raise ValueError("T08 actionability disagrees with decision")
        if (self.decision == Decision.UNAVAILABLE) != (self.generation is None):
            raise ValueError("Unavailable state must have no generation")
        if self.decision_evidence_status != expected_evidence_status(self.decision):
            raise ValueError("Checkpoint decision/evidence status disagree")
        if self.generation is None and (
            self.historical_evidence_status != HistoricalEvidenceStatus.UNAVAILABLE
            or self.sample_sufficiency_status != SampleSufficiencyStatus.NOT_ASSESSABLE
        ):
            raise ValueError("Absent forecast cannot have historical/sample evidence")
        expected = self.decision if (
            self.actionable
            and self.historical_evidence_status == HistoricalEvidenceStatus.AVAILABLE
            and self.sample_sufficiency_status == SampleSufficiencyStatus.POLICY_MINIMUMS_MET
            and self.decision_evidence_status == DecisionEvidenceStatus.DIRECTIONAL_RULES_PASSED
        ) else None
        if self.eligible_direction != expected:
            raise ValueError("Eligible direction contradicts authoritative evidence")
        return self


class AlertCheckpoint(Frozen):
    policy_version: Literal["predictive-alerts-v1"] = POLICY_VERSION
    series: SeriesIdentity
    state: CheckpointState
    previous_token: Digest | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    state_fingerprint: Digest = Field(pattern=r"^[0-9a-f]{64}$")
    accepted_checkpoint_token: Digest = Field(pattern=r"^[0-9a-f]{64}$")


class PredictiveAlertInput(Frozen):
    policy_version: Literal["predictive-alerts-v1"] = POLICY_VERSION
    series: SeriesIdentity
    decision: DecisionResult
    evidence: EvidenceAssessment
    previous_checkpoint: AlertCheckpoint | None = None


class PredictiveAlertResult(Frozen):
    policy_version: Literal["predictive-alerts-v1"] = POLICY_VERSION
    status: AlertStatus
    transition: Transition | None = None
    category: SignalCategory | None = None
    signal_identity: Digest | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    reasons: tuple[AlertReason, ...]
    evidence: EvidenceAssessment | None = None
    next_checkpoint: AlertCheckpoint | None = None

    @model_validator(mode="after")
    def consistent_output(self):
        emitted = self.status == AlertStatus.EMIT
        if emitted != all(v is not None for v in (
            self.transition, self.category, self.signal_identity)):
            raise ValueError("Emitted results require complete signal identity")
        if not emitted and any(v is not None for v in (
            self.transition, self.category, self.signal_identity)):
            raise ValueError("Non-emitted results cannot carry signals")
        if (self.status == AlertStatus.INVALID_INPUT) != (self.next_checkpoint is None):
            raise ValueError("Invalid input cannot advance a checkpoint")
        if (self.status == AlertStatus.INVALID_INPUT) != (self.evidence is None):
            raise ValueError("Only valid results carry matching evidence")
        if emitted:
            expected = (SignalCategory.OPERATIONAL if
                        self.transition == Transition.ACTIONABILITY_WITHDRAWN
                        else SignalCategory.DIRECTIONAL)
            if self.category != expected:
                raise ValueError("Withdrawal must be operational")
            if expected == SignalCategory.DIRECTIONAL and self.next_checkpoint.state.eligible_direction is None:
                raise ValueError("Directional emission requires an eligible direction")
        return self
