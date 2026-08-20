# %% [markdown]
# # Prompt Regression Test Suite
# Ties together the AIEvalHarness and Prompt Manager to test LLM outputs against golden datasets.

# %%
import sys
import os

# Add root directory to python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from pydantic import BaseModel, Field
from typing import Literal
from tests.ai_eval.eval_framework import AIEvalHarness, GoldenTestCase
from ai.prompts.prompt_manager import get_prompt_version

# %%
# 1. Define the Expected Schema for the Route Brief
class RouteBriefSchema(BaseModel):
    """Schema for AI-4: Route Intelligence Brief."""
    brief_markdown: str
    recommendation: Literal["ship_now", "wait", "reroute"]
    risk_level: Literal["low", "medium", "high"]

# %%
# 2. Initialize the Evaluation Harness and load the Prompt
harness = AIEvalHarness()

# Dynamically load the prompt version we want to test
prompt_v1 = get_prompt_version("route_brief", "v1")

# %%
# 3. Create a Mock LLM Generator (Simulating the future OpenAI client)
# In production, this function will send 'prompt_v1' and 'input_data' to GPT-4o-mini
def mock_llm_call(input_data: dict) -> dict:
    """
    Simulates the LLM returning a structured JSON response.
    Here we simulate a perfect response that respects the schema.
    """
    return {
        "brief_markdown": f"## Brief for {input_data['origin']} to {input_data['destination']}\nRates are stable.",
        "recommendation": "ship_now",
        "risk_level": "low"
    }

# %%
# 4. Define the Golden Test Case (The baseline data we use to test the prompt)
regression_test = GoldenTestCase(
    name="Route Brief v1 - Baseline Regression Test",
    input_data={
        "origin": "Shanghai", 
        "destination": "Europe",
        "cargo_type": "40ft",
        "date": "2026-08-09",
        "current_rate": 1500,
        "change_7d_pct": 1.0,
        "change_30d_pct": 0.5,
        "trend": "stable"
    },
    expected_schema=RouteBriefSchema,
    required_fields=["brief_markdown", "recommendation", "risk_level"],
    enum_constraints={
        "recommendation": ["ship_now", "wait", "reroute"],
        "risk_level": ["low", "medium", "high"]
    }
)

def test_route_brief_prompt_regression():
    # Run the test using our harness
    result = harness.run_golden_test("AI-4 Route Brief (v1)", regression_test, mock_llm_call)
    
    assert result.passed is True, "Prompt regression test failed"
    assert result.checks["schema_valid"] is True
    assert result.checks["fields_present"] is True
    assert result.checks["enums_valid"] is True