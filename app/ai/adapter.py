import logging
from typing import Any, Optional

from app.ai.carrier_summarizer import CarrierSummarizer
from app.schemas.ai_outputs import CarrierSummaryOutput

logger = logging.getLogger(__name__)


class AdvisoryNotFoundError(Exception):
    """Raised when an advisory is not found in the repository."""


class AdvisoryEmptyError(Exception):
    """Raised when an advisory has empty or whitespace-only raw text."""


class InsufficientDataError(Exception):
    """Raised when required historical data is insufficient for AI narration."""


class InvalidAdvisoryIdError(Exception):
    """Raised when advisory ID format is invalid."""


class AdvisoryRepository:
    async def get_by_id(self, id: Any) -> Any:
        raise NotImplementedError

    async def commit(self) -> None:
        raise NotImplementedError

    async def rollback(self) -> None:
        raise NotImplementedError


class CarrierSummarizerAdapter:
    def __init__(
        self,
        repository: AdvisoryRepository,
        summarizer: CarrierSummarizer,
    ):
        self.repository = repository
        self.summarizer = summarizer

    async def summarize_and_save(self, advisory_id: Any) -> CarrierSummaryOutput:
        advisory = await self.repository.get_by_id(advisory_id)
        if advisory is None:
            raise AdvisoryNotFoundError(f"Advisory '{advisory_id}' not found")

        raw_text = getattr(advisory, "raw_text", None)
        if not raw_text or not str(raw_text).strip():
            raise AdvisoryEmptyError(f"Advisory '{advisory_id}' has empty raw text")

        try:
            output = await self.summarizer.summarize(
                carrier=getattr(advisory, "carrier", "") or "",
                title=getattr(advisory, "title", "") or "",
                advisory_text=str(raw_text),
            )

            advisory.summary = output.summary
            advisory.affected_lanes = output.affected_lanes
            advisory.impact_severity = output.impact_severity
            if hasattr(advisory, "effective_date") and output.effective_date is not None:
                advisory.effective_date = output.effective_date

            await self.repository.commit()
            return output

        except Exception as exc:
            await self.repository.rollback()
            # Safe logging: log error and advisory ID without exposing raw sensitive text
            logger.exception(f"Advisory summarization failed for advisory_id={advisory_id}: {exc}")
            raise
