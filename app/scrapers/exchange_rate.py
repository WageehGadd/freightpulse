import httpx
from app.scrapers.base import BaseScraper
from app.redis_client import get_redis
from app.config import settings
import structlog

logger = structlog.get_logger()

CACHE_KEY = "fx:usd_egp"
CACHE_TTL_SECONDS = 86400  # 24 hours


class ExchangeRateScraper(BaseScraper):
    name = "exchange_rate"

    async def scrape(self) -> dict:
        url = f"https://v6.exchangerate-api.com/v6/{settings.EXCHANGE_RATE_API_KEY}/latest/USD"

        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()

        if data.get("result") != "success":
            logger.warning("exchange_rate_api_error", response_data=data)
            return {"rows_upserted": 0}

        rate = data.get("conversion_rates", {}).get("EGP")

        if rate is None:
            logger.warning("exchange_rate_missing_egp", response_data=data)
            return {"rows_upserted": 0}

        redis = get_redis()
        await redis.set(CACHE_KEY, str(rate), ex=CACHE_TTL_SECONDS)

        logger.info("exchange_rate_updated", usd_egp=rate)
        return {"rows_upserted": 1, "usd_egp": rate}