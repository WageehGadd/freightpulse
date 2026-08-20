from uuid import UUID
from typing import List
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.auth.security import get_current_user
from app.models.user import User
from app.models.rate_alert import RateAlert, RateAlertRule
from app.schemas.alert import (
    AlertReadResponse,
    AlertResponse,
    AlertsListResponse,
    AlertRuleCreateRequest,
    AlertRuleResponse,
)

router = APIRouter(prefix="/alerts", tags=["Alerts"])


@router.post("/rules", response_model=AlertRuleResponse, status_code=status.HTTP_201_CREATED)
async def create_alert_rule(
    request: AlertRuleCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rule = RateAlertRule(
        user_id=current_user.id,
        trade_lane=request.trade_lane,
        alert_type=request.alert_type,
        magnitude_pct=request.magnitude_pct,
        target_usd=request.target_usd,
        is_active=True,
    )
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    return rule


@router.get("/rules", response_model=List[AlertRuleResponse])
async def list_alert_rules(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(RateAlertRule)
        .where(RateAlertRule.user_id == current_user.id, RateAlertRule.is_active == True)  # noqa: E712
        .order_by(RateAlertRule.created_at.desc())
    )
    rules = (await db.execute(stmt)).scalars().all()
    return rules


@router.delete("/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_alert_rule(
    rule_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(RateAlertRule).where(
        RateAlertRule.id == rule_id,
        RateAlertRule.user_id == current_user.id,
    )
    rule = (await db.execute(stmt)).scalar_one_or_none()
    if not rule:
        raise HTTPException(status_code=404, detail="Alert rule not found")

    await db.delete(rule)
    await db.commit()
    return None


@router.get("/events", response_model=List[AlertResponse])
async def list_alert_events(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(RateAlert)
        .where((RateAlert.user_id == current_user.id) | (RateAlert.user_id.is_(None)))
        .order_by(RateAlert.created_at.desc())
    )
    alerts = (await db.execute(stmt)).scalars().all()
    return alerts


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
