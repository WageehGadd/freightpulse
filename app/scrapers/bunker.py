import httpx
from bs4 import BeautifulSoup

from app.scrapers.base import BaseScraper
from app.redis_client import get_redis

import structlog


logger = structlog.get_logger()


BUNKER_URL = "https://shipandbunker.com/prices"

IFO380_TABLE_INDEX = 2  # Page tables order: VLSFO (0), MGO (1), IFO380 (2)

CACHE_KEY_PREFIX = "bunker:ifo380"
CACHE_TTL_SECONDS = 86400  # 24 hours


# Rows to store (actual ports + reference averages)
TRACKED_ROWS = [
    "Global Average Bunker Price",
    "Singapore",
    "Rotterdam",
    "Fujairah",
    "Houston",
    "Hong Kong",
    "New York",
    "Santos",
    "LA / Long Beach",
]


class BunkerScraper(BaseScraper):
    name = "bunker"

    async def scrape(self) -> dict:
        async with httpx.AsyncClient(
            timeout=20.0,
            follow_redirects=True,
        ) as client:
            response = await client.get(BUNKER_URL)
            response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        tables = soup.find_all("table")

        if len(tables) <= IFO380_TABLE_INDEX:
            logger.warning(
                "bunker_ifo380_table_not_found",
                tables_found=len(tables),
            )
            return {"rows_upserted": 0}

        ifo380_table = tables[IFO380_TABLE_INDEX]
        prices = {}

        for row in ifo380_table.find_all("tr"):
            cells = row.find_all(["th", "td"])

            if len(cells) < 2:
                continue

            label = cells[0].get_text(strip=True)
            price_text = cells[1].get_text(strip=True)

            try:
                price = float(price_text)
            except ValueError:
                # Ignore the header row or any non-numeric row automatically
                continue

            prices[label] = price

        if not prices:
            logger.warning("bunker_no_prices_parsed")
            return {"rows_upserted": 0}

        redis = get_redis()
        rows_upserted = 0

        for label in TRACKED_ROWS:
            if label in prices:
                cache_key = (
                    f"{CACHE_KEY_PREFIX}:"
                    f"{label.lower().replace(' ', '_').replace('/', '_')}"
                )

                await redis.set(
                    cache_key,
                    str(prices[label]),
                    ex=CACHE_TTL_SECONDS,
                )

                rows_upserted += 1
            else:
                logger.warning(
                    "bunker_expected_port_missing",
                    port=label,
                )

        logger.info(
            "bunker_prices_updated",
            rows_upserted=rows_upserted,
        )

        return {"rows_upserted": rows_upserted}

