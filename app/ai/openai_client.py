from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional, TypeVar

import openai
from openai import AsyncAzureOpenAI
from openai.types import CompletionUsage
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

def normalize_azure_endpoint(endpoint: str) -> str:
    """Normalize Azure OpenAI endpoint URL to resource root.

    Strips trailing '/openai/v1', '/openai', and trailing slashes so AsyncAzureOpenAI
    receives the expected resource host (e.g. https://<resource>.openai.azure.com).
    """
    if not endpoint:
        return ""
    ep = endpoint.strip().rstrip("/")
    if ep.endswith("/openai/v1"):
        ep = ep[:-len("/openai/v1")]
    elif ep.endswith("/openai"):
        ep = ep[:-len("/openai")]
    return ep.rstrip("/")


class FreightPulseAIClient:
    def __init__(
        self,
        api_key: Optional[str] = None,  # noqa: UP045
        model: Optional[str] = None,  # noqa: UP045
        temperature: Optional[float] = None,  # noqa: UP045
        max_tokens: Optional[int] = None,  # noqa: UP045
        timeout: float = 30.0,
    ):
        normalized_endpoint = normalize_azure_endpoint(settings.AZURE_OPENAI_ENDPOINT)
        self.client = AsyncAzureOpenAI(
            azure_endpoint=normalized_endpoint,
            api_key=api_key or settings.AZURE_OPENAI_API_KEY,
            api_version=settings.AZURE_OPENAI_API_VERSION,
            timeout=timeout,
        )
        self.model = model or getattr(settings, "AI_MODEL", "gpt-5-mini")
        self.temperature = temperature if temperature is not None else getattr(settings, "AI_TEMPERATURE", 1.0)
        self.max_tokens = max_tokens if max_tokens is not None else getattr(settings, "AI_MAX_TOKENS", 3500)

        self.cost_per_1m_input_tokens = getattr(settings, "AI_INPUT_COST_PER_1M_TOKENS", 0.0)
        self.cost_per_1m_output_tokens = getattr(settings, "AI_OUTPUT_COST_PER_1M_TOKENS", 0.0)

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
        azure_deployment = settings.AZURE_OPENAI_DEPLOYMENT

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
        input_tokens = output_tokens = 0
        actual_cost = 0.0
        response_received = False
        reservation_state = "active"
        result = None
        failure = None

        try:
            while attempt <= retries:
                try:
                    parse_kwargs: dict[str, Any] = {
                        "model": azure_deployment,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_content}
                        ],
                        "response_format": output_schema,
                    }
                    if effective_max_tokens is not None:
                        parse_kwargs["max_completion_tokens"] = effective_max_tokens
                    if effective_temperature is not None and effective_temperature != 1.0:
                        parse_kwargs["temperature"] = effective_temperature

                    # One SDK request; defer its same structured parser until usage
                    # is captured, including responses whose output cannot validate.
                    raw = await self.client.beta.chat.completions.with_raw_response.parse(**parse_kwargs)
                    response_received = True
                    body = raw.http_response.json()
                    usage = CompletionUsage.model_validate(body["usage"]) if body.get("usage") is not None else None
                    if usage is not None:
                        input_tokens += usage.prompt_tokens
                        output_tokens += usage.completion_tokens
                        actual_cost += (
                            usage.prompt_tokens / 1_000_000 * self.cost_per_1m_input_tokens
                            + usage.completion_tokens / 1_000_000 * self.cost_per_1m_output_tokens
                        )
                    self._log_usage(usage, feature_name, effective_model, prompt_version=prompt_version)
                    response = raw.parse()
                    message = response.choices[0].message
                    if getattr(message, "refusal", None):
                        raise AIValidationError(f"Model refused: {message.refusal}")
                    result = output_schema.model_validate(message.parsed)
                    break
                except (openai.APITimeoutError, asyncio.TimeoutError) as exc:
                    attempt += 1
                    if attempt > retries:
                        raise AITimeoutError(f"OpenAI API timed out after {retries} retries.") from exc
                    await asyncio.sleep(2 ** attempt)
                except (openai.APIConnectionError, openai.RateLimitError, openai.InternalServerError):
                    attempt += 1
                    if attempt > retries:
                        raise
                    await asyncio.sleep(2 ** attempt)
                except (ValidationError, json.JSONDecodeError) as exc:
                    attempt += 1
                    if attempt > retries:
                        raise AIValidationError(f"Failed to validate response against schema after {retries} retries: {exc}") from exc
                    user_content += f"\n\nPrevious response failed validation: {exc}. Please ensure the response exactly matches the required JSON schema."
                    await asyncio.sleep(1)
        except Exception as exc:
            failure = exc

        # Set attempted BEFORE awaiting: a Redis error may follow remote execution.
        # Never retry settlement or release after an indeterminate reconciliation.
        # This is local ordinary-execution discipline, not distributed exactly-once.
        if reservation_state == "active":
            reservation_state = "attempted"
            try:
                if response_received:
                    await BudgetGuard.reconcile_success(est_micro_usd, actual_cost)
                else:
                    await BudgetGuard.release_reservation(est_micro_usd)
                reservation_state = "completed"  # Existing fail-open policy may mask an outage.
            except Exception as exc:
                failure = exc  # Settlement remains indeterminate; no further cleanup.

        # One terminal LOGICAL-call outcome, carrying all captured response usage.
        # CancelledError deliberately retains the existing unsupported boundary.
        await AITelemetry.record_call(
            feature_name=feature_name,
            prompt_version=prompt_version or "v1",
            model=effective_model,
            success=failure is None,
            latency=time.time() - start_time,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            actual_cost=actual_cost,
            error_type=type(failure).__name__ if failure is not None else None,
        )
        if failure is not None:
            raise failure
        return result
