import logging
import time

from typing import Optional

from app.ai.openai_client import (
    AITimeoutError,
    AIValidationError,
    FreightPulseAIClient,
)
from app.ai.prompts import get_prompt
from app.schemas.ai_outputs import RateOutlookOutput

logger = logging.getLogger(__name__)


class RateOutlookNarrator:
    def __init__(
        self,
        ai_client: FreightPulseAIClient,
        prompt_version: Optional[str] = None,  # noqa: UP045
    ):
        self.ai_client = ai_client
        self.prompt_version = prompt_version

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

        prompt_template = get_prompt("rate_outlook", self.prompt_version)

        user_content = prompt_template.user_template.format(
            lane=lane,
            current_rate=current_rate,
            historical_context=historical_context,
            market_factors=market_factors,
        )

        try:
            result = await self.ai_client.generate_structured(
                system_prompt=prompt_template.system_prompt,
                user_content=user_content,
                output_schema=RateOutlookOutput,
                feature_name="rate_outlook_narrator",
                prompt_version=prompt_template.version,
            )

            latency = time.time() - start_time
            logger.info(
                "Rate outlook success: lane=%s, prompt_version=%s, recommendation=%s, confidence=%d, latency=%.2fs",
                lane,
                prompt_template.version,
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

    async def narrate_grounded(self, evidence: dict, prompt_version: str = "v2"):
        """Production T07 path; legacy narrate() is retained for compatibility only."""
        import json
        from app.schemas.ai_outputs import GroundedRateOutlookOutput
        if prompt_version != "v2":
            raise AIValidationError("Grounded narration requires rate_outlook/v2")
        prompt = get_prompt("rate_outlook", "v2")
        result = await self.ai_client.generate_structured(
            system_prompt=prompt.system_prompt,
            user_content=prompt.user_template.format(evidence=json.dumps(evidence, sort_keys=True)),
            output_schema=GroundedRateOutlookOutput,
            feature_name="rate_outlook_narrator", prompt_version=prompt.version,
            temperature=1.0,
        )
        return GroundedRateOutlookOutput.model_validate(result)
