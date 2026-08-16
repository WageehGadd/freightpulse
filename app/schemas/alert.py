from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, model_validator
from datetime import datetime, date

class RateAlertRuleCreate(BaseModel):
    trade_lane: str = Field(..., description="Trade lane to monitor")
    alert_type: Literal["rate_spike", "rate_drop", "threshold_above", "threshold_below"]
    magnitude_pct: float | None = None
    target_usd: float | None = None

    @model_validator(mode="after")
    def validate_conditions(self):
        if self.alert_type in ("rate_spike", "rate_drop"):
            if self.magnitude_pct is None:
                raise ValueError(f"magnitude_pct is required for {self.alert_type}")
            if self.target_usd is not None:
                raise ValueError(f"target_usd must be absent for {self.alert_type}")
        elif self.alert_type in ("threshold_above", "threshold_below"):
            if self.target_usd is None:
                raise ValueError(f"target_usd is required for {self.alert_type}")
            if self.magnitude_pct is not None:
                raise ValueError(f"magnitude_pct must be absent for {self.alert_type}")
        return self

class RateAlertRuleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    trade_lane: str
    alert_type: str
    magnitude_pct: float | None
    target_usd: float | None
    is_active: bool
    created_at: datetime

class RateAlertEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    rule_id: UUID
    trade_lane: str
    alert_type: str | None
    message: str
    magnitude_pct: float | None
    is_read: bool
    evaluation_date: date
    created_at: datetime
