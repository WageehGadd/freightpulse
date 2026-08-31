import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.celery_app import celery_app
from app.database import AsyncSessionLocal
from app.models import RouteBrief
from app.services.route_brief_context import RouteBriefContext, build_route_brief_context
from app.ai.openai_client import FreightPulseAIClient
from app.ai.route_brief_generator import RouteBriefGenerator

logger = logging.getLogger(__name__)


class InvalidRouteBriefIdError(ValueError):
    pass


class RouteBriefNotFoundError(Exception):
    pass


class RouteBriefStateError(Exception):
    pass


def _parse_brief_id(brief_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(brief_id)
    except (AttributeError, TypeError, ValueError) as exc:
        raise InvalidRouteBriefIdError(f"Invalid route brief UUID: {brief_id!r}") from exc


def _build_generator() -> RouteBriefGenerator:
    return RouteBriefGenerator(ai_client=FreightPulseAIClient())


async def _mark_failed(session: AsyncSession, brief_id: uuid.UUID) -> None:
    failed_brief = await session.get(RouteBrief, brief_id)
    if failed_brief is None:
        return
    failed_brief.status = "failed"
    failed_brief.error_message = "Route brief generation failed. Please try again later."
    await session.commit()


async def generate_route_brief_async(
    brief_id: str,
    *,
    session_factory: Callable[[], Any] = AsyncSessionLocal,
    context_builder: Callable[..., Awaitable[RouteBriefContext]] = build_route_brief_context,
    generator_factory: Callable[[], RouteBriefGenerator] = _build_generator,
    allow_generating_retry: bool = False,
    mark_failed_on_error: bool = True,
) -> dict[str, str]:
    parsed_id = _parse_brief_id(brief_id)

    async with session_factory() as session:
        brief = await session.get(RouteBrief, parsed_id)
        if brief is None:
            raise RouteBriefNotFoundError(f"Route brief {parsed_id} not found.")
        if brief.status == "completed":
            return {"route_brief_id": str(parsed_id), "status": "completed"}
        if brief.status != "pending" and not (allow_generating_retry and brief.status == "generating"):
            raise RouteBriefStateError(f"Route brief {parsed_id} is not pending.")

        if brief.status == "pending":
            brief.status = "generating"
            brief.error_message = None
            await session.commit()

        try:
            context = await context_builder(
                session,
                origin=brief.origin,
                destination=brief.destination,
                carrier=brief.carrier,
                cargo_type=brief.cargo_type,
            )
            output = await generator_factory().generate_brief(
                origin=brief.origin,
                destination=brief.destination,
                carrier=brief.carrier,
                advisories=context.advisories,
                conditions=context.conditions,
            )
            brief.brief_markdown = output.brief_markdown
            brief.recommendation = output.recommendation
            brief.risk_level = output.risk_level

            # Generate PDF
            try:
                from app.services.pdf_generator import generate_route_brief_pdf
                from fpdf.errors import FPDFException
                pdf_path = generate_route_brief_pdf(str(parsed_id), output.brief_markdown)
                brief.pdf_path = pdf_path
            except FPDFException:
                logger.exception("route_brief_pdf_generation_failed", extra={"brief_id": str(parsed_id)})
                # Do not raise. The PDF generation is non-critical, and we should still save the AI result.
                brief.pdf_path = None

            brief.status = "completed"
            brief.error_message = None
            await session.commit()
            return {"route_brief_id": str(parsed_id), "status": "completed"}
        except Exception:
            await session.rollback()
            if mark_failed_on_error:
                try:
                    await _mark_failed(session, parsed_id)
                except Exception:
                    await session.rollback()
                    logger.exception("route_brief_failure_status_update_failed", extra={"brief_id": str(parsed_id)})
            raise


@celery_app.task(bind=True, max_retries=2, default_retry_delay=30)
def generate_route_brief(self, brief_id: str) -> dict[str, str]:
    try:
        return asyncio.run(
            generate_route_brief_async(
                brief_id,
                allow_generating_retry=self.request.retries > 0,
                mark_failed_on_error=self.request.retries >= self.max_retries,
            )
        )
    except (InvalidRouteBriefIdError, RouteBriefNotFoundError, RouteBriefStateError):
        raise
    except Exception as exc:
        raise self.retry(exc=exc) from exc
