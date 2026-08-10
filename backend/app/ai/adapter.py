import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.ai.carrier_summarizer import CarrierSummarizer
from backend.app.db.models import CarrierAdvisory
from backend.app.schemas.ai_outputs import CarrierSummaryOutput

logger = logging.getLogger(__name__)


class AdvisoryNotFoundError(Exception):
    """Raised when the requested advisory does not exist."""


class AdvisoryEmptyError(Exception):
    """Raised when the raw advisory text is missing or whitespace."""


class CarrierSummarizerAdapter:
    def __init__(self, db_session: AsyncSession, summarizer: CarrierSummarizer):
        self.db_session = db_session
        self.summarizer = summarizer

    async def summarize_and_save(self, advisory_id: int) -> CarrierSummaryOutput:
        result = await self.db_session.execute(
            select(CarrierAdvisory).where(CarrierAdvisory.id == advisory_id)
        )
        advisory = result.scalar_one_or_none()

        if not advisory:
            raise AdvisoryNotFoundError(f"Advisory {advisory_id} not found in database.")

        raw_text = advisory.raw_text
        if not raw_text or not str(raw_text).strip():
            raise AdvisoryEmptyError(f"Advisory {advisory_id} has empty raw text.")

        try:
            summary_output = await self.summarizer.summarize(
                carrier=advisory.carrier,
                title=advisory.title,
                advisory_text=raw_text,
            )

            advisory.summary = summary_output.summary
            advisory.advisory_type = summary_output.advisory_type
            advisory.affected_lanes = summary_output.affected_lanes
            advisory.effective_date = summary_output.effective_date
            advisory.impact_severity = summary_output.impact_severity

            await self.db_session.commit()
            
            logger.info("Successfully updated advisory_id=%s with summary", advisory_id)
            return summary_output

        except Exception:
            await self.db_session.rollback()
            logger.exception("Failed to process advisory_id=%s", advisory_id)
            raise
