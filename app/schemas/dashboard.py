from datetime import date, datetime
from pydantic import BaseModel


class DashboardLaneSummary(BaseModel):
    trade_lane: str
    current_rate: float | None
    trend: str | None
    change_7d_pct: float | None


class DashboardRateTrendPoint(BaseModel):
    date: date
    avg_rate_usd: float


class DashboardPortSummary(BaseModel):
    port_code: str
    port_name: str
    severity: str | None
    congestion_index: float | None


class DashboardAdvisorySummary(BaseModel):
    carrier: str
    title: str
    advisory_type: str
    published_at: datetime | None


class DashboardResponse(BaseModel):
    tracked_lanes_count: int
    lanes_summary: list[DashboardLaneSummary]
    rate_trend_30d: list[DashboardRateTrendPoint]
    port_congestion_overview: list[DashboardPortSummary]
    recent_advisories: list[DashboardAdvisorySummary]
    unread_alert_count: int
