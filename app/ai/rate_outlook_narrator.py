import logging
from typing import Optional

from app.ai.openai_client import FreightPulseAIClient
from app.ai.prompts import get_prompt
from app.schemas.ai_outputs import RateOutlookOutput

logger = logging.getLogger(__name__)


class RateOutlookNarrator:
    def __init__(
        self,
        ai_client: Optional[FreightPulseAIClient] = None,
        prompt_version: str = "v1",
    ):
        self.ai_client = ai_client or FreightPulseAIClient()
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

        prompt_tmpl = get_prompt("rate_outlook", self.prompt_version)
        system_prompt = prompt_tmpl.system_prompt
        user_content = prompt_tmpl.user_template.format(
            lane=lane,
            current_rate=current_rate,
            historical_context=historical_context,
            market_factors=market_factors,
        )

        result = await self.ai_client.generate_structured(
            system_prompt=system_prompt,
            user_content=user_content,
            output_schema=RateOutlookOutput,
            feature_name="rate_outlook_narrator",
            prompt_version=self.prompt_version,
        )

        # Safe logging without leaking sensitive historical or market data
        logger.info(
            f"Rate outlook narrative generated for lane={lane}, recommendation={result.recommendation}, confidence={result.confidence}"
        )
        return result
