from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.app.ai.openai_client import (
    AITimeoutError,
    AIValidationError,
    FreightPulseAIClient,
)
from backend.app.ai.rate_outlook_narrator import RateOutlookNarrator
from backend.app.schemas.ai_outputs import RateOutlookOutput


@pytest.fixture
def mock_ai_client():
    client = MagicMock(spec=FreightPulseAIClient)
    client.generate_structured = AsyncMock()
    return client


@pytest.fixture
def narrator(mock_ai_client):
    return RateOutlookNarrator(ai_client=mock_ai_client)


@pytest.mark.asyncio
async def test_narrate_success_book_now(narrator, mock_ai_client):
    mock_output = RateOutlookOutput(
        outlook_text="Strong positive outlook for this lane based on historical trends.",
        recommendation="book_now",
        confidence=100,
    )
    mock_ai_client.generate_structured.return_value = mock_output

    result = await narrator.narrate(
        lane="US-EU",
        current_rate="$2000",
        historical_context="Rates were higher last year.",
        market_factors="Demand is rising.",
    )

    assert result == mock_output
    mock_ai_client.generate_structured.assert_called_once()
    
    call_kwargs = mock_ai_client.generate_structured.call_args.kwargs
    assert "rate_outlook_narrator" == call_kwargs["feature_name"]
    assert call_kwargs["output_schema"] == RateOutlookOutput
    assert "Do not invent or hallucinate market data" in call_kwargs["system_prompt"]
    assert "US-EU" in call_kwargs["user_content"]
    assert "$2000" in call_kwargs["user_content"]
    assert "Rates were higher last year." in call_kwargs["user_content"]
    assert "Demand is rising." in call_kwargs["user_content"]


@pytest.mark.asyncio
@pytest.mark.parametrize("recommendation, confidence", [
    ("book_now", 100),
    ("wait", 0),
    ("hedge", 50),
])
async def test_narrate_recommendation_and_confidence_bounds(narrator, mock_ai_client, recommendation, confidence):
    mock_output = RateOutlookOutput(
        outlook_text="Valid test outlook text exceeding minimum length required by schema.",
        recommendation=recommendation,
        confidence=confidence,
    )
    mock_ai_client.generate_structured.return_value = mock_output

    result = await narrator.narrate("Asia-US", "$1500", "Stable", "None")

    assert result == mock_output
    assert result.recommendation == recommendation
    assert result.confidence == confidence


@pytest.mark.asyncio
async def test_narrate_empty_lane(narrator):
    with pytest.raises(ValueError, match="Lane cannot be empty"):
        await narrator.narrate("", "$100", "None", "None")
        
    with pytest.raises(ValueError, match="Lane cannot be empty"):
        await narrator.narrate("   ", "$100", "None", "None")


@pytest.mark.asyncio
async def test_narrate_ai_validation_exception_propagates(narrator, mock_ai_client):
    mock_ai_client.generate_structured.side_effect = AIValidationError("Invalid schema")
    
    with pytest.raises(AIValidationError, match="Invalid schema"):
        await narrator.narrate("US-EU", "$1000", "None", "None")


@pytest.mark.asyncio
async def test_narrate_timeout_propagates(narrator, mock_ai_client):
    mock_ai_client.generate_structured.side_effect = AITimeoutError("Timeout")
    
    with pytest.raises(AITimeoutError, match="Timeout"):
        await narrator.narrate("US-EU", "$1000", "None", "None")


@pytest.mark.asyncio
@patch("backend.app.ai.rate_outlook_narrator.logger")
async def test_narrate_does_not_log_raw_input(mock_logger, narrator, mock_ai_client):
    mock_output = RateOutlookOutput(
        outlook_text="This is a sufficiently long test outlook text to pass the fifty character requirement.",
        recommendation="wait",
        confidence=50,
    )
    mock_ai_client.generate_structured.return_value = mock_output
    
    sensitive_historical_data = "Super secret historical data"
    sensitive_market_data = "Super secret market factors"

    await narrator.narrate(
        lane="US-EU",
        current_rate="$1000",
        historical_context=sensitive_historical_data,
        market_factors=sensitive_market_data,
    )

    mock_logger.info.assert_called_once()
    log_args = mock_logger.info.call_args.args
    log_msg = log_args[0]
    
    assert sensitive_historical_data not in log_msg
    assert sensitive_market_data not in log_msg
    
    # Also verify that when formatting happens in the logger, it doesn't leak.
    for arg in log_args[1:]:
        assert sensitive_historical_data not in str(arg)
        assert sensitive_market_data not in str(arg)

