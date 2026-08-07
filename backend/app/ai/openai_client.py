import json
import logging
import asyncio
from typing import TypeVar, Type, Any, Optional
from pydantic import BaseModel, ValidationError
from openai import AsyncOpenAI
import openai

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

class AITimeoutError(Exception):
    pass

class AIValidationError(Exception):
    pass

class FreightPulseAIClient:
    def __init__(self, api_key: Optional[str] = None):
        # AsyncOpenAI will automatically fall back to os.environ.get("OPENAI_API_KEY")
        self.client = AsyncOpenAI(api_key=api_key)
        self.cost_per_1m_input_tokens = 0.15
        self.cost_per_1m_output_tokens = 0.60

    def _log_usage(self, usage: Any, feature_name: str, model: str) -> None:
        if not usage:
            return
        
        input_tokens = usage.prompt_tokens
        output_tokens = usage.completion_tokens
        
        input_cost = (input_tokens / 1_000_000) * self.cost_per_1m_input_tokens
        output_cost = (output_tokens / 1_000_000) * self.cost_per_1m_output_tokens
        total_cost = input_cost + output_cost
        
        logger.info(
            f"AI Usage [{feature_name}]: model={model}, "
            f"input_tokens={input_tokens}, output_tokens={output_tokens}, "
            f"cost=${total_cost:.6f}"
        )

    async def generate_structured(
        self,
        system_prompt: str,
        user_content: str,
        output_schema: Type[T],
        feature_name: str,
        model: str = "gpt-4o-mini",
        temperature: float = 0.3,
        max_tokens: int = 1000
    ) -> T:
        retries = 2
        attempt = 0
        
        while attempt <= retries:
            try:
                response = await self.client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_content}
                    ],
                    temperature=temperature,
                    max_tokens=max_tokens,
                    response_format={"type": "json_object"}
                )
                
                self._log_usage(response.usage, feature_name, model)
                
                content = response.choices[0].message.content
                if not content:
                    raise AIValidationError("Received empty content from OpenAI")
                    
                parsed_json = json.loads(content)
                return output_schema.model_validate(parsed_json)
                
            except (openai.APITimeoutError, asyncio.TimeoutError) as e:
                attempt += 1
                if attempt > retries:
                    raise AITimeoutError(f"OpenAI API timed out after {retries} retries.") from e
                await asyncio.sleep(2 ** attempt)
                
            except (openai.APIError, openai.APIConnectionError, openai.RateLimitError, openai.InternalServerError) as e:
                attempt += 1
                if attempt > retries:
                    raise e
                await asyncio.sleep(2 ** attempt)
                
            except (ValidationError, json.JSONDecodeError) as e:
                attempt += 1
                if attempt > retries:
                    raise AIValidationError(f"Failed to validate response against schema after {retries} retries: {e}") from e
                # Adjust user content to include the validation error for the retry
                user_content += f"\n\nPrevious response failed validation: {e}. Please ensure the response exactly matches the required JSON schema."
                await asyncio.sleep(1)
