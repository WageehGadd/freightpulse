from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


class CarrierSummaryOutput(BaseModel):
    summary: str = Field(..., min_length=10, max_length=500)
    advisory_type: Literal["surcharge", "route_suspension", "schedule_change", "congestion"]
    affected_lanes: list[str]
    effective_date: date | None = None
    impact_severity: Literal["low", "medium", "high"]

class RouteBriefOutput(BaseModel):
    brief_markdown: str = Field(..., min_length=100)
    recommendation: Literal["ship_now", "wait", "reroute"]
    risk_level: Literal["low", "medium", "high"]

class RateOutlookOutput(BaseModel):
    outlook_text: str = Field(..., min_length=50, max_length=1500)
    recommendation: Literal["book_now", "wait", "hedge"]
    confidence: int = Field(..., ge=0, le=100)
