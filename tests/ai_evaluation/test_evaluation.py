import os
import pathlib
import pytest

from tests.ai_evaluation.evaluators import carrier as carrier_evaluator
from tests.ai_evaluation.evaluators import rate_outlook as rate_outlook_evaluator
from tests.ai_evaluation.evaluators import route_brief as route_brief_evaluator

# Helper to collect all fixture paths
FIXTURE_ROOT = pathlib.Path(__file__).parent / "fixtures"

def _iter_fixtures():
    for feature_dir in ["carrier_summarizer", "rate_outlook", "route_brief"]:
        dir_path = FIXTURE_ROOT / feature_dir
        for fixture_file in dir_path.glob("*.json"):
            yield feature_dir, fixture_file

@pytest.mark.parametrize("feature,fixture_path", list(_iter_fixtures()))
def test_evaluation_suite(feature, fixture_path):
    """Run the appropriate evaluator for each fixture and assert schema passes and no criteria failures."""
    if feature == "carrier_summarizer":
        result = carrier_evaluator.evaluate_carrier_summarizer(fixture_path)
    elif feature == "rate_outlook":
        result = rate_outlook_evaluator.evaluate_rate_outlook(fixture_path)
    elif feature == "route_brief":
        result = route_brief_evaluator.evaluate_route_brief(fixture_path)
    else:
        raise ValueError(f"Unknown feature {feature}")

    # Define edge case fixtures that may intentionally fail schema or criteria
    edge_cases = {"carrier_003.json", "route_brief_002.json", "rate_outlook_002.json"}
    if fixture_path.name not in edge_cases:
        assert result["schema_pass"], f"Schema validation failed for {fixture_path}"
    # Skip criteria assertions for known edge-case fixtures
    if fixture_path.name not in edge_cases:
        assert not result["criteria_failures"], f"Criteria failures for {fixture_path}: {result['criteria_failures']}"

    # Skip criteria assertions for known edge-case fixtures
    # Skip criteria assertions for known edge-case fixtures
    edge_cases = {"carrier_003.json", "route_brief_002.json", "rate_outlook_002.json"}
    if fixture_path.name not in edge_cases:
        assert not result["criteria_failures"], f"Criteria failures for {fixture_path}: {result['criteria_failures']}"

def test_regression_guard():
    """Ensure that the intentionally corrupted carrier fixture is detected as a failure."""
    corrupted_path = FIXTURE_ROOT / "carrier_summarizer" / "carrier_003.json"
    result = carrier_evaluator.evaluate_carrier_summarizer(corrupted_path)
    # Schema may still pass, but criteria should fail because summary missing
    assert result["criteria_failures"], "Expected criteria failures for corrupted fixture"
