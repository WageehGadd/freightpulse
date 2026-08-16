import asyncio
import uuid
from collections.abc import Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.celery_app import celery_app
from app.database import AsyncSessionLocal
from app.models import CarrierAdvisory
from app.ai.adapter import (
    AdvisoryEmptyError,
    AdvisoryNotFoundError,
    CarrierSummarizerAdapter,
)
from app.ai.carrier_summarizer import CarrierSummarizer
from app.ai.openai_client import FreightPulseAIClient
from app.ai.translator import CarrierTranslator


class InvalidAdvisoryIdError(ValueError):
    """Raised when Celery receives a non-UUID carrier advisory identifier."""


class SQLAlchemyAdvisoryRepository:
    """Production persistence adapter owned by the backend layer."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, advisory_id: uuid.UUID) -> CarrierAdvisory | None:
        return await self.session.get(CarrierAdvisory, advisory_id)

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()


def _build_summarizer() -> CarrierSummarizer:
    return CarrierSummarizer(
        ai_client=FreightPulseAIClient(),
        translator=CarrierTranslator(),
    )


def _parse_advisory_id(advisory_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(advisory_id)
    except (AttributeError, TypeError, ValueError) as exc:
        raise InvalidAdvisoryIdError(f"Invalid advisory UUID: {advisory_id!r}") from exc


async def summarize_advisory_async(
    advisory_id: str,
    *,
    session_factory: Callable[[], Any] = AsyncSessionLocal,
    summarizer_factory: Callable[[], CarrierSummarizer] = _build_summarizer,
) -> dict[str, str | int]:
    """Load, summarize, and persist one advisory using production-owned storage."""
    parsed_id = _parse_advisory_id(advisory_id)

    async with session_factory() as session:
        adapter = CarrierSummarizerAdapter(
            repository=SQLAlchemyAdvisoryRepository(session),
            summarizer=summarizer_factory(),
        )
        result = await adapter.summarize_and_save(parsed_id)

    return {
        "advisory_id": str(parsed_id),
        "summary_length": len(result.summary),
        "impact_severity": result.impact_severity,
    }


@celery_app.task(bind=True, max_retries=2, default_retry_delay=30)
def summarize_advisory(self, advisory_id: str) -> dict[str, str | int]:
    """Synchronously bridge Celery's worker process to the async AI service."""
    try:
        return asyncio.run(summarize_advisory_async(advisory_id))
    except (InvalidAdvisoryIdError, AdvisoryNotFoundError, AdvisoryEmptyError):
        raise
    except Exception as exc:
        raise self.retry(exc=exc) from exc
