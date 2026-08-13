from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.models import CarrierAdvisory
from app.schemas.carrier import CarrierAdvisoriesListResponse, CarrierAdvisoryResponse

router = APIRouter()


@router.get("/carriers/advisories", response_model=CarrierAdvisoriesListResponse)
async def get_carrier_advisories(
    carrier: str | None = Query(default=None),
    type: str | None = Query(default=None),  
    affected_lane: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(CarrierAdvisory).order_by(CarrierAdvisory.published_at.desc())

    if carrier:
        stmt = stmt.where(CarrierAdvisory.carrier == carrier)
    if type:
        stmt = stmt.where(CarrierAdvisory.advisory_type == type)
    if affected_lane:
        stmt = stmt.where(CarrierAdvisory.affected_lanes.any(affected_lane))

    result = await db.execute(stmt)
    advisories = result.scalars().all()

    return CarrierAdvisoriesListResponse(
        advisories=[
            CarrierAdvisoryResponse(
                id=str(a.id),
                carrier=a.carrier,
                advisory_type=a.advisory_type,
                title=a.title,
                summary=a.summary,
                affected_lanes=a.affected_lanes,
                effective_date=a.effective_date,
                impact_severity=None,  # AI 
                source_url=a.source_url,
                published_at=a.published_at,
            )
            for a in advisories
        ]
    )