import feedparser
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from playwright.async_api import async_playwright
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.database import AsyncSessionLocal
from app.models import CarrierAdvisory
from app.scrapers.base import BaseScraper
from app.tasks.ai_generation import summarize_advisory

import structlog


logger = structlog.get_logger()


CARRIER_FEEDS = {
    "CMA CGM": "https://www.cma-cgm.com/news/feed",
}


CATEGORY_MAP = {
    "Prices & Surcharges": "surcharge",
    "Shipping": "schedule_change",
    "Corporate Information": None,
}


def guess_advisory_type(category: str, title: str) -> str | None:
    mapped = CATEGORY_MAP.get(category)

    if mapped is None:
        return None

    title_lower = title.lower()

    if "suspension" in title_lower or "suspend" in title_lower:
        return "route_suspension"

    if mapped == "schedule_change" and (
        "rotation" in title_lower or "update" in title_lower
    ):
        return "schedule_change"

    return mapped


async def fetch_feed_via_browser(url: str) -> bytes:
    """
    Use a real browser (Playwright) to bypass WAF protection
    that may reject requests from httpx.
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        try:
            response = await page.goto(
                url,
                wait_until="networkidle",
                timeout=30000,
            )

            content = await response.body()
            return content

        finally:
            await browser.close()


class CarrierAdvisoryScraper(BaseScraper):
    name = "carrier_advisories"

    async def scrape(self) -> dict:
        rows_upserted = 0
        new_ids = []

        async with AsyncSessionLocal() as session:
            for carrier_name, feed_url in CARRIER_FEEDS.items():
                try:
                    raw_content = await fetch_feed_via_browser(feed_url)

                except Exception as e:
                    logger.warning(
                        "carrier_feed_fetch_failed",
                        carrier=carrier_name,
                        error=str(e),
                    )
                    continue

                feed = feedparser.parse(raw_content)

                if not feed.entries:
                    logger.warning(
                        "carrier_feed_no_entries",
                        carrier=carrier_name,
                        bozo=feed.bozo,
                        error=str(
                            getattr(feed, "bozo_exception", "")
                        ),
                    )
                    continue

                for entry in feed.entries:
                    category = getattr(entry, "category", "")
                    advisory_type = guess_advisory_type(
                        category,
                        entry.title,
                    )

                    if advisory_type is None:
                        continue

                    try:
                        published_at = parsedate_to_datetime(
                            entry.published
                        )

                        if published_at.tzinfo is None:
                            published_at = published_at.replace(
                                tzinfo=timezone.utc
                            )

                    except Exception:
                        published_at = datetime.now(timezone.utc)

                    existing = await session.execute(
                        select(CarrierAdvisory).where(
                            CarrierAdvisory.source_url == entry.link
                        )
                    )

                    if existing.scalar_one_or_none() is not None:
                        continue

                    stmt = (
                        insert(CarrierAdvisory)
                        .values(
                            carrier=carrier_name,
                            advisory_type=advisory_type,
                            title=entry.title,
                            raw_text=getattr(entry, "description", None),
                            summary=None,
                            impact_severity=None,
                            affected_lanes=None,
                            effective_date=None,
                            source_url=entry.link,
                            published_at=published_at,
                        )
                        .returning(CarrierAdvisory.id)
                    )

                    res = await session.execute(stmt)
                    new_id = res.scalar_one()
                    new_ids.append(new_id)
                    rows_upserted += 1

            await session.commit()

        # Dispatch AI summarization tasks after commit
        for adv_id in new_ids:
            try:
                summarize_advisory.delay(str(adv_id))
            except Exception as e:
                logger.warning("summarize_advisory_dispatch_failed", advisory_id=str(adv_id), error=str(e))

        logger.info(
            "carrier_advisories_updated",
            rows_upserted=rows_upserted,
        )

        return {"rows_upserted": rows_upserted}
