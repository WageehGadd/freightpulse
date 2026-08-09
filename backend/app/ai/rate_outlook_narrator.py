import logging
import time

from backend.app.ai.openai_client import (
    AITimeoutError,
    AIValidationError,
    FreightPulseAIClient,
)
from backend.app.ai.prompts.rate_outlook_v1 import SYSTEM_PROMPT, USER_TEMPLATE
from backend.app.schemas.ai_outputs import RateOutlookOutput

logger = logging.getLogger(__name__)


class RateOutlookNarrator:
    def __init__(self, ai_client: FreightPulseAIClient):
        self.ai_client = ai_client

    async def narrate(
        self,
        lane: str,
        current_rate: str,
        historical_context: str,
        market_factors: str,
    ) -> RateOutlookOutput:
        if not lane or not lane.strip():
            raise ValueError("Lane cannot be empty")
            
        start_time = time.time()

        user_content = USER_TEMPLATE.format(
            lane=lane,
            current_rate=current_rate,
            historical_context=historical_context,
            market_factors=market_factors,
        )

        try:
            result = await self.ai_client.generate_structured(
                system_prompt=SYSTEM_PROMPT,
                user_content=user_content,
                output_schema=RateOutlookOutput,
                feature_name="rate_outlook_narrator",
            )
            
            latency = time.time() - start_time
            logger.info(
                "Rate outlook success: lane=%s, recommendation=%s, confidence=%d, latency=%.2fs",
                lane,
                result.recommendation,
                result.confidence,
                latency,
            )
            return result

        except (AIValidationError, AITimeoutError):
            latency = time.time() - start_time
            logger.exception(
                "Rate outlook failure (AI Error): lane=%s, latency=%.2fs",
                lane,
                latency,
            )
            raise
        except Exception:
            latency = time.time() - start_time
            logger.exception(
                "Rate outlook failure (Unexpected Error): lane=%s, latency=%.2fs",
                lane,
                latency,
            )
            raise
