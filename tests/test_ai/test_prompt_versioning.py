import logging
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.ai.carrier_summarizer import CarrierSummarizer
from app.ai.openai_client import FreightPulseAIClient
from app.ai.prompts import (
    PromptRegistry,
    PromptTemplate,
    PromptVersionNotFoundError,
    carrier_summary_v1,
    get_prompt,
    rate_outlook_v1,
    registry,
    route_brief_v1,
)
from app.ai.rate_outlook_narrator import RateOutlookNarrator
from app.ai.route_brief_generator import RouteBriefGenerator
from app.ai.translator import CarrierTranslator
from app.config import settings
from app.schemas.ai_outputs import (
    CarrierSummaryOutput,
    RateOutlookOutput,
    RouteBriefOutput,
)


def test_baseline_v1_prompts_resolved_correctly():
    """Verify v1 prompts resolve for all features with expected baseline prompts."""
    carrier_p = get_prompt("carrier_summarizer", "v1")
    assert carrier_p.version == "v1"
    assert carrier_p.system_prompt == carrier_summary_v1.SYSTEM_PROMPT
    assert carrier_p.user_template == carrier_summary_v1.USER_TEMPLATE

    rate_p = get_prompt("rate_outlook", "v1")
    assert rate_p.version == "v1"
    assert rate_p.system_prompt == rate_outlook_v1.SYSTEM_PROMPT
    assert rate_p.user_template == rate_outlook_v1.USER_TEMPLATE

    route_p = get_prompt("route_brief", "v1")
    assert route_p.version == "v1"
    assert route_p.system_prompt == route_brief_v1.SYSTEM_PROMPT
    assert route_p.user_template == route_brief_v1.USER_TEMPLATE


def test_unknown_version_raises_prompt_version_not_found():
    """Verify that requesting an unknown version raises PromptVersionNotFoundError."""
    with pytest.raises(PromptVersionNotFoundError, match="Prompt version 'v999' not found"):
        get_prompt("carrier_summarizer", "v999")

    with pytest.raises(PromptVersionNotFoundError, match="No prompts registered for feature 'unknown_feature'"):
        get_prompt("unknown_feature", "v1")


def test_list_versions():
    """Verify list_versions returns registered versions for features."""
    assert "v1" in registry.list_versions("carrier_summarizer")
    assert "v1" in registry.list_versions("rate_outlook")
    assert "v1" in registry.list_versions("route_brief")
    assert registry.list_versions("non_existent_feature") == []


def test_feature_prompt_isolation():
    """Verify features cannot accidentally resolve prompts registered to another feature."""
    custom_reg = PromptRegistry()
    custom_reg.register("feat_a", "v1", PromptTemplate("v1", "Sys A", "User A"))
    custom_reg.register("feat_b", "v2", PromptTemplate("v2", "Sys B", "User B"))

    assert custom_reg.get_prompt("feat_a", "v1").system_prompt == "Sys A"
    with pytest.raises(PromptVersionNotFoundError):
        custom_reg.get_prompt("feat_a", "v2")

    with pytest.raises(PromptVersionNotFoundError):
        custom_reg.get_prompt("feat_b", "v1")


def test_explicit_version_overrides_configuration():
    """Verify that passing explicit prompt_version overrides configuration settings."""
    custom_reg = PromptRegistry()
    custom_reg.register("carrier_summarizer", "v1", PromptTemplate("v1", "System V1", "User V1"))
    custom_reg.register("carrier_summarizer", "v2", PromptTemplate("v2", "System V2", "User V2"))

    with patch("app.ai.prompts.registry.registry", custom_reg):
        # With active setting = v1, explicit v2 should fetch v2
        p2 = get_prompt("carrier_summarizer", "v2")
        assert p2.version == "v2"
        assert p2.system_prompt == "System V2"


def test_configuration_controls_default_version():
    """Verify active settings determine default version when version parameter is None."""
    custom_reg = PromptRegistry()
    custom_reg.register("carrier_summarizer", "v1", PromptTemplate("v1", "Sys 1", "User 1"))
    custom_reg.register("carrier_summarizer", "v2", PromptTemplate("v2", "Sys 2", "User 2"))

    with patch("app.ai.prompts.registry.registry", custom_reg):
        with patch.object(settings, "AI_CARRIER_SUMMARIZER_PROMPT_VERSION", "v2"):
            resolved = get_prompt("carrier_summarizer", None)
            assert resolved.version == "v2"
            assert resolved.system_prompt == "Sys 2"


@pytest.mark.asyncio
async def test_carrier_summarizer_uses_registry_selected_prompt():
    """Verify CarrierSummarizer uses prompt resolved from registry and passes version to AI client."""
    mock_ai_client = MagicMock(spec=FreightPulseAIClient)
    mock_ai_client.generate_structured = AsyncMock()
    mock_ai_client.generate_structured.return_value = CarrierSummaryOutput(
        summary="Summary test", affected_lanes=["US-EU"], impact_severity="low"
    )

    mock_translator = MagicMock(spec=CarrierTranslator)
    mock_translator.detect_language.return_value = "en"

    custom_reg = PromptRegistry()
    custom_reg.register("carrier_summarizer", "v2", PromptTemplate("v2", "Custom System V2", "Custom User V2: {carrier} - {title} - {advisory_text}"))

    with patch("app.ai.prompts.registry.registry", custom_reg):
        summarizer = CarrierSummarizer(mock_ai_client, mock_translator, prompt_version="v2")
        result = await summarizer.summarize("Carrier X", "Title X", "Advisory text X")

        assert result.summary == "Summary test"
        mock_ai_client.generate_structured.assert_called_once()
        call_kwargs = mock_ai_client.generate_structured.call_args.kwargs

        assert call_kwargs["system_prompt"] == "Custom System V2"
        assert "Custom User V2:" in call_kwargs["user_content"]
        assert call_kwargs["prompt_version"] == "v2"


@pytest.mark.asyncio
async def test_rate_outlook_narrator_uses_registry_selected_prompt():
    """Verify RateOutlookNarrator resolves prompt via registry."""
    mock_ai_client = MagicMock(spec=FreightPulseAIClient)
    mock_ai_client.generate_structured = AsyncMock()
    mock_ai_client.generate_structured.return_value = RateOutlookOutput(
        outlook_text="This is a sufficiently long freight rate outlook text that satisfies min_length requirements.", recommendation="book_now", confidence=85
    )

    custom_reg = PromptRegistry()
    custom_reg.register(
        "rate_outlook",
        "v2",
        PromptTemplate("v2", "Rate Sys V2", "Lane: {lane}, Rate: {current_rate}, Hist: {historical_context}, Mkt: {market_factors}"),
    )

    with patch("app.ai.prompts.registry.registry", custom_reg):
        narrator = RateOutlookNarrator(mock_ai_client, prompt_version="v2")
        result = await narrator.narrate("US-EU", "2000 USD", "Hist context", "Market context")

        assert result.recommendation == "book_now"
        mock_ai_client.generate_structured.assert_called_once()
        call_kwargs = mock_ai_client.generate_structured.call_args.kwargs

        assert call_kwargs["system_prompt"] == "Rate Sys V2"
        assert call_kwargs["prompt_version"] == "v2"


@pytest.mark.asyncio
async def test_route_brief_generator_uses_registry_selected_prompt():
    """Verify RouteBriefGenerator resolves prompt via registry."""
    mock_ai_client = MagicMock(spec=FreightPulseAIClient)
    mock_ai_client.generate_structured = AsyncMock()
    mock_ai_client.generate_structured.return_value = RouteBriefOutput(
        brief_markdown="# Route Brief Summary\n\nThis is a sufficiently long route brief markdown document that exceeds the minimum required length of 100 characters for validation.", recommendation="ship_now", risk_level="low"
    )

    custom_reg = PromptRegistry()
    custom_reg.register(
        "route_brief",
        "v2",
        PromptTemplate("v2", "Route Sys V2", "O: {origin}, D: {destination}, C: {carrier}, Adv: {advisories}, Cond: {conditions}"),
    )

    with patch("app.ai.prompts.registry.registry", custom_reg):
        generator = RouteBriefGenerator(mock_ai_client, prompt_version="v2")
        result = await generator.generate_brief("NYC", "LON", "Carrier Y", "Advisories", "Conditions")

        assert result.recommendation == "ship_now"
        mock_ai_client.generate_structured.assert_called_once()
        call_kwargs = mock_ai_client.generate_structured.call_args.kwargs

        assert call_kwargs["system_prompt"] == "Route Sys V2"
        assert call_kwargs["prompt_version"] == "v2"



def test_ai_client_configuration_precedence():
    """Verify precedence for AI client model parameters: explicit arg > settings > default."""
    # Default settings
    client_default = FreightPulseAIClient(api_key="test-key")
    assert client_default.model == settings.AI_MODEL
    assert client_default.temperature == settings.AI_TEMPERATURE
    assert client_default.max_tokens == settings.AI_MAX_TOKENS

    # Explicit constructor args take top precedence
    client_explicit = FreightPulseAIClient(
        api_key="test-key",
        model="gpt-4o",
        temperature=0.7,
        max_tokens=2000,
    )
    assert client_explicit.model == "gpt-4o"
    assert client_explicit.temperature == 0.7
    assert client_explicit.max_tokens == 2000


def test_ai_client_logging_includes_prompt_version(caplog):
    """Verify structured logger outputs prompt_version when logging usage."""
    client = FreightPulseAIClient(api_key="test-key")
    usage_mock = MagicMock()
    usage_mock.prompt_tokens = 100
    usage_mock.completion_tokens = 50

    with caplog.at_level(logging.INFO):
        client._log_usage(usage_mock, "carrier_summarizer", "gpt-4o-mini", prompt_version="v1")

    assert "AI Usage [carrier_summarizer]" in caplog.text
    assert "prompt_version=v1" in caplog.text
    assert "model=gpt-4o-mini" in caplog.text
