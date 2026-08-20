import logging
from typing import Optional

from app.ai.openai_client import FreightPulseAIClient
from app.ai.prompts import get_prompt
from app.ai.translator import CarrierTranslator, TranslationError
from app.schemas.ai_outputs import CarrierSummaryOutput

logger = logging.getLogger(__name__)


class CarrierSummarizer:
    def __init__(
        self,
        ai_client: Optional[FreightPulseAIClient] = None,
        translator: Optional[CarrierTranslator] = None,
        prompt_version: str = "v1",
    ):
        self.ai_client = ai_client or FreightPulseAIClient()
        self.translator = translator or CarrierTranslator()
        self.prompt_version = prompt_version

    async def summarize(
        self, carrier: str, title: str, advisory_text: str
    ) -> CarrierSummaryOutput:
        if not advisory_text or not advisory_text.strip():
            raise ValueError("Advisory text cannot be empty")

        # Language detection & translation
        text_to_summarize = advisory_text
        detected_lang = self.translator.detect_language(advisory_text)
        if detected_lang == "ar":
            try:
                text_to_summarize = self.translator.translate(advisory_text)
            except TranslationError as exc:
                logger.warning(
                    f"Translation error for advisory from {carrier}, falling back to original: {exc}"
                )
                text_to_summarize = advisory_text

        # Resolve prompt
        prompt_tmpl = get_prompt("carrier_summarizer", self.prompt_version)
        system_prompt = prompt_tmpl.system_prompt
        user_content = prompt_tmpl.user_template.format(
            carrier=carrier,
            title=title,
            advisory_text=text_to_summarize,
        )

        # Call AI Client
        result = await self.ai_client.generate_structured(
            system_prompt=system_prompt,
            user_content=user_content,
            output_schema=CarrierSummaryOutput,
            feature_name="carrier_advisory_summary",
            prompt_version=self.prompt_version,
        )

        # Safe logging without leaking sensitive raw advisory text
        logger.info(
            f"Advisory summary generated successfully for carrier={carrier}, severity={result.impact_severity}"
        )
        return result
