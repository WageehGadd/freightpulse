from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional, TypeVar

import openai
from openai import AsyncOpenAI
from pydantic import BaseModel, ValidationError

import time

from app.ai.budget_guard import BudgetGuard
from app.ai.telemetry import AITelemetry
from app.config import settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

class AITimeoutError(Exception):
    pass

class AIValidationError(Exception):
    pass

class FreightPulseAIClient:
    def __init__(
        self,
        api_key: Optional[str] = None,  # noqa: UP045
        model: Optional[str] = None,  # noqa: UP045
        temperature: Optional[float] = None,  # noqa: UP045
        max_tokens: Optional[int] = None,  # noqa: UP045
    ):
        # AsyncOpenAI will automatically fall back to os.environ.get("OPENAI_API_KEY")
        self.client = AsyncOpenAI(api_key=api_key)
        self.model = model or getattr(settings, "AI_MODEL", "gpt-4o-mini")
        self.temperature = temperature if temperature is not None else getattr(settings, "AI_TEMPERATURE", 0.3)
        self.max_tokens = max_tokens if max_tokens is not None else getattr(settings, "AI_MAX_TOKENS", 1000)
        self.cost_per_1m_input_tokens = 0.15
        self.cost_per_1m_output_tokens = 0.60

    def _log_usage(
        self,
        usage: Any,
        feature_name: str,
        model: str,
        prompt_version: Optional[str] = None,  # noqa: UP045
    ) -> None:
        if not usage:
            return

        input_tokens = usage.prompt_tokens
        output_tokens = usage.completion_tokens

        input_cost = (input_tokens / 1_000_000) * self.cost_per_1m_input_tokens
        output_cost = (output_tokens / 1_000_000) * self.cost_per_1m_output_tokens
        total_cost = input_cost + output_cost

        version_str = f" prompt_version={prompt_version}," if prompt_version else ""
        logger.info(
            f"AI Usage [{feature_name}]:{version_str} model={model}, "
            f"input_tokens={input_tokens}, output_tokens={output_tokens}, "
            f"cost=${total_cost:.6f}"
        )

    async def generate_structured(
        self,
        system_prompt: str,
        user_content: str,
        output_schema: type[T],
        feature_name: str,
        model: Optional[str] = None,  # noqa: UP045
        temperature: Optional[float] = None,  # noqa: UP045
        max_tokens: Optional[int] = None,  # noqa: UP045
        prompt_version: Optional[str] = None,  # noqa: UP045
    ) -> T:
        effective_model = model or self.model
        effective_temperature = temperature if temperature is not None else self.temperature
        effective_max_tokens = max_tokens if max_tokens is not None else self.max_tokens

        # Pre-call budget reservation & rate limit check
        estimated_cost = BudgetGuard.estimate_request_cost(
            system_prompt,
            user_content,
            effective_max_tokens,
            self.cost_per_1m_input_tokens,
            self.cost_per_1m_output_tokens,
        )

        try:
            est_micro_usd = await BudgetGuard.check_and_reserve(
                estimated_cost_usd=estimated_cost,
                feature_name=feature_name,
            )
        except Exception as exc:
            # Telemetry record for budget / rate limit block
            await AITelemetry.record_call(
                feature_name=feature_name,
                prompt_version=prompt_version or "v1",
                model=effective_model,
                success=False,
                latency=0.0,
                error_type=type(exc).__name__,
            )
            raise

        start_time = time.time()
        retries = 2
        attempt = 0

        while attempt <= retries:
            try:
                response = await self.client.chat.completions.create(
                    model=effective_model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_content}
                    ],
                    temperature=effective_temperature,
                    max_tokens=effective_max_tokens,
                    response_format={"type": "json_object"}
                )

                latency = time.time() - start_time
                self._log_usage(response.usage, feature_name, effective_model, prompt_version=prompt_version)

                input_tokens = response.usage.prompt_tokens if response.usage else 0
                output_tokens = response.usage.completion_tokens if response.usage else 0
                actual_cost = (
                    (input_tokens / 1_000_000) * self.cost_per_1m_input_tokens
                    + (output_tokens / 1_000_000) * self.cost_per_1m_output_tokens
                )

                # Reconcile budget reservation with actual cost
                await BudgetGuard.reconcile_success(est_micro_usd, actual_cost)

                # Telemetry record for success
                await AITelemetry.record_call(
                    feature_name=feature_name,
                    prompt_version=prompt_version or "v1",
                    model=effective_model,
                    success=True,
                    latency=latency,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    actual_cost=actual_cost,
                )

                content = response.choices[0].message.content
                if not content:
                    raise AIValidationError("Received empty content from OpenAI")

                parsed_json = json.loads(content)
                return output_schema.model_validate(parsed_json)

            except (openai.APITimeoutError, asyncio.TimeoutError) as e:
                attempt += 1
                if attempt > retries:
                    latency = time.time() - start_time
                    await BudgetGuard.release_reservation(est_micro_usd)
                    await AITelemetry.record_call(
                        feature_name=feature_name,
                        prompt_version=prompt_version or "v1",
                        model=effective_model,
                        success=False,
                        latency=latency,
                        error_type="AITimeoutError",
                    )
                    raise AITimeoutError(f"OpenAI API timed out after {retries} retries.") from e
                await asyncio.sleep(2 ** attempt)

            except (openai.APIError, openai.APIConnectionError, openai.RateLimitError, openai.InternalServerError) as e:
                attempt += 1
                if attempt > retries:
                    latency = time.time() - start_time
                    await BudgetGuard.release_reservation(est_micro_usd)
                    await AITelemetry.record_call(
                        feature_name=feature_name,
                        prompt_version=prompt_version or "v1",
                        model=effective_model,
                        success=False,
                        latency=latency,
                        error_type=type(e).__name__,
                    )
                    raise
                await asyncio.sleep(2 ** attempt)

            except (ValidationError, json.JSONDecodeError) as e:
                attempt += 1
                if attempt > retries:
                    latency = time.time() - start_time
                    await BudgetGuard.release_reservation(est_micro_usd)
                    await AITelemetry.record_call(
                        feature_name=feature_name,
                        prompt_version=prompt_version or "v1",
                        model=effective_model,
                        success=False,
                        latency=latency,
                        error_type="AIValidationError",
                    )
                    raise AIValidationError(f"Failed to validate response against schema after {retries} retries: {e}") from e
                # Adjust user content to include the validation error for the retry
                user_content += f"\n\nPrevious response failed validation: {e}. Please ensure the response exactly matches the required JSON schema."
                await asyncio.sleep(1)
            except Exception as e:
                latency = time.time() - start_time
                await BudgetGuard.release_reservation(est_micro_usd)
                await AITelemetry.record_call(
                    feature_name=feature_name,
                    prompt_version=prompt_version or "v1",
                    model=effective_model,
                    success=False,
                    latency=latency,
                    error_type=type(e).__name__,
                )
                raise
