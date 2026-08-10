from abc import ABC, abstractmethod

import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

logger = structlog.get_logger()


class BaseScraper(ABC):
    """
    Common base class for all scrapers in FreightPulse.
    Provides automatic retry logic, structured logging,
    and basic rate validation.
    """

    name: str = "base"

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        reraise=True,
    )
    async def run(self) -> dict:
        """Unified entry point that calls scrape() with automatic retries."""
        logger.info("scraper_start", scraper=self.name)

        try:
            result = await self.scrape()

            logger.info(
                "scraper_success",
                scraper=self.name,
                rows_upserted=result.get("rows_upserted", 0),
            )

            return result

        except Exception as e:
            logger.error(
                "scraper_error",
                scraper=self.name,
                error=str(e),
            )
            raise

    @abstractmethod
    async def scrape(self) -> dict:
        """
        Every scraper subclass must implement this method.
        It must return {"rows_upserted": int, ...}.
        """
        ...

    async def validate_rate(self, rate: float, lane: str) -> bool:
        """
        Perform basic rate validation.
        Expected rates are between $100 and $20,000 per TEU.
        """
        if not (100 <= rate <= 20_000):
            logger.warning(
                "rate_out_of_range",
                rate=rate,
                lane=lane,
                scraper=self.name,
            )
            return False

        return True

