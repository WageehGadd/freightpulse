from fastapi import APIRouter
from app.redis_client import get_redis

router = APIRouter()


@router.get("/bunker/ifo380")
async def get_bunker_prices():
    redis = get_redis()
    keys = await redis.keys("bunker:ifo380:*")

    prices = {}
    for key in keys:
        value = await redis.get(key)
        port_label = key.split(":")[-1]
        prices[port_label] = float(value) if value else None

    return {"ifo380_prices": prices}