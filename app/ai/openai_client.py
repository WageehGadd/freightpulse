import asyncio
import json
import logging
from typing import Type, TypeVar
# pyrefly: ignore [missing-import]
import openai
# pyrefly: ignore [missing-import]
from openai import AsyncOpenAI
# pyrefly: ignore [missing-import]
from pydantic import BaseModel, ValidationError

from app.config import settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class AITimeoutError(Exception):
    """Raised when OpenAI API call exceeds timeout limit."""


class AIValidationError(Exception):
    """Raised when OpenAI API response fails schema validation."""


class AIGenerationError(Exception):
    """Raised on general AI generation failures."""


class FreightPulseAIClient:
    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ):
        self.api_key = api_key or settings.OPENAI_API_KEY
        self.model = model if model is not None else settings.AI_MODEL
        self.temperature = temperature if temperature is not None else settings.AI_TEMPERATURE
        self.max_tokens = max_tokens if max_tokens is not None else settings.AI_MAX_TOKENS
        self.cost_per_1m_input_tokens = 0.15
        self.cost_per_1m_output_tokens = 0.60
        self.client = AsyncOpenAI(api_key=self.api_key or "sk-dummy")

    async def generate_structured(
        self,
        system_prompt: str,
        user_content: str,
        output_schema: Type[T],
        feature_name: str = "ai_feature",
        prompt_version: str = "v1",
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> T:
        selected_model = model or self.model
        selected_temp = temperature if temperature is not None else self.temperature
        selected_tokens = max_tokens if max_tokens is not None else self.max_tokens

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

        max_attempts = 3
        last_error = None

        for attempt in range(max_attempts):
            try:
                response = await self.client.chat.completions.create(
                    model=selected_model,
                    messages=messages,
                    temperature=selected_temp,
                    max_tokens=selected_tokens,
                    response_format={"type": "json_object"},
                )

                usage = getattr(response, "usage", None)
                if usage:
                    self._log_usage(usage, feature_name, selected_model, prompt_version=prompt_version)

                if not response.choices:
                    raise AIValidationError("No choices returned from OpenAI")

                raw_content = response.choices[0].message.content or ""
                try:
                    parsed_json = json.loads(raw_content)
                except Exception as json_err:
                    if attempt < max_attempts - 1:
                        await asyncio.sleep(0.5 * (2**attempt))
                        continue
                    raise AIValidationError(f"Invalid JSON response: {json_err}") from json_err

                validated = output_schema.model_validate(parsed_json)
                return validated

            except (openai.APITimeoutError, asyncio.TimeoutError) as exc:
                last_error = exc
                if attempt < max_attempts - 1:
                    await asyncio.sleep(0.5 * (2**attempt))
                    continue
                raise AITimeoutError(f"OpenAI API call timed out: {exc}") from exc

            except ValidationError as val_err:
                last_error = val_err
                if attempt < max_attempts - 1:
                    messages = [
                        {"role": "system", "content": system_prompt},
                        {
                            "role": "user",
                            "content": f"{user_content}\n\nPrevious response failed validation with error: {val_err}. Please output valid JSON matching the schema.",
                        },
                    ]
                    await asyncio.sleep(0.5 * (2**attempt))
                    continue
                raise AIValidationError(f"Response failed validation: {val_err}") from val_err

            except (AITimeoutError, AIValidationError):
                raise
            except Exception as exc:
                last_error = exc
                if attempt < max_attempts - 1:
                    await asyncio.sleep(0.5 * (2**attempt))
                    continue
                raise AIGenerationError(f"AI generation failed: {exc}") from exc

        raise AIGenerationError(f"Failed after {max_attempts} attempts: {last_error}")

    def _log_usage(
        self,
        usage,
        feature_name: str,
        model: str,
        prompt_version: str = "v1",
    ) -> None:
        prompt_tokens = getattr(usage, "prompt_tokens", 0)
        completion_tokens = getattr(usage, "completion_tokens", 0)
        est_cost = (
            (prompt_tokens / 1_000_000.0) * self.cost_per_1m_input_tokens
            + (completion_tokens / 1_000_000.0) * self.cost_per_1m_output_tokens
        )
        logger.info(
            f"AI Usage [{feature_name}] - prompt_version={prompt_version}, model={model}, "
            f"prompt_tokens={prompt_tokens}, completion_tokens={completion_tokens}, cost_usd={est_cost:.6f}"
        )
