"""T18 evidence adapter. It deliberately does not claim physical routing capability."""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.rate_limit import RateLimiter
from app.auth.security import get_current_user
from app.database import get_db
from app.models.carrier_advisory import CarrierAdvisory
from app.models.user import User
from app.routers.decisions import NONBLANK_SELECTOR_PATTERN
from app.schemas.route_intelligence import (AdvisorySnapshot, MarketSeries, ProvenanceClass,
                                             RouteEvidenceRequest, RouteEvidenceResult)
from app.services.decision_api import DecisionAPIService
from app.services.route_intelligence import compose_route_evidence, RouteEvidenceInputError

router = APIRouter(prefix="/route-evidence", tags=["Route evidence"], dependencies=[Depends(RateLimiter())])


@router.get("", response_model=RouteEvidenceResult)
async def get_route_evidence(
    response: Response,
    source: str = Query(..., min_length=1, pattern=NONBLANK_SELECTOR_PATTERN),
    trade_lane: str = Query(..., min_length=1, pattern=NONBLANK_SELECTOR_PATTERN),
    container_type: str = Query(..., min_length=1, pattern=NONBLANK_SELECTOR_PATTERN),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    series = MarketSeries(source=source, trade_lane=trade_lane, container_type=container_type)
    now = datetime.now(timezone.utc)
    try:
        context = await DecisionAPIService(db).context(source, trade_lane, container_type)
        # Existing advisory rows do not contain an asserted verification or exact
        # source/container lineage. Preserve them as persisted context, never facts.
        rows = (await db.execute(select(CarrierAdvisory).where(
            CarrierAdvisory.affected_lanes.any(trade_lane)
        ).order_by(CarrierAdvisory.published_at.desc()))).scalars().all()
        advisories = tuple(AdvisorySnapshot(
            record_id=str(row.id), carrier=row.carrier, classification=ProvenanceClass.PERSISTED_APPLICATION_DATA,
            source_url=row.source_url, source_text=row.raw_text, derived_summary=row.summary,
            published_at=row.published_at, observed_at=row.created_at,
        ) for row in rows)
        result = compose_route_evidence(RouteEvidenceRequest(
            series=series, evaluated_at=now, decision_input=context.input if context else None,
            advisories=advisories,
        ))
    except (RouteEvidenceInputError, ValueError, ArithmeticError):
        raise HTTPException(500, "Route evidence composition failed. Check server logs.") from None
    response.headers["Cache-Control"] = "no-store"
    return result
