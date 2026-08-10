from fastapi import APIRouter, HTTPException

from app.redis_client import get_redis

router = APIRouter()


@router.get("/exchange-rate/usd-egp")
async def get_usd_egp_rate():
    redis = get_redis()
    rate = await redis.get("fx:usd_egp")

    if rate is None:
        raise HTTPException(status_code=404, detail="Exchange rate not yet cached. Run the scraper first.")

    return {"usd_egp": float(rate)}