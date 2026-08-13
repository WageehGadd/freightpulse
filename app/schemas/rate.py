from datetime import date, datetime
from pydantic import BaseModel


class RateHistoryPoint(BaseModel):
    date: date
    rate_usd: float


class TrendInfo(BaseModel):
    direction: str | None  # rising | stable | falling
    slope_per_week: float | None
    change_7d_pct: float | None
    change_30d_pct: float | None
    anomaly_flag: bool = False


class LaneAllResponse(BaseModel):
    trade_lane: str
    container_type: str
    current_rate_usd: float | None
    source: str | None
    rate_date: date | None
    change_7d_pct: float | None
    trend: str | None
    data_freshness: datetime | None


class RatesAllResponse(BaseModel):
    lanes: list[LaneAllResponse]


class LaneDetailResponse(BaseModel):
    trade_lane: str
    container_type: str
    current_rate: float | None
    history: list[RateHistoryPoint]
    trend: TrendInfo


class RateCompareResponse(BaseModel):
    trade_lane: str
    container_type: str
    current_rate: float | None
    avg_7d: float | None
    avg_30d: float | None
    avg_90d: float | None
    vs_7d_pct: float | None
    vs_30d_pct: float | None
    vs_90d_pct: float | None