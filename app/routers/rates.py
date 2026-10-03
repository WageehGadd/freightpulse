import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import FreightRate, RateTrend
from app.schemas.rate import (
    LaneAllResponse,
    LaneDetailResponse,
    RateCompareResponse,
    RateHistoryPoint,
    RatesAllResponse,
    TrendInfo,
)
from app.tasks.rate_outlook_generation import generate_rate_outlook
from app.services.rate_outlook import RateOutlookService
from app.schemas.outlook import GroundedOutlookCreateResponse, GroundedOutlookResponse

from app.auth.rate_limit import RateLimiter

logger = logging.getLogger(__name__)
router = APIRouter(dependencies=[Depends(RateLimiter())])


@router.get("/rates/all", response_model=RatesAllResponse)
async def get_all_lanes(db: AsyncSession = Depends(get_db)):
    latest_dates_subq = (
        select(
            FreightRate.trade_lane,
            FreightRate.container_type,
            func.max(FreightRate.rate_date).label("max_date"),
        )
        .group_by(FreightRate.trade_lane, FreightRate.container_type)
        .subquery()
    )

    stmt = select(FreightRate).join(
        latest_dates_subq,
        (FreightRate.trade_lane == latest_dates_subq.c.trade_lane)
        & (FreightRate.container_type == latest_dates_subq.c.container_type)
        & (FreightRate.rate_date == latest_dates_subq.c.max_date),
    )
    result = await db.execute(stmt)
    latest_rates = result.scalars().all()

    lanes = []
    for rate in latest_rates:
        trend_stmt = (
            select(RateTrend)
            .where(RateTrend.trade_lane == rate.trade_lane)
            .order_by(RateTrend.computed_date.desc())
            .limit(1)
        )
        trend_row = (await db.execute(trend_stmt)).scalar_one_or_none()

        lanes.append(
            LaneAllResponse(
                trade_lane=rate.trade_lane,
                container_type=rate.container_type,
                current_rate_usd=float(rate.rate_usd),
                source=rate.source,
                rate_date=rate.rate_date,
                change_7d_pct=trend_row.change_7d_pct if trend_row else None,
                trend=trend_row.trend if trend_row else None,
                data_freshness=rate.created_at,
            )
        )

    return RatesAllResponse(lanes=lanes)


@router.get("/rates/compare", response_model=RateCompareResponse)
async def compare_rate(
    trade_lane: str = Query(...),
    container_type: str = Query(default="40ft", pattern="^(20ft|40ft)$"),
    db: AsyncSession = Depends(get_db),
):
    latest_stmt = (
        select(FreightRate)
        .where(FreightRate.trade_lane == trade_lane, FreightRate.container_type == container_type)
        .order_by(FreightRate.rate_date.desc())
        .limit(1)
    )
    latest = (await db.execute(latest_stmt)).scalar_one_or_none()

    if not latest:
        raise HTTPException(status_code=404, detail=f"No rate data found for lane '{trade_lane}'")

    async def avg_over_days(days: int) -> float | None:
        cutoff = datetime.now(timezone.utc).date() - timedelta(days=days)
        stmt = select(func.avg(FreightRate.rate_usd)).where(
            FreightRate.trade_lane == trade_lane,
            FreightRate.container_type == container_type,
            FreightRate.rate_date >= cutoff,
        )
        avg = await db.scalar(stmt)
        return float(avg) if avg is not None else None

    avg_7d = await avg_over_days(7)
    avg_30d = await avg_over_days(30)
    avg_90d = await avg_over_days(90)
    current = float(latest.rate_usd)

    def pct(base: float | None) -> float | None:
        return round(((current - base) / base) * 100, 2) if base else None

    return RateCompareResponse(
        trade_lane=trade_lane,
        container_type=container_type,
        current_rate=current,
        avg_7d=avg_7d,
        avg_30d=avg_30d,
        avg_90d=avg_90d,
        vs_7d_pct=pct(avg_7d),
        vs_30d_pct=pct(avg_30d),
        vs_90d_pct=pct(avg_90d),
    )


@router.get("/rates/{lane}", response_model=LaneDetailResponse)
async def get_lane_rate(
    lane: str,
    container_type: str = Query(default="40ft", pattern="^(20ft|40ft)$"),
    db: AsyncSession = Depends(get_db),
):
    cutoff_date = datetime.now(timezone.utc).date() - timedelta(days=30)

    history_stmt = (
        select(FreightRate)
        .where(
            FreightRate.trade_lane == lane,
            FreightRate.container_type == container_type,
            FreightRate.rate_date >= cutoff_date,
        )
        .order_by(FreightRate.rate_date.asc())
    )
    rates = (await db.execute(history_stmt)).scalars().all()

    if not rates:
        raise HTTPException(status_code=404, detail=f"No rate data found for lane '{lane}'")

    latest = rates[-1]

    trend_stmt = (
        select(RateTrend)
        .where(RateTrend.trade_lane == lane)
        .order_by(RateTrend.computed_date.desc())
        .limit(1)
    )
    trend_row = (await db.execute(trend_stmt)).scalar_one_or_none()

    return LaneDetailResponse(
        trade_lane=lane,
        container_type=container_type,
        current_rate=float(latest.rate_usd),
        history=[RateHistoryPoint(date=r.rate_date, rate_usd=float(r.rate_usd)) for r in rates],
        trend=TrendInfo(
            id=trend_row.id if trend_row else None,
            direction=trend_row.trend if trend_row else None,
            slope_per_week=trend_row.slope_per_week if trend_row else None,
            change_7d_pct=trend_row.change_7d_pct if trend_row else None,
            change_30d_pct=trend_row.change_30d_pct if trend_row else None,
            anomaly_flag=trend_row.anomaly_flag if trend_row else False,
            # Deprecated lane-level AI advice is never authoritative grounded output.
            outlook_text=None,
            recommendation=None,
            confidence=None,
            status="none",  # Legacy lifecycle is not a T07 result.
            error_message=None,
        ),
    )


@router.post("/rates/trends/{trend_id}/outlook", response_model=GroundedOutlookCreateResponse, status_code=202)
async def generate_rate_outlook_endpoint(
    trend_id: UUID,
    source: str | None = None,
    container_type: str | None = None,
    retry: bool = False,
    db: AsyncSession = Depends(get_db),
):
    row = await RateOutlookService(db).create(trend_id, source, container_type, retry=retry)
    if row.status == "pending":
        try:
            generate_rate_outlook.delay(str(row.id))
        except Exception:
            logger.exception("grounded_outlook_enqueue_failed", extra={"outlook_id": str(row.id)})
            await RateOutlookService(db).mark_enqueue_failed(row)
    return GroundedOutlookCreateResponse(trend_id=str(row.trend_id), outlook_id=row.id,
        forecast_id=row.forecast_id, status=row.status)


@router.get("/rates/outlooks/{outlook_id}", response_model=GroundedOutlookResponse)
async def get_grounded_outlook(outlook_id: UUID, db: AsyncSession = Depends(get_db)):
    return await RateOutlookService(db).read(outlook_id)
