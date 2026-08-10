import logging
from typing import Any, Optional

try:
    from typing import Protocol
except ImportError:
    from typing_extensions import Protocol

from backend.app.ai.carrier_summarizer import CarrierSummarizer
from backend.app.schemas.ai_outputs import CarrierSummaryOutput

logger = logging.getLogger(__name__)


class AdvisoryNotFoundError(Exception):
    """Raised when the requested advisory does not exist."""


class AdvisoryEmptyError(Exception):
    """Raised when the raw advisory text is missing or whitespace."""


class AdvisoryRecord(Protocol):
    """Protocol defining the required fields for a Carrier Advisory DB record."""
    id: int
    carrier: str
    title: str
    raw_text: str
    
    summary: Optional[str]  # noqa: UP045
    advisory_type: Optional[str]  # noqa: UP045
    affected_lanes: Optional[list[str]]  # noqa: UP045
    effective_date: Optional[Any]  # noqa: UP045
    impact_severity: Optional[str]  # noqa: UP045


class AdvisoryRepository(Protocol):
    """Protocol defining the required database operations for the adapter."""
    async def get_by_id(self, advisory_id: int) -> Optional[AdvisoryRecord]:  # noqa: UP045
        ...
        
    async def commit(self) -> None:
        ...
        
    async def rollback(self) -> None:
        ...


class CarrierSummarizerAdapter:
    def __init__(self, repository: AdvisoryRepository, summarizer: CarrierSummarizer):
        self.repository = repository
        self.summarizer = summarizer

    async def summarize_and_save(self, advisory_id: int) -> CarrierSummaryOutput:
        advisory = await self.repository.get_by_id(advisory_id)

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

            await self.repository.commit()
            
            logger.info("Successfully updated advisory_id=%s with summary", advisory_id)
            return summary_output

        except Exception:
            await self.repository.rollback()
            logger.exception("Failed to process advisory_id=%s", advisory_id)
            raise
