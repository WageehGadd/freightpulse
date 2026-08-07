from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.app.ai.carrier_summarizer import CarrierSummarizer
from backend.app.ai.openai_client import (
    AITimeoutError,
    AIValidationError,
    FreightPulseAIClient,
)
from backend.app.ai.translator import CarrierTranslator, TranslationError
from backend.app.schemas.ai_outputs import CarrierSummaryOutput


@pytest.fixture
def mock_ai_client():
    client = MagicMock(spec=FreightPulseAIClient)
    client.generate_structured = AsyncMock()
    return client


@pytest.fixture
def mock_translator():
    translator = MagicMock(spec=CarrierTranslator)
    return translator


@pytest.fixture
def summarizer(mock_ai_client, mock_translator):
    return CarrierSummarizer(ai_client=mock_ai_client, translator=mock_translator)


@pytest.mark.asyncio
async def test_summarize_english_advisory(summarizer, mock_ai_client, mock_translator):
    mock_translator.detect_language.return_value = "en"
    
    mock_output = CarrierSummaryOutput(
        summary="Test English summary",
        advisory_type="surcharge",
        affected_lanes=["US-EU"],
        impact_severity="low"
    )
    mock_ai_client.generate_structured.return_value = mock_output
    
    result = await summarizer.summarize("Carrier A", "Test Title", "Test English Advisory")
    
    assert result == mock_output
    mock_translator.detect_language.assert_called_once_with("Test English Advisory")
    mock_translator.translate.assert_not_called()
    
    # Assert generated structured was called
    mock_ai_client.generate_structured.assert_called_once()
    call_kwargs = mock_ai_client.generate_structured.call_args.kwargs
    assert "Test English Advisory" in call_kwargs["user_content"]


@pytest.mark.asyncio
async def test_summarize_arabic_advisory(summarizer, mock_ai_client, mock_translator):
    mock_translator.detect_language.return_value = "ar"
    mock_translator.translate.return_value = "Translated English text"
    
    mock_output = CarrierSummaryOutput(
        summary="Test Arabic to English summary",
        advisory_type="surcharge",
        affected_lanes=["US-EU"],
        impact_severity="low"
    )
    mock_ai_client.generate_structured.return_value = mock_output
    
    result = await summarizer.summarize("Carrier B", "Arabic Title", "Arabic Advisory")
    
    assert result == mock_output
    mock_translator.detect_language.assert_called_once_with("Arabic Advisory")
    mock_translator.translate.assert_called_once_with("Arabic Advisory")
    
    mock_ai_client.generate_structured.assert_called_once()
    call_kwargs = mock_ai_client.generate_structured.call_args.kwargs
    assert "Translated English text" in call_kwargs["user_content"]


@pytest.mark.asyncio
async def test_summarize_translator_failure_falls_back(summarizer, mock_ai_client, mock_translator):
    # Detect language works, but translate fails
    mock_translator.detect_language.return_value = "ar"
    mock_translator.translate.side_effect = TranslationError("Model failed")
    
    mock_output = CarrierSummaryOutput(
        summary="Test fallback summary",
        advisory_type="surcharge",
        affected_lanes=["US-EU"],
        impact_severity="low"
    )
    mock_ai_client.generate_structured.return_value = mock_output
    
    result = await summarizer.summarize("Carrier C", "Failed Title", "Fallback Advisory")
    
    assert result == mock_output
    mock_translator.detect_language.assert_called_once_with("Fallback Advisory")
    mock_translator.translate.assert_called_once_with("Fallback Advisory")
    
    mock_ai_client.generate_structured.assert_called_once()
    call_kwargs = mock_ai_client.generate_structured.call_args.kwargs
    # Should fall back to the original text
    assert "Fallback Advisory" in call_kwargs["user_content"]


@pytest.mark.asyncio
async def test_summarize_empty_advisory(summarizer):
    with pytest.raises(ValueError, match="Advisory text cannot be empty"):
        await summarizer.summarize("Carrier D", "Title", "")
        
    with pytest.raises(ValueError, match="Advisory text cannot be empty"):
        await summarizer.summarize("Carrier D", "Title", "   ")


@pytest.mark.asyncio
async def test_summarize_ai_validation_exception_propagates(summarizer, mock_ai_client, mock_translator):
    mock_translator.detect_language.return_value = "en"
    mock_ai_client.generate_structured.side_effect = AIValidationError("Invalid schema")
    
    with pytest.raises(AIValidationError, match="Invalid schema"):
        await summarizer.summarize("Carrier E", "Title", "Text")


@pytest.mark.asyncio
async def test_summarize_timeout_propagates(summarizer, mock_ai_client, mock_translator):
    mock_translator.detect_language.return_value = "en"
    mock_ai_client.generate_structured.side_effect = AITimeoutError("Timeout reached")
    
    with pytest.raises(AITimeoutError, match="Timeout reached"):
        await summarizer.summarize("Carrier F", "Title", "Text")
