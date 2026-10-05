"""route-intelligence-v1: market-lane evidence, never a physical-route model."""
from datetime import datetime
from enum import Enum
from typing import Literal
from pydantic import BaseModel, ConfigDict, field_validator
from app.schemas.decision import DecisionInput, DecisionResult
from app.schemas.reliability import EvidenceAssessment

METHODOLOGY = "route-intelligence-v1"


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class MarketSeries(Frozen):
    source: str
    trade_lane: str
    container_type: str

    @field_validator("source", "trade_lane", "container_type")
    @classmethod
    def exact_identity(cls, value):
        if not value.strip() or not all(c.isprintable() for c in value):
            raise ValueError("Identity must be nonblank and printable; no normalization")
        return value


class ProvenanceClass(str, Enum):
    VERIFIED_SOURCE_DATA = "VERIFIED_SOURCE_DATA"
    PERSISTED_APPLICATION_DATA = "PERSISTED_APPLICATION_DATA"
    DERIVED_INTERPRETATION = "DERIVED_INTERPRETATION"
    SEEDED_DEMO_DATA = "SEEDED_DEMO_DATA"
    UNVERIFIED = "UNVERIFIED"


class Availability(str, Enum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    EXCLUDED_UNVERIFIED = "EXCLUDED_UNVERIFIED"


class AdvisorySnapshot(Frozen):
    record_id: str
    carrier: str
    series: MarketSeries | None = None
    classification: ProvenanceClass
    source_url: str | None = None
    source_text: str | None = None
    derived_summary: str | None = None
    published_at: datetime | None = None
    observed_at: datetime | None = None
    source_effective_at: datetime | None = None
    derived_effective_at: datetime | None = None

    @field_validator("record_id", "carrier")
    @classmethod
    def nonblank(cls, value):
        return MarketSeries.exact_identity(value)


class RouteEvidenceRequest(Frozen):
    series: MarketSeries
    evaluated_at: datetime
    decision_input: DecisionInput | None = None
    advisories: tuple[AdvisorySnapshot, ...] = ()


class EvidenceStatus(Frozen):
    availability: Availability
    reason: str


class AdvisoryContext(Frozen):
    snapshot: AdvisorySnapshot
    status: EvidenceStatus


class OperationalGaps(Frozen):
    physical_route: EvidenceStatus
    port_operations: EvidenceStatus
    distance: EvidenceStatus
    transit_time: EvidenceStatus
    route_alternatives: EvidenceStatus
    route_ranking: EvidenceStatus
    operational_route_risk: EvidenceStatus


class RouteEvidenceResult(Frozen):
    methodology: Literal["route-intelligence-v1"] = METHODOLOGY
    series: MarketSeries
    evaluated_at: datetime
    forecast_status: EvidenceStatus
    decision_status: EvidenceStatus
    assessment_status: EvidenceStatus
    decision: DecisionResult | None
    assessment: EvidenceAssessment | None
    advisory_status: EvidenceStatus
    advisories: tuple[AdvisoryContext, ...]
    advisory_conflicts: tuple[str, ...]
    operational: OperationalGaps
    limitations: tuple[str, ...]
    provenance: tuple[str, ...]
    fingerprint: str
