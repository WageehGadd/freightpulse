import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import RouteBrief
from app.schemas.route_brief import RouteBriefCreateRequest, RouteBriefCreateResponse, RouteBriefResponse
from app.models.user import User
from app.auth.security import get_current_user
from app.auth.rate_limit import RateLimiter
from app.tasks.route_brief_generation import generate_route_brief

logger = logging.getLogger(__name__)
router = APIRouter(dependencies=[Depends(RateLimiter())])


def _to_response(brief: RouteBrief) -> RouteBriefResponse:
    return RouteBriefResponse(
        id=str(brief.id),
        origin=brief.origin,
        destination=brief.destination,
        cargo_type=brief.cargo_type,
        status=brief.status,
        brief_markdown=brief.brief_markdown,
        recommendation=brief.recommendation,
        risk_level=brief.risk_level,
        error_message=brief.error_message,
        created_at=brief.created_at,
    )


@router.post("/route-briefs", response_model=RouteBriefCreateResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_route_brief(
    payload: RouteBriefCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    brief = RouteBrief(
        user_id=current_user.id,
        origin=payload.origin,
        destination=payload.destination,
        cargo_type=payload.cargo_type,
        status="pending",
    )
    db.add(brief)
    await db.flush()
    await db.commit()

    try:
        generate_route_brief.delay(str(brief.id))
    except Exception:  # noqa: BLE001
        logger.exception("route_brief_enqueue_failed", extra={"brief_id": str(brief.id)})
        brief.status = "failed"
        brief.error_message = "Route brief could not be queued. Please try again later."
        await db.commit()

    return RouteBriefCreateResponse(id=str(brief.id), status=brief.status)


from fastapi.responses import FileResponse
import os

@router.get("/route-briefs/{brief_id}", response_model=RouteBriefResponse)
async def get_route_brief(
    brief_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    brief = await db.scalar(
        select(RouteBrief).where(
            RouteBrief.id == brief_id,
            RouteBrief.user_id == current_user.id,
        )
    )
    if brief is None:
        raise HTTPException(status_code=404, detail="Route brief not found")
    return _to_response(brief)


@router.get("/route-briefs/{brief_id}/status", response_model=RouteBriefCreateResponse)
async def get_route_brief_status(
    brief_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    brief = await db.scalar(
        select(RouteBrief).where(
            RouteBrief.id == brief_id,
            RouteBrief.user_id == current_user.id,
        )
    )
    if brief is None:
        raise HTTPException(status_code=404, detail="Route brief not found")
    return RouteBriefCreateResponse(id=str(brief.id), status=brief.status)


@router.get("/route-briefs/{brief_id}/pdf")
async def get_route_brief_pdf(
    brief_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    brief = await db.scalar(
        select(RouteBrief).where(
            RouteBrief.id == brief_id,
            RouteBrief.user_id == current_user.id,
        )
    )
    if brief is None:
        raise HTTPException(status_code=404, detail="Route brief not found")

    if brief.status in ["pending", "generating"]:
        raise HTTPException(status_code=409, detail="Route brief is still generating")

    if brief.status == "failed" or not brief.pdf_path:
        raise HTTPException(status_code=404, detail="Route brief PDF generation failed or is unavailable")

    if not os.path.exists(brief.pdf_path):
        raise HTTPException(status_code=404, detail="Route brief PDF file not found")

    return FileResponse(
        path=brief.pdf_path,
        media_type="application/pdf",
        filename=f"RouteBrief_{brief_id}.pdf",
    )
