"""
Forecast API schemas — T06.

Semantic structure: forecast / evidence / provenance / safety.
No confidence percentages are exposed (T09 concern).
"""
import uuid
from datetime import date, datetime
from typing import Optional, Literal

from pydantic import BaseModel, Field


class ForecastSeriesSchema(BaseModel):
    source: str
    trade_lane: str
    container_type: str


class ForecastValueSchema(BaseModel):
    model_config = {"protected_namespaces": ()}
    forecast_for_date: date
    predicted_rate: float
    model: str
    model_version: str
    horizon: int


class ForecastEvidenceSchema(BaseModel):
    history_observations: int
    evaluation_points: int
    mae: float
    rmse: float
    smape: float
    directional_accuracy: float
    data_readiness: str


class ForecastProvenanceSchema(BaseModel):
    latest_observation_date: date
    latest_actual_rate: float
    input_freshness_at_generation: str = Field(description="Stored historical source freshness; never current decision eligibility.")
    current_input_freshness: str = Field(description="T02 freshness of this artifact's source cutoff at freshness_evaluated_at; not a query for newer source data.")
    freshness_evaluated_at: datetime
    generated_at: datetime


class ForecastSafetySchema(BaseModel):
    live_decision_eligible: bool
    warning: Optional[str]


class RateForecastResponse(BaseModel):
    """Full forecast artifact response — always includes evidence and safety."""
    id: uuid.UUID
    series: ForecastSeriesSchema
    forecast: ForecastValueSchema
    evidence: ForecastEvidenceSchema
    provenance: ForecastProvenanceSchema
    safety: ForecastSafetySchema

    class Config:
        from_attributes = True


class ForecastListResponse(BaseModel):
    forecasts: list[RateForecastResponse]
    count: int


class ForecastGenerateResponse(BaseModel):
    attempted: int
    generated: int
    failed: int
    status: Literal["success", "partial_success", "failure"]
    message: str
