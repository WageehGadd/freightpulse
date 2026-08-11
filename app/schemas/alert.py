from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class AlertResponse(BaseModel):
    id: UUID
    trade_lane: str
    alert_type: str | None
    message: str
    magnitude_pct: float | None
    is_read: bool
    created_at: datetime


class AlertsListResponse(BaseModel):
    alerts: list[AlertResponse]


class AlertReadResponse(BaseModel):
    id: UUID
    is_read: bool
