import asyncio
import structlog
from celery import shared_task
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError

from app.database import AsyncSessionLocal
from app.models import FreightRate
from app.scrapers.scfi import SCFIScraper

logger = structlog.get_logger()

class IngestionValidationError(ValueError):
    """Raised when a record fails critical structural validation."""
    pass

async def _run_rate_ingestion() -> dict:
    scraper = SCFIScraper()

    # Run the scraper. Its internal tenacity retry handles transient network issues.
    result = await scraper.run()
    records = result.get("records", [])

    if not records:
        logger.info("ingest_freight_rates_empty", source="scfi")
        return {"upserted": 0, "invalid": 0}

    valid_records = []
    invalid_count = 0

    # 1. Validate structure
    for rec in records:
        try:
            if not isinstance(rec.get("rate_usd"), (int, float)):
                raise IngestionValidationError("Missing or invalid 'rate_usd'")
            if not rec.get("trade_lane"):
                raise IngestionValidationError("Missing 'trade_lane'")
            if not rec.get("container_type"):
                raise IngestionValidationError("Missing 'container_type'")
            if not rec.get("rate_date"):
                raise IngestionValidationError("Missing 'rate_date'")

            valid_records.append(rec)
        except IngestionValidationError as e:
            invalid_count += 1
            logger.error(
                "ingest_freight_rates_invalid_record",
                error=str(e),
                record_preview=str(rec)[:200]
            )

    if not valid_records:
        logger.warning("ingest_freight_rates_all_invalid", source="scfi")
        return {"upserted": 0, "invalid": invalid_count}

    upserted_count = 0

    # 2. Persist with atomic batch semantics
    # Any DB error here correctly bubbles up, failing the task and triggering retry,
    # leaving the database cleanly unmutated (atomic).
    async with AsyncSessionLocal() as session:
        for record in valid_records:
            stmt = insert(FreightRate).values(
                source=record["source"],
                trade_lane=record["trade_lane"],
                origin_port=record["origin_port"],
                dest_region=record["dest_region"],
                container_type=record["container_type"],
                rate_usd=record["rate_usd"],
                rate_date=record["rate_date"],
                week_number=record.get("week_number"),
                source_url=record.get("source_url")
            )

            # Idempotency: updates mutable fields if exact record already exists
            stmt = stmt.on_conflict_do_update(
                index_elements=[
                    "source",
                    "trade_lane",
                    "container_type",
                    "rate_date",
                ],
                set_={
                    "rate_usd": record["rate_usd"],
                    "week_number": record.get("week_number"),
                    "source_url": record.get("source_url"),
                },
            )

            await session.execute(stmt)
            upserted_count += 1

        await session.commit()

    logger.info(
        "ingest_freight_rates_completed",
        source="scfi",
        upserted=upserted_count,
        invalid=invalid_count
    )
    return {"upserted": upserted_count, "invalid": invalid_count}

@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def ingest_freight_rates(self):
    """
    Scheduled Celery task to ingest freight rates from configured scrapers.
    Idempotent and safe to run repeatedly.
    """
    try:
        return asyncio.run(_run_rate_ingestion())
    except SQLAlchemyError as exc:
        logger.warning("ingest_freight_rates_db_error_retrying", error=str(exc))
        raise self.retry(exc=exc) from exc
    except Exception as exc:
        logger.exception("ingest_freight_rates_unexpected_error", error=str(exc))
        raise self.retry(exc=exc) from exc
