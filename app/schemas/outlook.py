"""Additive authoritative T07 contract; monetary values are exact decimal strings."""
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal
from pydantic import BaseModel
from app.schemas.forecast import RateForecastResponse

class GroundedOutlookCreateResponse(BaseModel):
    trend_id: str
    outlook_id: uuid.UUID
    forecast_id: uuid.UUID
    status: str

class ExactForecastValue(BaseModel):
    predicted_rate: Decimal
    latest_actual_rate: Decimal
    expected_change: Decimal
    expected_change_pct: Decimal | None

class NarrationResponse(BaseModel):
    status: str
    text: str | None
    error_message: str | None
    attempt_count: int
    retryable: bool
    retry_after: datetime | None
    input_evidence: dict | None

class GroundedOutlookResponse(BaseModel):
    id: uuid.UUID
    trend_id: uuid.UUID
    forecast_id: uuid.UUID
    prompt_version: str
    created_at: datetime
    completed_at: datetime | None
    quantitative: RateForecastResponse
    exact_values: ExactForecastValue
    context_state: Literal["current", "superseded", "historical_trend", "source_unavailable"]
    effective_live_decision_eligible: bool
    context_warning: str | None
    narration: NarrationResponse
