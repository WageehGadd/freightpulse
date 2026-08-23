from datetime import date, datetime
from pydantic import BaseModel


class CarrierAdvisoryResponse(BaseModel):
    id: str
    carrier: str
    advisory_type: str
    title: str
    summary: str | None
    affected_lanes: list[str] | None
    effective_date: date | None
    impact_severity: str | None
    source_url: str | None
    published_at: datetime | None


class CarrierAdvisoriesListResponse(BaseModel):
    advisories: list[CarrierAdvisoryResponse]


class CarrierItem(BaseModel):
    name: str
    code: str | None = None
    full_name: str | None = None
    advisories_count: int = 0


class CarriersListResponse(BaseModel):
    carriers: list[CarrierItem]