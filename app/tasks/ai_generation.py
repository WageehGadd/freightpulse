import asyncio
import uuid
import structlog
from app.celery_app import celery_app
from app.database import AsyncSessionLocal
from app.models.carrier_advisory import CarrierAdvisory
from app.ai.carrier_summarizer import CarrierSummarizer
from app.ai.adapter import (
    AdvisoryEmptyError,
    AdvisoryNotFoundError,
    InvalidAdvisoryIdError,
)

logger = structlog.get_logger()


async def summarize_advisory_async(
    advisory_id_str: str,
    session_factory=None,
    summarizer_factory=None,
) -> dict:
    try:
        advisory_uuid = uuid.UUID(advisory_id_str)
    except (ValueError, TypeError, AttributeError) as exc:
        raise InvalidAdvisoryIdError(f"Invalid advisory UUID: {advisory_id_str}") from exc

    session_maker = session_factory or AsyncSessionLocal
    summarizer = summarizer_factory() if summarizer_factory else CarrierSummarizer()

    async with session_maker() as session:
        advisory = await session.get(CarrierAdvisory, advisory_uuid)
        if advisory is None:
            raise AdvisoryNotFoundError(f"Advisory '{advisory_id_str}' not found")

        raw_text = advisory.raw_text
        if not raw_text or not str(raw_text).strip():
            raise AdvisoryEmptyError(f"Advisory '{advisory_id_str}' has empty raw text")

        try:
            output = await summarizer.summarize(
                carrier=advisory.carrier or "",
                title=advisory.title or "",
                advisory_text=str(raw_text),
            )

            advisory.summary = output.summary
            advisory.impact_severity = output.impact_severity
            advisory.affected_lanes = output.affected_lanes
            if hasattr(advisory, "effective_date") and output.effective_date is not None:
                advisory.effective_date = output.effective_date

            await session.commit()
            return {
                "advisory_id": str(advisory_uuid),
                "summary_length": len(advisory.summary),
                "impact_severity": advisory.impact_severity,
            }

        except Exception as exc:
            await session.rollback()
            logger.exception("advisory_summarization_failed", advisory_id=str(advisory_uuid), error=str(exc))
            raise


@celery_app.task(bind=True, max_retries=3, default_retry_delay=30)
def summarize_advisory(self, advisory_id: str):
    try:
        uuid.UUID(advisory_id)
    except Exception as exc:
        raise InvalidAdvisoryIdError(f"Invalid advisory UUID: {advisory_id}") from exc

    try:
        return asyncio.run(summarize_advisory_async(advisory_id))
    except Exception as exc:
        raise self.retry(exc=exc) from exc