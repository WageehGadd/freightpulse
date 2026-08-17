import json
import pathlib
from typing import Any

from .base import load_fixture, validate_schema, run_criteria
from app.schemas.ai_outputs import RateOutlookOutput


def evaluate_rate_outlook(fixture_path: pathlib.Path) -> dict:
    """Evaluate a Rate Outlook fixture.

    Returns a dict with keys: 'schema_pass', 'criteria_failures', 'output'.
    """
    data = load_fixture(fixture_path)
    expected = data.get("expected_output")
    criteria = data.get("criteria", {})

    # Directly use the expected output for evaluation (deterministic).
    result_model = RateOutlookOutput.model_validate(expected)
    schema_pass = True
    try:
        validate_schema(result_model, RateOutlookOutput)
    except Exception:
        schema_pass = False

    failures = run_criteria(result_model, criteria)

    return {
        "schema_pass": schema_pass,
        "criteria_failures": failures,
        "output": result_model,
    }
