from datetime import date
from typing import Literal
import uuid

from pydantic import BaseModel, Field

# System user ID for automated alerts until user subscriptions are implemented
SYSTEM_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


class RateTrendSchema(BaseModel):
    """AI-1 output: 30-day statistical trend for one trade lane."""

    trade_lane: str
    computed_date: date
    avg_7d_usd: float = Field(ge=0)
    avg_30d_usd: float = Field(ge=0)
    change_7d_pct: float | None = None
    change_30d_pct: float | None = None
    trend: Literal["rising", "stable", "falling", "insufficient_data"]
    slope_per_week: float | None = None
    r_squared: float | None = Field(default=None, ge=0, le=1)


class RateAnomalySchema(BaseModel):
    """AI-2 output: one detected anomaly event for one trade lane."""

    user_id: uuid.UUID = Field(default_factory=lambda: SYSTEM_USER_ID)
    trade_lane: str
    alert_type: Literal["rate_spike", "rate_drop"]
    message: str = Field(min_length=10)
    magnitude_pct: float
    direction: Literal["up", "down"]
    z_score: float
    latest_rate: float = Field(ge=0)
    mean_30d: float = Field(ge=0)
    # P3 Enhancement #2: effective threshold used for this detection.
    threshold_used: float = Field(default=2.5, ge=0)
    # P3 Enhancement #3: multi-day event tracking.
    pattern_type: Literal["one_day", "sustained"] = "one_day"
    duration_days: int = Field(default=1, ge=1)
    cumulative_magnitude_pct: float | None = None