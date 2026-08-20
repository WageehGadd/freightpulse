from datetime import date
from typing import Literal, List, Optional
from pydantic import BaseModel, Field


class CarrierSummaryOutput(BaseModel):
    summary: str = Field(..., min_length=10)
    affected_lanes: Optional[List[str]] = Field(default=None)
    impact_severity: Optional[Literal["low", "medium", "high"]] = Field(default=None)
    effective_date: Optional[date] = Field(default=None)


class RateOutlookOutput(BaseModel):
    outlook_text: str = Field(..., min_length=50)
    recommendation: Literal["book_now", "wait", "hedge"]
    confidence: int = Field(..., ge=0, le=100)


class RouteBriefOutput(BaseModel):
    brief_markdown: str = Field(..., min_length=100)
    recommendation: Literal["ship_now", "wait", "reroute"]
    risk_level: Literal["low", "medium", "high"]
