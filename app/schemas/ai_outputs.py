from __future__ import annotations

from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field


class CarrierSummaryOutput(BaseModel):
    summary: str = Field(..., min_length=10, max_length=500)
    affected_lanes: list[str]
    effective_date: Optional[date] = None  # noqa: UP045
    impact_severity: Literal["low", "medium", "high"]

class RouteBriefOutput(BaseModel):
    brief_markdown: str = Field(..., min_length=100)
    recommendation: Literal["ship_now", "wait", "reroute"]
    risk_level: Literal["low", "medium", "high"]

class RateOutlookOutput(BaseModel):
    """Legacy v1 output only; T07 uses GroundedRateOutlookOutput."""
    outlook_text: str = Field(..., min_length=50, max_length=1500)
    recommendation: Literal["book_now", "wait", "hedge"]
    confidence: int = Field(..., ge=0, le=100)


class GroundedRateOutlookOutput(BaseModel):
    """Narrative only; numerical fields and booking advice are application-excluded."""
    model_config = {"extra": "forbid"}
    outlook_text: str = Field(..., min_length=50, max_length=1500)
