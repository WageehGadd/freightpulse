import logging
import time

from backend.app.ai.openai_client import (
    AITimeoutError,
    AIValidationError,
    FreightPulseAIClient,
)
from backend.app.ai.prompts.route_brief_v1 import SYSTEM_PROMPT, USER_TEMPLATE
from backend.app.schemas.ai_outputs import RouteBriefOutput

logger = logging.getLogger(__name__)


class RouteBriefGenerator:
    def __init__(self, ai_client: FreightPulseAIClient):
        self.ai_client = ai_client

    async def generate_brief(
        self,
        origin: str,
        destination: str,
        carrier: str,
        advisories: str,
        conditions: str,
    ) -> RouteBriefOutput:
        if not origin or not origin.strip():
            raise ValueError("Origin cannot be empty")
        if not destination or not destination.strip():
            raise ValueError("Destination cannot be empty")
            
        start_time = time.time()

        user_content = USER_TEMPLATE.format(
            origin=origin,
            destination=destination,
            carrier=carrier,
            advisories=advisories,
            conditions=conditions,
        )

        try:
            result = await self.ai_client.generate_structured(
                system_prompt=SYSTEM_PROMPT,
                user_content=user_content,
                output_schema=RouteBriefOutput,
                feature_name="route_brief",
            )
            
            latency = time.time() - start_time
            logger.info(
                "Route brief success: origin=%s, destination=%s, recommendation=%s, risk_level=%s, latency=%.2fs",
                origin,
                destination,
                result.recommendation,
                result.risk_level,
                latency,
            )
            return result

        except (AIValidationError, AITimeoutError):
            latency = time.time() - start_time
            logger.exception(
                "Route brief failure (AI Error): origin=%s, destination=%s, latency=%.2fs",
                origin,
                destination,
                latency,
            )
            raise
        except Exception:
            latency = time.time() - start_time
            logger.exception(
                "Route brief failure (Unexpected Error): origin=%s, destination=%s, latency=%.2fs",
                origin,
                destination,
                latency,
            )
            raise
