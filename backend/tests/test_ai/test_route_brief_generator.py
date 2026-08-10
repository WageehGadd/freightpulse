from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.app.ai.openai_client import (
    AITimeoutError,
    AIValidationError,
    FreightPulseAIClient,
)
from backend.app.ai.route_brief_generator import RouteBriefGenerator
from backend.app.schemas.ai_outputs import RouteBriefOutput


@pytest.fixture
def mock_ai_client():
    client = MagicMock(spec=FreightPulseAIClient)
    client.generate_structured = AsyncMock()
    return client


@pytest.fixture
def generator(mock_ai_client):
    return RouteBriefGenerator(ai_client=mock_ai_client)


@pytest.mark.asyncio
async def test_generate_brief_success(generator, mock_ai_client):
    mock_output = RouteBriefOutput(
        brief_markdown="This is a fully verified test route brief markdown string that is over one hundred characters long. Ensuring length constraint.",
        recommendation="ship_now",
        risk_level="low",
    )
    mock_ai_client.generate_structured.return_value = mock_output

    result = await generator.generate_brief(
        origin="Shanghai, CN",
        destination="Los Angeles, US",
        carrier="CarrierX",
        advisories="No severe advisories.",
        conditions="Clear weather.",
    )

    assert result == mock_output
    mock_ai_client.generate_structured.assert_called_once()
    
    call_kwargs = mock_ai_client.generate_structured.call_args.kwargs
    assert "route_brief" == call_kwargs["feature_name"]
    assert call_kwargs["output_schema"] == RouteBriefOutput
    assert "Do not invent or hallucinate" in call_kwargs["system_prompt"]
    assert "Shanghai, CN" in call_kwargs["user_content"]
    assert "Los Angeles, US" in call_kwargs["user_content"]
    assert "CarrierX" in call_kwargs["user_content"]
    assert "No severe advisories." in call_kwargs["user_content"]
    assert "Clear weather." in call_kwargs["user_content"]


@pytest.mark.asyncio
@pytest.mark.parametrize("recommendation, risk_level", [
    ("ship_now", "low"),
    ("wait", "medium"),
    ("reroute", "high"),
])
async def test_generate_brief_recommendation_and_risk_bounds(generator, mock_ai_client, recommendation, risk_level):
    mock_output = RouteBriefOutput(
        brief_markdown="This is a valid route brief text exceeding the minimum length required by schema. Very important information. Must be above one hundred length.",
        recommendation=recommendation,
        risk_level=risk_level,
    )
    mock_ai_client.generate_structured.return_value = mock_output

    result = await generator.generate_brief("Origin", "Destination", "Carrier", "Advisories", "Conditions")

    assert result == mock_output
    assert result.recommendation == recommendation
    assert result.risk_level == risk_level


@pytest.mark.asyncio
async def test_generate_brief_empty_inputs(generator):
    with pytest.raises(ValueError, match="Origin cannot be empty"):
        await generator.generate_brief("", "Dest", "Carrier", "None", "None")
        
    with pytest.raises(ValueError, match="Origin cannot be empty"):
        await generator.generate_brief("   ", "Dest", "Carrier", "None", "None")
        
    with pytest.raises(ValueError, match="Destination cannot be empty"):
        await generator.generate_brief("Origin", "", "Carrier", "None", "None")


@pytest.mark.asyncio
async def test_generate_brief_ai_validation_exception_propagates(generator, mock_ai_client):
    mock_ai_client.generate_structured.side_effect = AIValidationError("Invalid schema")
    
    with pytest.raises(AIValidationError, match="Invalid schema"):
        await generator.generate_brief("Origin", "Dest", "Carrier", "None", "None")


@pytest.mark.asyncio
async def test_generate_brief_timeout_propagates(generator, mock_ai_client):
    mock_ai_client.generate_structured.side_effect = AITimeoutError("Timeout")
    
    with pytest.raises(AITimeoutError, match="Timeout"):
        await generator.generate_brief("Origin", "Dest", "Carrier", "None", "None")


@pytest.mark.asyncio
async def test_generate_brief_unexpected_exception_propagates(generator, mock_ai_client):
    mock_ai_client.generate_structured.side_effect = RuntimeError("Broken logic")
    
    with pytest.raises(RuntimeError, match="Broken logic"):
        await generator.generate_brief("Origin", "Dest", "Carrier", "None", "None")


@pytest.mark.asyncio
@patch("backend.app.ai.route_brief_generator.logger")
async def test_generate_brief_does_not_log_raw_input(mock_logger, generator, mock_ai_client):
    mock_output = RouteBriefOutput(
        brief_markdown="This is a fully verified test route brief markdown string that is over one hundred characters long. Ensuring length constraint.",
        recommendation="ship_now",
        risk_level="low",
    )
    mock_ai_client.generate_structured.return_value = mock_output
    
    sensitive_advisory = "Super secret advisory for VIP client"
    sensitive_condition = "Super secret condition"

    await generator.generate_brief(
        origin="Origin",
        destination="Dest",
        carrier="Carrier",
        advisories=sensitive_advisory,
        conditions=sensitive_condition,
    )

    mock_logger.info.assert_called_once()
    log_args = mock_logger.info.call_args.args
    log_msg = log_args[0]
    
    assert sensitive_advisory not in log_msg
    assert sensitive_condition not in log_msg
    
    # Also verify that when formatting happens in the logger, it doesn't leak.
    for arg in log_args[1:]:
        assert sensitive_advisory not in str(arg)
        assert sensitive_condition not in str(arg)
