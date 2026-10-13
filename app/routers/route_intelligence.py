"""
Route Intelligence Router (T18).
Exposes authenticated route evidence composition combining exact-series factual decisions
with verified carrier advisories. Does NOT perform route optimization, ranking, or ETA predictions.
"""
from datetime import datetime, timezone
import logging
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.auth.security import get_current_user
from app.models.user import User
from app.models.carrier_advisory import CarrierAdvisory

try:
    from app.auth.rate_limit import RateLimiter
    rate_limiter_dep = [Depends(RateLimiter)]
except ImportError:
    rate_limiter_dep = []

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/routes", tags=["Route Intelligence"], dependencies=rate_limiter_dep)


@router.get("/evidence", status_code=status.HTTP_200_OK)
@router.post("/evidence", status_code=status.HTTP_200_OK)
async def get_route_evidence(
    response: Response,
    source: str = Query(..., description="Exact rate source, e.g. SCFI"),
    trade_lane: str = Query(..., description="Exact trade lane, e.g. Shanghai-Rotterdam"),
    container_type: str = Query(..., description="Exact container type, e.g. 40ft"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Compose authoritative route evidence for an exact market series and its verified advisories.
    Preserves factual T08/T09 authority and discloses operational gaps.
    Does not convert into route optimization, ranking, ETA, or savings predictions.
    """
    response.headers["Cache-Control"] = "no-store"

    try:
        from app.schemas.decision import SeriesIdentity, DecisionPolicy, DecisionInput
        from app.schemas.route_intelligence import (
            RouteEvidenceRequest,
            RouteEvidenceResult,
            AdvisorySnapshot,
            ProvenanceClass,
        )
        from app.services.forecast_persistence import ForecastPersistenceService
        from app.services.forecast_state import ForecastStateCollector, snapshot_forecast
        from app.services.route_intelligence import compose_route_evidence, RouteEvidenceInputError
    except ImportError as err:
        logger.error("route_intelligence_modules_unavailable", extra={"error": str(err)})
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Route intelligence service is not available on this deployment.",
        )

    evaluated_at = datetime.now(timezone.utc)
    series = SeriesIdentity(source=source, trade_lane=trade_lane, container_type=container_type)

    # 1. Fetch factual DecisionInput if available
    decision_input: Optional[DecisionInput] = None
    forecast_service = ForecastPersistenceService(db)
    rows = await forecast_service.get_latest_forecasts(
        source=source, trade_lane=trade_lane, container_type=container_type
    )

    if rows and len(rows) == 1:
        snapshot = snapshot_forecast(rows[0])
        if snapshot.series == series:
            state_collector = ForecastStateCollector(db)
            state = await state_collector.collect(snapshot, evaluated_at, expected_series=series)
            decision_input = DecisionInput(forecast=snapshot, current_state=state)

    # 2. Fetch carrier advisories relevant to trade lane
    advisories_stmt = select(CarrierAdvisory).where(
        CarrierAdvisory.trade_lane == trade_lane
    ).order_by(CarrierAdvisory.published_date.desc()).limit(20)
    advisories_res = await db.execute(advisories_stmt)
    advisory_rows = advisories_res.scalars().all()

    snapshots: List[AdvisorySnapshot] = []
    for adv in advisory_rows:
        has_url = bool(adv.source_url and adv.source_url.strip())
        has_text = bool(adv.raw_text and adv.raw_text.strip())

        # Assert qualified provenance only when verified text and URL exist
        if has_url and has_text:
            p_class = ProvenanceClass.VERIFIED_SOURCE_DATA
        else:
            p_class = ProvenanceClass.PERSISTED_APPLICATION

        pub_dt = (
            adv.published_date.replace(tzinfo=timezone.utc)
            if adv.published_date and adv.published_date.tzinfo is None
            else adv.published_date
        )

        snapshots.append(
            AdvisorySnapshot(
                record_id=str(adv.id),
                carrier=adv.carrier or "UNKNOWN",
                series=series,
                classification=p_class,
                source_text=adv.raw_text or adv.summary or "",
                source_url=adv.source_url or "https://freightpulse.internal/advisories",
                derived_interpretation=adv.impact_summary or adv.summary,
                published_at=pub_dt,
                observed_at=pub_dt,
            )
        )

    # 3. Compose route evidence
    req = RouteEvidenceRequest(
        series=series,
        evaluated_at=evaluated_at,
        decision_input=decision_input,
        advisories=tuple(snapshots),
    )

    try:
        result: RouteEvidenceResult = compose_route_evidence(req)
    except RouteEvidenceInputError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Route evidence composition rejected: {exc}",
        )
    except Exception as exc:
        logger.exception("route_evidence_composition_failed", extra={"error": str(exc)})
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal error during route evidence composition.",
        )

    return result.model_dump(mode="json")
