import os
import pathlib
import pytest

from tests.ai_evaluation.fake_ai_client import FakeFreightPulseAIClient
from app.ai.carrier_summarizer import CarrierSummarizer
from app.ai.rate_outlook_narrator import RateOutlookNarrator
from app.ai.route_brief_generator import RouteBriefGenerator

# This test is marked as "ai_live" and will be skipped unless the environment variable
# FREIGHTPULSE_ENABLE_LIVE_AI=1 is set. It demonstrates how the real LLM would be invoked.

@pytest.mark.ai_live
@pytest.mark.asyncio
async def test_live_carrier_summarizer():
    if os.getenv("FREIGHTPULSE_ENABLE_LIVE_AI") != "1" or not os.getenv("OPENAI_API_KEY"):
        pytest.skip("Live AI tests are disabled or OPENAI_API_KEY is not set")
    summarizer = CarrierSummarizer()
    result = await summarizer.summarize(
        carrier="Carrier A",
        title="Port Congestion Advisory",
        advisory_text="Effective Sept 1 a surcharge of $200 per TEU applies due to port congestion.",
    )
    assert result is not None
    assert result.summary


@pytest.mark.ai_live
@pytest.mark.asyncio
async def test_live_rate_outlook():
    if os.getenv("FREIGHTPULSE_ENABLE_LIVE_AI") != "1" or not os.getenv("OPENAI_API_KEY"):
        pytest.skip("Live AI tests are disabled or OPENAI_API_KEY is not set")
    narrator = RateOutlookNarrator()
    result = await narrator.narrate(
        lane="Shanghai-Rotterdam",
        current_rate="2200 USD on 2026-08-15",
        historical_context="7d avg 2100 USD, 30d avg 1950 USD, trend rising (+5.1% per week)",
        market_factors="Peak season demand surge and Red Sea rerouting",
    )
    assert result is not None
    assert result.outlook_text


@pytest.mark.ai_live
@pytest.mark.asyncio
async def test_live_route_brief():
    if os.getenv("FREIGHTPULSE_ENABLE_LIVE_AI") != "1" or not os.getenv("OPENAI_API_KEY"):
        pytest.skip("Live AI tests are disabled or OPENAI_API_KEY is not set")
    generator = RouteBriefGenerator()
    result = await generator.generate_brief(
        origin="Shanghai",
        destination="Rotterdam",
        carrier="Maersk",
        advisories="Port congestion surcharge $200/TEU effective Sept 1.",
        conditions="Clear weather at origin; 3-day dwell time at destination port.",
    )
    assert result is not None
    assert result.brief_markdown
