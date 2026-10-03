"""T07 worker consumes stable outlook IDs, never legacy trend-only payloads."""
import asyncio
import logging
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any

import openai
from sqlalchemy import update
from sqlalchemy.exc import SQLAlchemyError

from app.celery_app import celery_app
from app.database import AsyncSessionLocal
from app.models import RateOutlook, RateTrend, RateForecast
from app.ai.rate_outlook_narrator import RateOutlookNarrator
from app.ai.openai_client import FreightPulseAIClient, AITimeoutError, AIValidationError
from app.ai.budget_guard import AIBudgetExceededError, AIRateLimitExceededError
from app.schemas.ai_outputs import GroundedRateOutlookOutput
from app.services.rate_outlook import RateOutlookService, MAX_ATTEMPTS, RETRY_COOLDOWN_SECONDS

logger = logging.getLogger(__name__)


def _build_narrator():
    return RateOutlookNarrator(ai_client=FreightPulseAIClient())


def _fail(row, code, message, retryable=False):
    row.status = "failed"
    row.failure_code = code
    row.error_message = message
    row.retry_after = (
        datetime.now(timezone.utc) + timedelta(seconds=RETRY_COOLDOWN_SECONDS)
        if retryable else None
    )


async def generate_rate_outlook_async(
    outlook_id: str, *, session_factory: Callable[[], Any] = AsyncSessionLocal,
    narrator_factory: Callable = _build_narrator,
) -> dict[str, str]:
    parsed_id = uuid.UUID(outlook_id)
    async with session_factory() as session:
        # Atomic claim prevents concurrent workers spending twice for one attempt.
        row = (await session.execute(update(RateOutlook).where(
            RateOutlook.id == parsed_id, RateOutlook.status == "pending",
            RateOutlook.attempt_count < MAX_ATTEMPTS,
        ).values(status="generating", attempt_count=RateOutlook.attempt_count + 1)
          .returning(RateOutlook))).scalar_one_or_none()
        await session.commit()
        if row is None:
            existing = await session.get(RateOutlook, parsed_id)
            if existing is None:
                # Includes old queued trend UUIDs: no fallback lookup or legacy write.
                raise ValueError("Rate outlook not found; legacy trend jobs are unsupported")
            return {"outlook_id": str(parsed_id), "status": existing.status}
        try:
            if row.prompt_version != "v2":
                raise AIValidationError("Grounded narration requires rate_outlook/v2")
            forecast = await session.get(RateForecast, row.forecast_id)
            trend = await session.get(RateTrend, row.trend_id)
            service = RateOutlookService(session)
            state, warning = await service.context_state(trend, forecast, row.forecast_generated_at)
            if state != "current":
                row.status = "unavailable"
                row.error_message = warning
            else:
                result = await service.read(row.id)
                evidence = result.quantitative.model_dump(mode="json")
                evidence["exact_values"] = result.exact_values.model_dump(mode="json")
                # Preserve exactly what this attempt supplied, including evaluated freshness.
                # JSON serialization gives Azure a copy; read-time changes cannot rewrite this.
                row.narration_input = evidence
                await session.commit()
                output = await narrator_factory().narrate_grounded(evidence, row.prompt_version)
                output = GroundedRateOutlookOutput.model_validate(output)
                await session.refresh(forecast)
                await session.refresh(trend)
                state, warning = await service.context_state(trend, forecast, row.forecast_generated_at)
                if state != "current":
                    row.status = "unavailable"
                    row.error_message = warning
                else:
                    row.outlook_text = output.outlook_text
                    row.status = "completed"
                    row.error_message = None
        except (AIBudgetExceededError, AIRateLimitExceededError):
            _fail(row, "budget_or_limit", "Narration unavailable: AI budget or request limit reached.")
        except (AIValidationError, ValueError):
            _fail(row, "validation", "Narration unavailable: structured output validation failed.")
        except (AITimeoutError, openai.APITimeoutError):
            _fail(row, "timeout", "Narration unavailable: AI request timed out.", retryable=True)
        except (openai.APIConnectionError, openai.InternalServerError, openai.RateLimitError):
            _fail(row, "service_unavailable", "Narration unavailable: AI service temporarily unavailable.", retryable=True)
        except SQLAlchemyError:
            # A failed database transaction cannot safely persist a successful degradation.
            await session.rollback()
            raise
        except Exception:
            logger.exception("grounded_rate_outlook_failed", extra={"outlook_id": str(parsed_id)})
            _fail(row, "internal", "Narration unavailable: AI service failed.")
        row.completed_at = datetime.now(timezone.utc)
        await session.commit()
        return {"outlook_id": str(parsed_id), "status": row.status}


@celery_app.task(bind=True, name="app.tasks.rate_outlook_generation.generate_grounded_rate_outlook")
def generate_rate_outlook(self, outlook_id: str) -> dict[str, str]:
    # Client owns bounded retries. Only a later explicit POST can retry transient failures.
    return asyncio.run(generate_rate_outlook_async(outlook_id))
