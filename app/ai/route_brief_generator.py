import logging
from typing import Optional

from app.ai.openai_client import FreightPulseAIClient
from app.ai.prompts import get_prompt
from app.schemas.ai_outputs import RouteBriefOutput

logger = logging.getLogger(__name__)


class RouteBriefGenerator:
    def __init__(
        self,
        ai_client: Optional[FreightPulseAIClient] = None,
        prompt_version: str = "v1",
    ):
        self.ai_client = ai_client or FreightPulseAIClient()
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

        prompt_tmpl = get_prompt("route_brief", self.prompt_version)
        system_prompt = prompt_tmpl.system_prompt
        user_content = prompt_tmpl.user_template.format(
            origin=origin,
            destination=destination,
            carrier=carrier,
            advisories=advisories,
            conditions=conditions,
        )

        result = await self.ai_client.generate_structured(
            system_prompt=system_prompt,
            user_content=user_content,
            output_schema=RouteBriefOutput,
            feature_name="route_brief",
            prompt_version=self.prompt_version,
        )

        # Safe logging without leaking sensitive raw inputs
        logger.info(
            f"Route brief generated successfully for origin={origin}, destination={destination}, recommendation={result.recommendation}, risk={result.risk_level}"
        )
        return result
