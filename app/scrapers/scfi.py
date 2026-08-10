import re
from datetime import date, datetime, timezone

import structlog
from playwright.async_api import async_playwright
from sqlalchemy.dialects.postgresql import insert

from app.database import AsyncSessionLocal
from app.models import FreightRate
from app.scrapers.base import BaseScraper

logger = structlog.get_logger()


SCFI_URL = "https://en.sse.net.cn/indices/scfinew.jsp"


# Normalize region names from the source table
# into the standardized trade_lane names used by the application.
REGION_NAME_MAP = {
    "Europe": "Europe",
    "Mediterranean": "Mediterranean",
    "USWC": "USWC",
    "USEC": "USEC",
    "South America": "SouthAmerica",
    "Central/South America West Coast": "CSAmericaWest",
    "West Africa": "WestAfrica",
    "South Africa": "SouthAfrica",
    "East Africa": "EastAfrica",
    "Persian Gulf and Red Sea": "PersianGulf",
    "India and Pakistan": "IndiaPakistan",
    "Australia/New Zealand": "Australia",
    "Southeast Asia": "SoutheastAsia",
    "West Japan": "WestJapan",
    "East Japan": "EastJapan",
    "Korea": "Korea",
}


def parse_row_label(description: str) -> tuple[str, str] | None:
    """
    Parse descriptions such as:
    'Europe 20ft (Base port)' or 'South America 40ft (Santos)'.

    Returns (region_name, container_type), or None if the row
    is not a valid data row, such as the Comprehensive Index row.
    """
    match = re.match(
        r"^(.+?)\s+(20ft|40ft)\b",
        description.strip(),
    )

    if not match:
        return None

    region_raw = match.group(1).strip()
    container_type = match.group(2)

    return region_raw, container_type


class SCFIScraper(BaseScraper):
    name = "scfi"

    async def scrape(self) -> dict:
        rows_data = []

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()

            try:
                await page.goto(
                    SCFI_URL,
                    wait_until="networkidle",
                    timeout=30000,
                )

                # The table is loaded dynamically with JavaScript,
                # so wait until the table content is available.
                await page.wait_for_selector(
                    "table >> text=Current Index",
                    timeout=15000,
                )

                # Get all table rows that may contain actual rate data.
                # Empty rows and header rows are filtered out below.
                rows = await page.query_selector_all("table tr")

                for row in rows:
                    cells = await row.query_selector_all("td")

                    if len(cells) < 6:
                        continue

                    texts = [await c.inner_text() for c in cells]

                    description = texts[0].strip()
                    unit = texts[1].strip()
                    current_index_text = texts[4].strip()

                    parsed = parse_row_label(description)

                    if not parsed:
                        # Skip rows such as the Comprehensive Index row.
                        continue

                    if not current_index_text or unit not in (
                        "USD/TEU",
                        "USD/FEU",
                    ):
                        # Skip empty rows or unsupported rate units.
                        continue

                    try:
                        rate_usd = float(
                            current_index_text.replace(",", "")
                        )
                    except ValueError:
                        continue

                    region_raw, container_type = parsed

                    region = REGION_NAME_MAP.get(
                        region_raw,
                        region_raw.replace(" ", "").replace("/", ""),
                    )

                    rows_data.append(
                        {
                            "trade_lane": f"Shanghai-{region}",
                            "dest_region": region,
                            "container_type": container_type,
                            "rate_usd": rate_usd,
                        }
                    )

            finally:
                await browser.close()

        if not rows_data:
            logger.warning("scfi_no_rows_parsed")
            return {"rows_upserted": 0}

        rate_date = datetime.now(timezone.utc).date()
        rows_upserted = 0

        async with AsyncSessionLocal() as session:
            for row in rows_data:
                if not await self.validate_rate(
                    row["rate_usd"],
                    row["trade_lane"],
                ):
                    continue

                stmt = insert(FreightRate).values(
                    source="SCFI",
                    trade_lane=row["trade_lane"],
                    origin_port="Shanghai",
                    dest_region=row["dest_region"],
                    container_type=row["container_type"],
                    rate_usd=row["rate_usd"],
                    rate_date=rate_date,
                    week_number=rate_date.isocalendar()[1],
                    source_url=SCFI_URL,
                )

                stmt = stmt.on_conflict_do_update(
                    index_elements=[
                        "source",
                        "trade_lane",
                        "container_type",
                        "rate_date",
                    ],
                    set_={"rate_usd": row["rate_usd"]},
                )

                await session.execute(stmt)
                rows_upserted += 1

            await session.commit()

        return {"rows_upserted": rows_upserted}

