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
def test_live_carrier_summarizer():
    if os.getenv("FREIGHTPULSE_ENABLE_LIVE_AI") != "1":
        pytest.skip("Live AI tests are disabled")
    # Use a realistic real input (could be derived from a fixture)
    input_data = {"carrier": "Carrier A", "title": "Summary", "advisory_text": "Advisory"}
    summarizer = CarrierSummarizer()
    result = summarizer.generate_structured(**input_data)
    assert result is not None

@pytest.mark.ai_live
def test_live_rate_outlook():
    if os.getenv("FREIGHTPULSE_ENABLE_LIVE_AI") != "1":
        pytest.skip("Live AI tests are disabled")
    input_data = {"lane": "US-APAC", "date": "2024-01-01"}
    narrator = RateOutlookNarrator()
    result = narrator.generate_structured(**input_data)
    assert result is not None

@pytest.mark.ai_live
def test_live_route_brief():
    if os.getenv("FREIGHTPULSE_ENABLE_LIVE_AI") != "1":
        pytest.skip("Live AI tests are disabled")
    input_data = {
        "origin": "NYC",
        "destination": "LON",
        "carrier": "Carrier X",
        "advisories": "None",
        "conditions": "Clear",
    }
    generator = RouteBriefGenerator()
    result = generator.generate_structured(**input_data)
    assert result is not None
