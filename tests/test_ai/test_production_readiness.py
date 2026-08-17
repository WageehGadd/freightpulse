import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from app.ai.carrier_summarizer import CarrierSummarizer
from app.ai.openai_client import AITimeoutError, FreightPulseAIClient
from app.ai.prompts import registry
from app.ai.rate_outlook_narrator import RateOutlookNarrator
from app.ai.route_brief_generator import RouteBriefGenerator
from app.ai.translator import CarrierTranslator
from app.auth.rate_limit import RateLimiter
from app.auth.security import get_current_admin_user, get_current_user
from app.config import settings
from app.main import app
from app.models.user import User
from app.schemas.ai_outputs import (
    CarrierSummaryOutput,
    RateOutlookOutput,
    RouteBriefOutput,
)



@pytest.fixture
def mock_ai_client():
    client = MagicMock(spec=FreightPulseAIClient)
    client.model = settings.AI_MODEL
    client.cost_per_1m_input_tokens = 0.15
    client.cost_per_1m_output_tokens = 0.60
    client.generate_structured = AsyncMock()
    return client


@pytest.fixture
def mock_translator():
    translator = MagicMock(spec=CarrierTranslator)
    translator.detect_language.return_value = "en"
    return translator


@pytest.mark.asyncio
async def test_carrier_summarizer_e2e_wiring(mock_ai_client, mock_translator):
    """Verify CarrierSummarizer wiring with PromptRegistry, AI Client, and Translator."""
    mock_output = CarrierSummaryOutput(
        summary="Maersk announced port congestion surcharge on US-EU route.",
        affected_lanes=["US-EU"],
        impact_severity="medium",
    )
    mock_ai_client.generate_structured.return_value = mock_output

    summarizer = CarrierSummarizer(ai_client=mock_ai_client, translator=mock_translator)
    result = await summarizer.summarize("Maersk", "Surcharge Advisory", "Effective Sept 1 surcharge applies.")

    assert result.summary == mock_output.summary
    assert result.impact_severity == "medium"

    mock_ai_client.generate_structured.assert_called_once()
    call_kwargs = mock_ai_client.generate_structured.call_args.kwargs

    # Assert prompt prompt_version v1 was fetched and passed
    assert call_kwargs["feature_name"] == "carrier_advisory_summary"
    assert call_kwargs["prompt_version"] == "v1"
    assert "Surcharge Advisory" in call_kwargs["user_content"]


@pytest.mark.asyncio
async def test_rate_outlook_narrator_e2e_wiring(mock_ai_client):
    """Verify RateOutlookNarrator wiring with PromptRegistry and AI Client."""
    mock_output = RateOutlookOutput(
        outlook_text="Rates on US-APAC route are expected to rise due to peak season demand and capacity limits.",
        recommendation="book_now",
        confidence=90,
    )
    mock_ai_client.generate_structured.return_value = mock_output

    narrator = RateOutlookNarrator(ai_client=mock_ai_client)
    result = await narrator.narrate("US-APAC", "2200 USD on 2026-08-15", "7d avg 2100", "High demand")

    assert result.recommendation == "book_now"
    assert result.confidence == 90

    mock_ai_client.generate_structured.assert_called_once()
    call_kwargs = mock_ai_client.generate_structured.call_args.kwargs
    assert call_kwargs["feature_name"] == "rate_outlook_narrator"
    assert call_kwargs["prompt_version"] == "v1"


@pytest.mark.asyncio
async def test_route_brief_generator_e2e_wiring(mock_ai_client):
    """Verify RouteBriefGenerator wiring with PromptRegistry and AI Client."""
    mock_output = RouteBriefOutput(
        brief_markdown="# Route Brief NYC to LON\n\nCurrent conditions are clear with low congestion at port of origin and no reported carrier advisories.",
        recommendation="ship_now",
        risk_level="low",
    )
    mock_ai_client.generate_structured.return_value = mock_output

    generator = RouteBriefGenerator(ai_client=mock_ai_client)
    result = await generator.generate_brief("NYC", "LON", "Maersk", "None", "Clear weather")

    assert result.recommendation == "ship_now"
    assert result.risk_level == "low"

    mock_ai_client.generate_structured.assert_called_once()
    call_kwargs = mock_ai_client.generate_structured.call_args.kwargs
    assert call_kwargs["feature_name"] == "route_brief"
    assert call_kwargs["prompt_version"] == "v1"


def test_health_check_endpoints_do_not_invoke_llm():
    """Verify GET /api/v1/health and GET /api/v1/ai/health do NOT invoke OpenAI API."""
    client = TestClient(app)

    mock_user = MagicMock(spec=User)
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock()
    mock_db.scalar = AsyncMock(return_value=None)

    from app.database import get_db
    mock_user.is_admin = True
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_current_admin_user] = lambda: mock_user
    app.dependency_overrides[RateLimiter] = lambda: None
    app.dependency_overrides[get_db] = lambda: mock_db


    try:
        with patch("openai.resources.chat.completions.Completions.create") as mock_openai_create:
            # 1. Test core health check
            res_core = client.get("/api/v1/health")
            assert res_core.status_code == 200

            # 2. Test AI admin health check
            res_ai = client.get("/api/v1/ai/health")
            assert res_ai.status_code == 200
            data = res_ai.json()

            assert data["provider"] == "openai"
            assert data["model"] == settings.AI_MODEL
            assert "active_prompts" in data
            assert data["active_prompts"]["carrier_summarizer"] == "v1"

            # Assert OpenAI API completion creation was NEVER called
            mock_openai_create.assert_not_called()

    finally:
        app.dependency_overrides.clear()



@pytest.mark.asyncio
async def test_failure_isolation_between_components(mock_ai_client, mock_translator):
    """Verify failure in one feature (e.g. rate outlook timeout) is isolated from other AI components."""
    # 1. Rate outlook fails with timeout
    mock_ai_client.generate_structured.side_effect = AITimeoutError("OpenAI API timed out")
    narrator = RateOutlookNarrator(ai_client=mock_ai_client)

    with pytest.raises(AITimeoutError):
        await narrator.narrate("US-EU", "2000 USD", "Context", "Factors")

    # 2. CarrierSummarizer succeeds independently
    mock_ai_client.generate_structured.side_effect = None
    mock_output = CarrierSummaryOutput(
        summary="Carrier advisory summary succeeds after rate outlook failure.",
        affected_lanes=["US-EU"],
        impact_severity="low",
    )
    mock_ai_client.generate_structured.return_value = mock_output

    summarizer = CarrierSummarizer(ai_client=mock_ai_client, translator=mock_translator)
    summary_result = await summarizer.summarize("Carrier A", "Title", "Advisory text")

    assert summary_result.summary == mock_output.summary


def test_prompts_endpoint_hides_raw_system_prompts():
    """Verify GET /api/v1/ai/prompts returns feature metadata without exposing raw system prompts."""
    client = TestClient(app)
    mock_user = MagicMock(spec=User)
    mock_user.is_admin = True
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_current_admin_user] = lambda: mock_user
    app.dependency_overrides[RateLimiter] = lambda: None


    try:
        res = client.get("/api/v1/ai/prompts")
        assert res.status_code == 200
        data = res.json()

        assert "features" in data
        feats = data["features"]

        for feat in ["carrier_summarizer", "rate_outlook", "route_brief"]:
            assert feat in feats
            assert feats[feat]["active_version"] == "v1"
            assert "available_versions" in feats[feat]

        # Verify raw system prompt keywords are nowhere in response text
        body_text = res.text
        assert "SYSTEM_PROMPT" not in body_text
        assert "CRITICAL RULES:" not in body_text
        assert "Respond ONLY with valid JSON" not in body_text

    finally:
        app.dependency_overrides.clear()
