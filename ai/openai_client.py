"""OpenAI client wrapper for FreightPulse AI.

Implements FreightPulseAIClient per AI_IMPLEMENTATION_PLAN §5.2:
- Structured output with automatic Pydantic validation
- Retry once on Pydantic validation failure
- Exponential backoff (1s, 2s) on retryable OpenAI errors
- 30s timeout per attempt via asyncio.wait_for
- response_format={"type": "json_object"} on every call
- Token usage + estimated cost logging via structlog

NOTE: Owned by AI-B. Provided as the reference implementation of the §5.2
interface (see AI_B_HANDOFF_REPORT.md, Section 5 / Errata #1).
"""
import asyncio
import json
import os
from typing import TypeVar

from dotenv import load_dotenv
from openai import (
    APIConnectionError,
    AsyncOpenAI,
    InternalServerError,
    RateLimitError,
)
from pydantic import BaseModel, ValidationError

from ai.logging import get_logger

logger = get_logger(__name__)

load_dotenv()

# --- Configuration constants (no magic numbers) ------------------------------
DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_TEMPERATURE = 0.3
DEFAULT_MAX_TOKENS = 1000
TIMEOUT_SECONDS = 30.0
VALIDATION_RETRY_COUNT = 1                # retry once on Pydantic validation failure
BACKOFF_SCHEDULE_SECONDS = (1.0, 2.0)     # exponential backoff for retryable API errors

# Approximate USD cost per 1K tokens (for cost logging only — not billing).
COST_PER_1K_TOKENS = {
    "gpt-4o-mini": {"input": 0.00015, "output": 0.00060},
    "gpt-4o": {"input": 0.00250, "output": 0.01000},
}

# Retryable OpenAI SDK exceptions (transient failures worth backing off on)
_RETRYABLE_ERRORS = (APIConnectionError, RateLimitError, InternalServerError)

T = TypeVar("T", bound=BaseModel)


class LLMGenerationError(Exception):
    """Raised when the LLM cannot produce a valid, schema-compliant response."""


class FreightPulseAIClient:
    """Async OpenAI wrapper producing validated Pydantic outputs."""

    def __init__(self, api_key: str | None = None, default_model: str = DEFAULT_MODEL):
        self._default_model = default_model
        self._client = AsyncOpenAI(api_key=api_key or os.getenv("OPENAI_API_KEY"))

    async def generate_structured(
        self,
        system_prompt: str,
        user_content: str,
        output_schema: type[T],
        model: str | None = None,
        temperature: float = DEFAULT_TEMPERATURE,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> T:
        """Generate a structured output validated against ``output_schema``.

        Args:
            system_prompt: System instruction for the model.
            user_content: User message content.
            output_schema: Pydantic model class to validate the response against.
            model: Optional model override (defaults to the client's default).
            temperature: Sampling temperature.
            max_tokens: Maximum tokens in the response.

        Returns:
            A validated instance of ``output_schema``.

        Raises:
            LLMGenerationError: If all attempts fail to produce valid output.
        """
        selected_model = model or self._default_model
        last_error: Exception | None = None

        for validation_attempt in range(VALIDATION_RETRY_COUNT + 1):
            # 1) Call the API (with backoff + timeout for transient errors)
            try:
                raw_content, usage = await self._call_with_backoff(
                    system_prompt=system_prompt,
                    user_content=user_content,
                    model=selected_model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            except LLMGenerationError as exc:
                last_error = exc
                break  # API-level failure already exhausted backoff retries

            # 2) Log token usage + estimated cost
            self._log_usage(selected_model, usage)

            # 3) Parse JSON and validate against the Pydantic schema
            try:
                parsed = json.loads(raw_content)
                validated = output_schema.model_validate(parsed)
            except (json.JSONDecodeError, ValidationError) as exc:
                last_error = exc
                logger.warning(
                    "llm_validation_failed",
                    model=selected_model,
                    schema=output_schema.__name__,
                    validation_attempt=validation_attempt,
                    error=str(exc)[:200],
                )
                continue  # retry validation (if attempts remain)

            logger.info(
                "llm_structured_generation_ok",
                model=selected_model,
                schema=output_schema.__name__,
                validation_attempt=validation_attempt,
            )
            return validated

        raise LLMGenerationError(
            f"Failed to generate valid {output_schema.__name__} after retries"
        ) from last_error

    async def _call_with_backoff(
        self,
        system_prompt: str,
        user_content: str,
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> tuple[str, dict]:
        """Execute the OpenAI call with a 30s timeout and exponential backoff.

        Returns:
            A tuple of (raw_response_content, usage_dict).

        Raises:
            LLMGenerationError: If all attempts fail with retryable errors/timeout.
        """
        last_error: Exception | None = None
        total_attempts = len(BACKOFF_SCHEDULE_SECONDS) + 1

        for attempt in range(total_attempts):
            try:
                response = await asyncio.wait_for(
                    self._client.chat.completions.create(
                        model=model,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_content},
                        ],
                        temperature=temperature,
                        max_tokens=max_tokens,
                        response_format={"type": "json_object"},
                    ),
                    timeout=TIMEOUT_SECONDS,
                )
                if not response.choices:
                    raise LLMGenerationError("OpenAI returned no choices")
                content = response.choices[0].message.content or ""
                return content, self._extract_usage(response)

            except asyncio.TimeoutError as exc:
                last_error = exc
                logger.warning("llm_request_timeout", model=model, attempt=attempt)
            except _RETRYABLE_ERRORS as exc:
                last_error = exc
                logger.warning(
                    "llm_retryable_error", model=model, attempt=attempt, error=str(exc)[:200]
                )
            except LLMGenerationError:
                raise

            # Back off before the next attempt (if attempts remain)
            if attempt < total_attempts - 1:
                await asyncio.sleep(BACKOFF_SCHEDULE_SECONDS[attempt])

        raise LLMGenerationError(
            f"OpenAI call failed after {total_attempts} attempts"
        ) from last_error

    @staticmethod
    def _extract_usage(response) -> dict:
        """Extract token usage counters from an OpenAI response."""
        usage = getattr(response, "usage", None)
        if usage is None:
            return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        return {
            "prompt_tokens": usage.prompt_tokens,
            "completion_tokens": usage.completion_tokens,
            "total_tokens": usage.total_tokens,
        }

    @staticmethod
    def _estimate_cost_usd(model: str, usage: dict) -> float:
        """Estimate the USD cost of a call from its token usage."""
        rates = COST_PER_1K_TOKENS.get(model, COST_PER_1K_TOKENS[DEFAULT_MODEL])
        input_cost = (usage["prompt_tokens"] / 1000.0) * rates["input"]
        output_cost = (usage["completion_tokens"] / 1000.0) * rates["output"]
        return round(input_cost + output_cost, 6)

    def _log_usage(self, model: str, usage: dict) -> None:
        """Log token usage and estimated cost via structured logging."""
        logger.info(
            "llm_token_usage",
            model=model,
            prompt_tokens=usage["prompt_tokens"],
            completion_tokens=usage["completion_tokens"],
            total_tokens=usage["total_tokens"],
            estimated_cost_usd=self._estimate_cost_usd(model, usage),
        )