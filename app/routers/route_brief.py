import os
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.auth.security import get_current_user
from app.models.user import User
from app.models.route_brief import RouteBrief
from app.schemas.route_brief import (
    RouteBriefCreateRequest,
    RouteBriefResponse,
    RouteBriefStatusResponse,
)
from app.tasks.route_brief_generation import generate_route_brief

router = APIRouter(prefix="/route-briefs", tags=["Route Briefs"])


@router.post("", response_model=RouteBriefResponse, status_code=status.HTTP_201_CREATED)
async def create_route_brief(
    request: RouteBriefCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    brief = RouteBrief(
        user_id=current_user.id,
        origin=request.origin,
        destination=request.destination,
        carrier=request.carrier,
        cargo_type=request.cargo_type or "40ft",
        status="pending",
    )
    db.add(brief)
    await db.commit()
    await db.refresh(brief)

    # Trigger async Celery task
    try:
        generate_route_brief.delay(str(brief.id))
    except Exception:
        pass

    return brief


@router.get("/{brief_id}/status", response_model=RouteBriefStatusResponse)
async def get_route_brief_status(
    brief_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    brief = await db.get(RouteBrief, brief_id)
    if not brief or (brief.user_id != current_user.id and not current_user.is_admin):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Route brief not found",
        )

    return RouteBriefStatusResponse(
        id=brief.id,
        status=brief.status,
        error_message=brief.error_message,
    )


@router.get("/{brief_id}/pdf")
async def get_route_brief_pdf(
    brief_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    brief = await db.get(RouteBrief, brief_id)
    if not brief or (brief.user_id != current_user.id and not current_user.is_admin):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Route brief not found",
        )

    if brief.status in ("pending", "generating"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Route brief PDF generation is still in progress",
        )

    if not brief.pdf_path or not os.path.exists(brief.pdf_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Route brief PDF file not found",
        )

    return FileResponse(
        path=brief.pdf_path,
        media_type="application/pdf",
        filename=f"route_brief_{brief.id}.pdf",
    )
