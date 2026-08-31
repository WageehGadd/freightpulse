import logging
import uuid
from typing import Any, Optional

from dataclasses import dataclass

try:
    from typing import Protocol
except ImportError:
    from typing_extensions import Protocol

from app.ai.carrier_summarizer import CarrierSummarizer
from app.ai.rate_outlook_narrator import RateOutlookNarrator
from app.schemas.ai_outputs import CarrierSummaryOutput, RateOutlookOutput

logger = logging.getLogger(__name__)


class AdvisoryNotFoundError(Exception):
    """Raised when the requested advisory does not exist."""


class AdvisoryEmptyError(Exception):
    """Raised when the raw advisory text is missing or whitespace."""


class AdvisoryRecord(Protocol):
    """Protocol defining the required fields for a Carrier Advisory DB record."""
    id: uuid.UUID
    carrier: str
    title: str
    raw_text: str

    summary: Optional[str]  # noqa: UP045
    affected_lanes: Optional[list[str]]  # noqa: UP045
    effective_date: Optional[Any]  # noqa: UP045
    impact_severity: Optional[str]  # noqa: UP045


class AdvisoryRepository(Protocol):
    """Protocol defining the required database operations for the adapter."""
    async def get_by_id(self, advisory_id: uuid.UUID) -> Optional[AdvisoryRecord]:  # noqa: UP045
        ...

    async def commit(self) -> None:
        ...

    async def rollback(self) -> None:
        ...


class CarrierSummarizerAdapter:
    def __init__(self, repository: AdvisoryRepository, summarizer: CarrierSummarizer):
        self.repository = repository
        self.summarizer = summarizer

    async def summarize_and_save(self, advisory_id: uuid.UUID) -> CarrierSummaryOutput:
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


class TrendNotFoundError(Exception):
    """Raised when the requested rate trend does not exist."""


class InsufficientDataError(Exception):
    """Raised when the rate trend lacks sufficient data to generate an outlook."""


class RateTrendRecord(Protocol):
    """Protocol defining the required fields for a Rate Trend DB record."""
    id: uuid.UUID
    trade_lane: str
    computed_date: Any
    avg_7d_usd: Optional[float]  # noqa: UP045
    avg_30d_usd: Optional[float]  # noqa: UP045
    change_7d_pct: Optional[float]  # noqa: UP045
    slope_per_week: Optional[float]  # noqa: UP045
    outlook_text: Optional[str]  # noqa: UP045
    recommendation: Optional[str]  # noqa: UP045
    confidence: Optional[int]  # noqa: UP045
    status: str
    error_message: Optional[str]  # noqa: UP045


@dataclass
class RateOutlookContext:
    trend: RateTrendRecord
    current_rate: str
    historical_context: str
    market_factors: str


class RateTrendRepository(Protocol):
    """Protocol defining the required database operations for the outlook adapter."""
    async def get_context(self, trend_id: uuid.UUID) -> Optional[RateOutlookContext]:  # noqa: UP045
        ...

    async def commit(self) -> None:
        ...

    async def rollback(self) -> None:
        ...


class RateOutlookNarratorAdapter:
    def __init__(self, repository: RateTrendRepository, narrator: RateOutlookNarrator):
        self.repository = repository
        self.narrator = narrator

    async def narrate_and_save(self, trend_id: uuid.UUID) -> RateOutlookOutput:
        context = await self.repository.get_context(trend_id)

        if not context:
            raise TrendNotFoundError(f"Trend {trend_id} not found in database.")

        if (
            not context.trend.avg_7d_usd
            or not context.trend.avg_30d_usd
            or context.trend.change_7d_pct is None
            or context.trend.slope_per_week is None
            or context.current_rate == "Unknown"
        ):
            raise InsufficientDataError(f"Trend {trend_id} lacks required historical data.")

        try:
            output = await self.narrator.narrate(
                lane=context.trend.trade_lane,
                current_rate=context.current_rate,
                historical_context=context.historical_context,
                market_factors=context.market_factors,
            )

            context.trend.outlook_text = output.outlook_text
            context.trend.recommendation = output.recommendation
            context.trend.confidence = output.confidence
            context.trend.status = "completed"
            context.trend.error_message = None

            await self.repository.commit()

            logger.info("Successfully updated trend_id=%s with outlook", trend_id)
            return output

        except Exception:
            await self.repository.rollback()
            logger.exception("Failed to generate outlook for trend_id=%s", trend_id)
            raise
