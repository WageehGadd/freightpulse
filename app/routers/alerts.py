from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.rate_alert import RateAlertRule, RateAlert
from app.schemas.alert import RateAlertRuleCreate, RateAlertRuleResponse, RateAlertEventResponse
from app.models.user import User
from app.auth.security import get_current_user
from app.auth.rate_limit import RateLimiter

router = APIRouter(prefix="/alerts", tags=["Alerts"], dependencies=[Depends(RateLimiter())])

@router.post("/rules", response_model=RateAlertRuleResponse, status_code=status.HTTP_201_CREATED)
async def create_rule(
    payload: RateAlertRuleCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rule = RateAlertRule(
        user_id=current_user.id,
        trade_lane=payload.trade_lane,
        alert_type=payload.alert_type,
        magnitude_pct=payload.magnitude_pct,
        target_usd=payload.target_usd,
        is_active=True,
    )
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    return rule

@router.get("/rules", response_model=list[RateAlertRuleResponse])
async def list_rules(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(RateAlertRule).where(RateAlertRule.user_id == current_user.id, RateAlertRule.is_active == True)
    result = await db.execute(stmt)
    return list(result.scalars().all())

@router.delete("/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rule(
    rule_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(RateAlertRule).where(RateAlertRule.id == rule_id, RateAlertRule.user_id == current_user.id)
    rule = await db.scalar(stmt)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")

    # Deactivate instead of hard delete
    rule.is_active = False
    await db.commit()

@router.get("/events", response_model=list[RateAlertEventResponse])
async def list_events(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(RateAlert).where(RateAlert.user_id == current_user.id).order_by(RateAlert.created_at.desc())
    result = await db.execute(stmt)
    return list(result.scalars().all())

@router.post("/events/{event_id}/read", response_model=RateAlertEventResponse)
async def mark_event_read(
    event_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(RateAlert).where(RateAlert.id == event_id, RateAlert.user_id == current_user.id)
    event = await db.scalar(stmt)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    event.is_read = True
    await db.commit()
    await db.refresh(event)
    return event
