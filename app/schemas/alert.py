from datetime import datetime
from uuid import UUID
from typing import Literal, Optional, List
from pydantic import BaseModel, model_validator


class AlertResponse(BaseModel):
    id: UUID
    trade_lane: str
    alert_type: str | None
    message: str
    magnitude_pct: float | None
    is_read: bool
    created_at: datetime

    class Config:
        from_attributes = True


class AlertsListResponse(BaseModel):
    alerts: list[AlertResponse]


class AlertReadResponse(BaseModel):
    id: UUID
    is_read: bool


class AlertRuleCreateRequest(BaseModel):
    trade_lane: str
    alert_type: Literal["rate_spike", "rate_drop", "threshold_above", "threshold_below"]
    magnitude_pct: Optional[float] = None
    target_usd: Optional[float] = None

    @model_validator(mode="after")
    def validate_rule_config(self):
        if self.alert_type in ("rate_spike", "rate_drop"):
            if self.magnitude_pct is None:
                raise ValueError("magnitude_pct is required for rate spike/drop rules")
        elif self.alert_type in ("threshold_above", "threshold_below"):
            if self.target_usd is None:
                raise ValueError("target_usd is required for threshold rules")
        return self


class AlertRuleResponse(BaseModel):
    id: UUID
    trade_lane: str
    alert_type: str
    magnitude_pct: Optional[float] = None
    target_usd: Optional[float] = None
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True
