import logging
import time

from typing import Optional

from app.ai.openai_client import (
    AITimeoutError,
    AIValidationError,
    FreightPulseAIClient,
)
from app.ai.prompts import get_prompt
from app.schemas.ai_outputs import RouteBriefOutput

logger = logging.getLogger(__name__)


class RouteBriefGenerator:
    def __init__(
        self,
        ai_client: FreightPulseAIClient,
        prompt_version: Optional[str] = None,  # noqa: UP045
    ):
        self.ai_client = ai_client
        self.prompt_version = prompt_version

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

        prompt_template = get_prompt("route_brief", self.prompt_version)

        user_content = prompt_template.user_template.format(
            origin=origin,
            destination=destination,
            carrier=carrier,
            advisories=advisories,
            conditions=conditions,
        )

        try:
            result = await self.ai_client.generate_structured(
                system_prompt=prompt_template.system_prompt,
                user_content=user_content,
                output_schema=RouteBriefOutput,
                feature_name="route_brief",
                prompt_version=prompt_template.version,
            )

            latency = time.time() - start_time
            logger.info(
                "Route brief success: origin=%s, destination=%s, prompt_version=%s, recommendation=%s, risk_level=%s, latency=%.2fs",
                origin,
                destination,
                prompt_template.version,
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
