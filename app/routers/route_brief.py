import os
from uuid import UUID
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query, status
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
    RouteBriefStatusUpdate,
)
from app.tasks.route_brief_generation import generate_route_brief, generate_route_brief_async

router = APIRouter(prefix="/route-briefs", tags=["Route Briefs"])


@router.post("", response_model=RouteBriefResponse, status_code=status.HTTP_201_CREATED)
async def create_route_brief(
    request: RouteBriefCreateRequest,
    background_tasks: BackgroundTasks,
    sync: bool = Query(False, description="If true, wait synchronously for brief and PDF generation"),
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

    if sync:
        try:
            await generate_route_brief_async(str(brief.id))
            await db.refresh(brief)
        except Exception:
            await db.refresh(brief)
        return brief

    # Trigger async Celery task, with automatic fallback to FastAPI BackgroundTasks
    dispatched = False
    try:
        generate_route_brief.delay(str(brief.id))
        dispatched = True
    except Exception:
        dispatched = False

    if not dispatched:
        background_tasks.add_task(generate_route_brief_async, str(brief.id))

    return brief


@router.post("/{brief_id}/generate", response_model=RouteBriefResponse)
async def trigger_route_brief_generation(
    brief_id: UUID,
    background_tasks: BackgroundTasks,
    sync: bool = Query(False, description="If true, wait synchronously for brief and PDF generation"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    brief = await db.get(RouteBrief, brief_id)
    if not brief or (brief.user_id != current_user.id and not current_user.is_admin):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Route brief not found",
        )

    brief.status = "generating"
    brief.error_message = None
    await db.commit()
    await db.refresh(brief)

    if sync:
        try:
            await generate_route_brief_async(str(brief.id))
            await db.refresh(brief)
        except Exception:
            await db.refresh(brief)
        return brief

    dispatched = False
    try:
        generate_route_brief.delay(str(brief.id))
        dispatched = True
    except Exception:
        dispatched = False

    if not dispatched:
        background_tasks.add_task(generate_route_brief_async, str(brief.id))

    return brief


@router.patch("/{brief_id}/status", response_model=RouteBriefStatusResponse)
async def update_route_brief_status(
    brief_id: UUID,
    update_data: RouteBriefStatusUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    brief = await db.get(RouteBrief, brief_id)
    if not brief or (brief.user_id != current_user.id and not current_user.is_admin):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Route brief not found",
        )

    brief.status = update_data.status
    if update_data.brief_markdown is not None:
        brief.brief_markdown = update_data.brief_markdown
    if update_data.recommendation is not None:
        brief.recommendation = update_data.recommendation
    if update_data.risk_level is not None:
        brief.risk_level = update_data.risk_level
    if update_data.error_message is not None:
        brief.error_message = update_data.error_message

    await db.commit()
    await db.refresh(brief)

    return RouteBriefStatusResponse(
        brief_id=brief.id,
        id=brief.id,
        status=brief.status,
        brief_markdown=brief.brief_markdown,
        recommendation=brief.recommendation,
        risk_level=brief.risk_level,
        error_message=brief.error_message,
        created_at=brief.created_at,
    )


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
        brief_id=brief.id,
        id=brief.id,
        status=brief.status,
        brief_markdown=brief.brief_markdown,
        recommendation=brief.recommendation,
        risk_level=brief.risk_level,
        error_message=brief.error_message,
        created_at=brief.created_at,
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
