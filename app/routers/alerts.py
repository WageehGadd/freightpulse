from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.rate_alert import RateAlert
from app.schemas.alert import (
    AlertReadResponse,
    AlertResponse,
    AlertsListResponse,
)

router = APIRouter(prefix="/alerts", tags=["Alerts"])


@router.get("", response_model=AlertsListResponse)
async def get_alerts(
    unread: bool | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    """List alerts for the shared-key MVP in newest-first order."""
    stmt = select(RateAlert).order_by(RateAlert.created_at.desc())
    if unread is not None:
        stmt = stmt.where(RateAlert.is_read == (not unread))

    alerts = (await db.execute(stmt)).scalars().all()
    return AlertsListResponse(
        alerts=[
            AlertResponse(
                id=alert.id,
                trade_lane=alert.trade_lane,
                alert_type=alert.alert_type,
                message=alert.message,
                magnitude_pct=alert.magnitude_pct,
                is_read=alert.is_read,
                created_at=alert.created_at,
            )
            for alert in alerts
        ]
    )


@router.patch("/{alert_id}/read", response_model=AlertReadResponse)
async def mark_alert_read(alert_id: UUID, db: AsyncSession = Depends(get_db)):
    alert = await db.get(RateAlert, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail=f"Alert '{alert_id}' was not found")

    alert.is_read = True
    await db.commit()
    return AlertReadResponse(id=alert.id, is_read=alert.is_read)

