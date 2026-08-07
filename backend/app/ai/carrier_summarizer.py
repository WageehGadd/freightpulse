import asyncio
import logging
import time

from backend.app.ai.openai_client import (
    AITimeoutError,
    AIValidationError,
    FreightPulseAIClient,
)
from backend.app.ai.prompts.carrier_summary_v1 import SYSTEM_PROMPT, USER_TEMPLATE
from backend.app.ai.translator import CarrierTranslator
from backend.app.schemas.ai_outputs import CarrierSummaryOutput

logger = logging.getLogger(__name__)


class CarrierSummarizer:
    def __init__(self, ai_client: FreightPulseAIClient, translator: CarrierTranslator):
        self.ai_client = ai_client
        self.translator = translator

    async def summarize(
        self,
        carrier: str,
        title: str,
        advisory_text: str,
    ) -> CarrierSummaryOutput:
        if not advisory_text or not advisory_text.strip():
            raise ValueError("Advisory text cannot be empty")

        start_time = time.time()
        is_translated = False
        lang = "en"
        processed_text = advisory_text

        try:
            lang = self.translator.detect_language(advisory_text)
            if lang == "ar":
                # translate runs a PyTorch model and is blocking, so run in a thread
                processed_text = await asyncio.to_thread(self.translator.translate, advisory_text)
                is_translated = True
        except Exception as e:  # noqa: BLE001
            logger.warning("Translation failed, falling back to original text: %s", e)
            processed_text = advisory_text

        user_content = USER_TEMPLATE.format(
            carrier=carrier,
            title=title,
            advisory_text=processed_text
        )

        try:
            result = await self.ai_client.generate_structured(
                system_prompt=SYSTEM_PROMPT,
                user_content=user_content,
                output_schema=CarrierSummaryOutput,
                feature_name="carrier_advisory_summary"
            )
            
            latency = time.time() - start_time
            logger.info(
                "Summary success: carrier=%s, lang=%s, translated=%s, latency=%.2fs",
                carrier,
                lang,
                is_translated,
                latency,
            )
            return result

        except (AIValidationError, AITimeoutError):
            latency = time.time() - start_time
            logger.exception(
                "Summary failure (AI Error): carrier=%s, lang=%s, translated=%s, latency=%.2fs",
                carrier,
                lang,
                is_translated,
                latency,
            )
            raise
        except Exception:
            latency = time.time() - start_time
            logger.exception(
                "Summary failure (Unexpected Error): carrier=%s, lang=%s, translated=%s, latency=%.2fs",
                carrier,
                lang,
                is_translated,
                latency,
            )
            raise
