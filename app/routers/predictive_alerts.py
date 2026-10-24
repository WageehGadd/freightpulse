from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.auth.rate_limit import RateLimiter
from app.auth.security import get_current_user
from app.database import get_db
from app.models.rate_alert import PredictiveAlertSubscription
from app.models.user import User

router = APIRouter(prefix="/alerts/predictive-subscriptions", tags=["Predictive alerts"], dependencies=[Depends(RateLimiter())])

class SubscriptionCreate(BaseModel):
    source: str
    trade_lane: str
    container_type: str
    @field_validator("source", "trade_lane", "container_type")
    @classmethod
    def exact(cls, value):
        if not value.strip() or not all(char.isprintable() for char in value):
            raise ValueError("must be nonblank printable exact identity")
        return value

class SubscriptionResponse(SubscriptionCreate):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    is_active: bool

@router.post("", response_model=SubscriptionResponse, status_code=status.HTTP_201_CREATED)
async def subscribe(payload: SubscriptionCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    row = PredictiveAlertSubscription(user_id=user.id, **payload.model_dump())
    db.add(row)
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise HTTPException(409, "Predictive subscription already exists for this exact series") from None
    await db.refresh(row)
    return row

@router.get("", response_model=list[SubscriptionResponse])
async def list_subscriptions(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return list((await db.execute(select(PredictiveAlertSubscription).where(
        PredictiveAlertSubscription.user_id == user.id, PredictiveAlertSubscription.is_active == True))).scalars())

@router.delete("/{subscription_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unsubscribe(subscription_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    row = await db.scalar(select(PredictiveAlertSubscription).where(PredictiveAlertSubscription.id == subscription_id, PredictiveAlertSubscription.user_id == user.id))
    if not row: raise HTTPException(404, "Predictive subscription not found")
    row.is_active = False
    await db.commit()
