import asyncio
from datetime import date
import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from app.celery_app import celery_app
from app.database import AsyncSessionLocal
from app.models.freight_rate import FreightRate
from app.scrapers.scfi import SCFIScraper

logger = structlog.get_logger()


async def _run_rate_ingestion() -> dict:
    scraper = SCFIScraper()
    data = await scraper.run()
    records = data.get("records", [])

    upserted = 0
    invalid = 0

    async with AsyncSessionLocal() as session:
        for rec in records:
            # Validate numeric rate
            try:
                rate_val = float(rec["rate_usd"])
            except (ValueError, TypeError):
                invalid += 1
                continue

            trade_lane = rec.get("trade_lane")
            rate_date = rec.get("rate_date")
            container_type = rec.get("container_type", "40ft")

            if not trade_lane or not rate_date:
                invalid += 1
                continue

            stmt = select(FreightRate).where(
                FreightRate.trade_lane == trade_lane,
                FreightRate.rate_date == rate_date,
                FreightRate.container_type == container_type,
            )
            existing = (await session.execute(stmt)).scalar_one_or_none()

            if existing:
                existing.rate_usd = rate_val
                existing.source = rec.get("source", "SCFI")
                existing.origin_port = rec.get("origin_port")
                existing.dest_region = rec.get("dest_region")
                existing.week_number = rec.get("week_number")
                existing.source_url = rec.get("source_url")
            else:
                new_rate = FreightRate(
                    source=rec.get("source", "SCFI"),
                    trade_lane=trade_lane,
                    origin_port=rec.get("origin_port"),
                    dest_region=rec.get("dest_region"),
                    container_type=container_type,
                    rate_usd=rate_val,
                    rate_date=rate_date,
                    week_number=rec.get("week_number"),
                    source_url=rec.get("source_url"),
                )
                session.add(new_rate)
            upserted += 1

        await session.commit()

    logger.info("rate_ingestion_completed", upserted=upserted, invalid=invalid)
    return {"upserted": upserted, "invalid": invalid}


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def ingest_freight_rates(self):
    try:
        return asyncio.run(_run_rate_ingestion())
    except Exception as exc:
        raise self.retry(exc=exc) from exc
