import json
from unittest.mock import AsyncMock, MagicMock, patch

import openai
from pydantic import ValidationError
import pytest

from app.ai.openai_client import (
    AITimeoutError,
    AIValidationError,
    FreightPulseAIClient,
)
from app.schemas.ai_outputs import RateOutlookOutput


@pytest.fixture
def mock_openai():
    with patch("app.ai.openai_client.AsyncAzureOpenAI") as mock:
        yield mock

@pytest.fixture
def ai_client(mock_openai):
    return FreightPulseAIClient(api_key="test-key")

@pytest.mark.asyncio
async def test_generate_structured_success(ai_client):
    # Setup mock response
    mock_response = MagicMock()
    mock_response.choices = [
        MagicMock(message=MagicMock(refusal=None, parsed=RateOutlookOutput(
            outlook_text="This is a valid test outlook that exceeds the minimum length requirement.",
            recommendation="wait",
            confidence=85
        )))
    ]
    mock_response.usage = MagicMock(prompt_tokens=100, completion_tokens=50)
    ai_client.client.beta.chat.completions.parse = AsyncMock(return_value=mock_response)

    # Call method
    result = await ai_client.generate_structured(
        system_prompt="You are a helpful assistant.",
        user_content="What is the outlook?",
        output_schema=RateOutlookOutput,
        feature_name="test_feature"
    )

    # Assertions
    assert isinstance(result, RateOutlookOutput)
    assert result.recommendation == "wait"
    assert result.confidence == 85
    ai_client.client.beta.chat.completions.parse.assert_called_once()


@pytest.mark.asyncio
async def test_generate_structured_retry_on_timeout(ai_client):
    # Setup mock to raise timeout then succeed
    mock_response = MagicMock()
    mock_response.choices = [
        MagicMock(message=MagicMock(refusal=None, parsed=RateOutlookOutput(
            outlook_text="This is a valid test outlook that exceeds the minimum length requirement.",
            recommendation="book_now",
            confidence=90
        )))
    ]
    mock_response.usage = MagicMock(prompt_tokens=100, completion_tokens=50)

    # Needs to fail once, then succeed
    ai_client.client.beta.chat.completions.parse = AsyncMock(side_effect=[
        openai.APITimeoutError(request=MagicMock()),
        mock_response
    ])

    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        result = await ai_client.generate_structured(
            system_prompt="System",
            user_content="User",
            output_schema=RateOutlookOutput,
            feature_name="test_feature"
        )

        assert isinstance(result, RateOutlookOutput)
        assert ai_client.client.beta.chat.completions.parse.call_count == 2
        mock_sleep.assert_called_once()

@pytest.mark.asyncio
async def test_generate_structured_validation_error_retry(ai_client):
    mock_valid_response = MagicMock()
    mock_valid_response.choices = [
        MagicMock(message=MagicMock(refusal=None, parsed=RateOutlookOutput(
            outlook_text="This is a valid test outlook that exceeds the minimum length requirement.",
            recommendation="book_now",
            confidence=95
        )))
    ]
    mock_valid_response.usage = MagicMock(prompt_tokens=100, completion_tokens=50)

    ai_client.client.beta.chat.completions.parse = AsyncMock(side_effect=[
        ValidationError.from_exception_data(title="RateOutlookOutput", line_errors=[]),
        mock_valid_response
    ])

    with patch("asyncio.sleep", new_callable=AsyncMock):
        result = await ai_client.generate_structured(
            system_prompt="System",
            user_content="User",
            output_schema=RateOutlookOutput,
            feature_name="test_feature"
        )

        assert isinstance(result, RateOutlookOutput)
        assert ai_client.client.beta.chat.completions.parse.call_count == 2
        # Verify prompt got adjusted
        call_args = ai_client.client.beta.chat.completions.parse.call_args_list[1]
        messages = call_args[1]["messages"]
        assert "Previous response failed validation" in messages[1]["content"]

@pytest.mark.asyncio
async def test_generate_structured_max_retries_exceeded(ai_client):
    # Always raise timeout
    ai_client.client.beta.chat.completions.parse = AsyncMock(side_effect=openai.APITimeoutError(request=MagicMock()))

    with patch("asyncio.sleep", new_callable=AsyncMock):
        with pytest.raises(AITimeoutError):
            await ai_client.generate_structured(
                system_prompt="System",
                user_content="User",
                output_schema=RateOutlookOutput,
                feature_name="test_feature"
            )

        assert ai_client.client.beta.chat.completions.parse.call_count == 3 # Initial + 2 retries


@pytest.mark.asyncio
async def test_generate_structured_json_decode_error_retry(ai_client):
    mock_valid_response = MagicMock()
    mock_valid_response.choices = [
        MagicMock(message=MagicMock(refusal=None, parsed=RateOutlookOutput(
            outlook_text="This is a valid test outlook that exceeds the minimum length requirement.",
            recommendation="book_now",
            confidence=95
        )))
    ]
    mock_valid_response.usage = MagicMock(prompt_tokens=100, completion_tokens=50)

    ai_client.client.beta.chat.completions.parse = AsyncMock(side_effect=[
        json.JSONDecodeError("Expecting value", "", 0),
        mock_valid_response
    ])

    with patch("asyncio.sleep", new_callable=AsyncMock):
        result = await ai_client.generate_structured(
            system_prompt="System",
            user_content="User",
            output_schema=RateOutlookOutput,
            feature_name="test_feature"
        )

        assert isinstance(result, RateOutlookOutput)
        assert ai_client.client.beta.chat.completions.parse.call_count == 2


def test_normalize_azure_endpoint():
    from app.ai.openai_client import normalize_azure_endpoint

    assert normalize_azure_endpoint("https://my-res.openai.azure.com/openai/v1") == "https://my-res.openai.azure.com"
    assert normalize_azure_endpoint("https://my-res.openai.azure.com/openai/v1/") == "https://my-res.openai.azure.com"
    assert normalize_azure_endpoint("https://my-res.openai.azure.com/openai") == "https://my-res.openai.azure.com"
    assert normalize_azure_endpoint("https://my-res.openai.azure.com/openai/") == "https://my-res.openai.azure.com"
    assert normalize_azure_endpoint("https://my-res.openai.azure.com/") == "https://my-res.openai.azure.com"
    assert normalize_azure_endpoint("https://my-res.openai.azure.com") == "https://my-res.openai.azure.com"
    assert normalize_azure_endpoint("") == ""
    assert normalize_azure_endpoint(None) == ""


@pytest.mark.asyncio
async def test_generate_structured_passes_max_completion_tokens(ai_client):
    mock_response = MagicMock()
    mock_response.choices = [
        MagicMock(message=MagicMock(refusal=None, parsed=RateOutlookOutput(
            outlook_text="This is a valid test outlook that exceeds the minimum length requirement.",
            recommendation="wait",
            confidence=85
        )))
    ]
    mock_response.usage = MagicMock(prompt_tokens=100, completion_tokens=50)
    ai_client.client.beta.chat.completions.parse = AsyncMock(return_value=mock_response)

    await ai_client.generate_structured(
        system_prompt="System",
        user_content="User",
        output_schema=RateOutlookOutput,
        feature_name="test_feature",
        max_tokens=1500,
        temperature=1.0,
    )

    ai_client.client.beta.chat.completions.parse.assert_called_once()
    call_kwargs = ai_client.client.beta.chat.completions.parse.call_args.kwargs
    assert "max_completion_tokens" in call_kwargs
    assert call_kwargs["max_completion_tokens"] == 1500
    assert "max_tokens" not in call_kwargs
