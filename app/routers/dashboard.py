from datetime import date, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.models import FreightRate, RateTrend, PortCongestion, CarrierAdvisory, RateAlert
from app.schemas.dashboard import (
    DashboardResponse,
    DashboardLaneSummary,
    DashboardRateTrendPoint,
    DashboardPortSummary,
    DashboardAdvisorySummary,
)

from app.auth.rate_limit import RateLimiter

router = APIRouter(dependencies=[Depends(RateLimiter)])


@router.get("/dashboard", response_model=DashboardResponse)
async def get_dashboard(db: AsyncSession = Depends(get_db)):
    # Get the latest rate for each trade lane
    latest_dates_subq = (
        select(FreightRate.trade_lane, func.max(FreightRate.rate_date).label("max_date"))
        .group_by(FreightRate.trade_lane)
        .subquery()
    )
    lanes_stmt = select(FreightRate).join(
        latest_dates_subq,
        (FreightRate.trade_lane == latest_dates_subq.c.trade_lane)
        & (FreightRate.rate_date == latest_dates_subq.c.max_date),
    )
    latest_rates = (await db.execute(lanes_stmt)).scalars().all()

    # Daily average across all tracked rates for the chart on the dashboard.
    # The interval includes today and the previous 29 calendar days.
    trend_cutoff = date.today() - timedelta(days=29)
    rate_trend_stmt = (
        select(
            FreightRate.rate_date,
            func.avg(FreightRate.rate_usd).label("avg_rate_usd"),
        )
        .where(FreightRate.rate_date >= trend_cutoff)
        .group_by(FreightRate.rate_date)
        .order_by(FreightRate.rate_date.asc())
    )
    rate_trend_rows = (await db.execute(rate_trend_stmt)).all()

    lanes_summary = []
    seen_lanes = set()
    for rate in latest_rates:
        if rate.trade_lane in seen_lanes:
            continue
        seen_lanes.add(rate.trade_lane)

        trend_stmt = (
            select(RateTrend)
            .where(RateTrend.trade_lane == rate.trade_lane)
            .order_by(RateTrend.computed_date.desc())
            .limit(1)
        )
        trend_row = (await db.execute(trend_stmt)).scalar_one_or_none()

        lanes_summary.append(
            DashboardLaneSummary(
                trade_lane=rate.trade_lane,
                current_rate=float(rate.rate_usd),
                trend=trend_row.trend if trend_row else None,
                change_7d_pct=trend_row.change_7d_pct if trend_row else None,
            )
        )
# Get an overview of port congestion
    latest_port_subq = (
        select(PortCongestion.port_code, func.max(PortCongestion.measured_at).label("max_time"))
        .group_by(PortCongestion.port_code)
        .subquery()
    )
    ports_stmt = select(PortCongestion).join(
        latest_port_subq,
        (PortCongestion.port_code == latest_port_subq.c.port_code)
        & (PortCongestion.measured_at == latest_port_subq.c.max_time),
    )
    ports = (await db.execute(ports_stmt)).scalars().all()

    # Get the latest 5 carrier advisories published
    advisories_stmt = select(CarrierAdvisory).order_by(CarrierAdvisory.published_at.desc()).limit(5)
    advisories = (await db.execute(advisories_stmt)).scalars().all()

    # Get the count of unread rate alerts
    unread_count = await db.scalar(
        select(func.count()).select_from(RateAlert).where(RateAlert.is_read == False)  # noqa: E712
    )

    return DashboardResponse(
        tracked_lanes_count=len(seen_lanes),
        lanes_summary=lanes_summary,
        rate_trend_30d=[
            DashboardRateTrendPoint(
                date=row.rate_date,
                avg_rate_usd=float(row.avg_rate_usd),
            )
            for row in rate_trend_rows
        ],
        port_congestion_overview=[
            DashboardPortSummary(
                port_code=p.port_code,
                port_name=p.port_name,
                severity=p.severity,
                congestion_index=p.congestion_index,
            )
            for p in ports
        ],
        recent_advisories=[
            DashboardAdvisorySummary(
                carrier=a.carrier,
                title=a.title,
                advisory_type=a.advisory_type,
                published_at=a.published_at,
            )
            for a in advisories
        ],
        unread_alert_count=unread_count or 0,
    )   
