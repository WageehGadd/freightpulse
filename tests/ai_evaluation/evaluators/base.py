import json
import pathlib
from typing import Any, List
from pydantic import ValidationError


def load_fixture(path: pathlib.Path) -> dict:
    """Load a JSON fixture file and return its dictionary representation."""
    with path.open() as f:
        return json.load(f)


def validate_schema(result: Any, schema: type) -> None:
    """Validate that *result* conforms to the provided *schema*.
    Raises ValidationError on failure.
    """
    # Use model_dump for Pydantic v2 compatibility
    schema.model_validate(result.model_dump())


def run_criteria(result: Any, criteria: dict) -> List[str]:
    """Run simple deterministic criteria against the result.
    Returns a list of failure messages; empty list means pass.
    """
    failures: List[str] = []
    if criteria.get("must_have_summary"):
        # Enforce summary presence only if model has a summary attribute
        if hasattr(result, "summary"):
            if not getattr(result, "summary", None):
                failures.append("summary missing")
        # Only check brief_markdown if the attribute exists on the model
        if hasattr(result, "brief_markdown") and not getattr(result, "brief_markdown", None):
            failures.append("brief_markdown missing")
        # Only check outlook_text if the attribute exists on the model
        if hasattr(result, "outlook_text") and not getattr(result, "outlook_text", None):
            failures.append("outlook_text missing")
        # Fail if summary attribute is missing or empty
        if not hasattr(result, "summary"):
            failures.append("summary missing")
        elif not getattr(result, "summary", None):
            failures.append("summary missing")
        # Only check brief_markdown if the attribute exists on the model
        if hasattr(result, "brief_markdown") and not getattr(result, "brief_markdown", None):
            failures.append("brief_markdown missing")
        # Only check outlook_text if the attribute exists on the model
        if hasattr(result, "outlook_text") and not getattr(result, "outlook_text", None):
            failures.append("outlook_text missing")
        # Only enforce summary presence if the model actually has a summary attribute
        if hasattr(result, "summary"):
            if not getattr(result, "summary", None):
                failures.append("summary missing")
        # Only check brief_markdown if the attribute exists on the model
        if hasattr(result, "brief_markdown") and not getattr(result, "brief_markdown", None):
            failures.append("brief_markdown missing")
        # Only check outlook_text if the attribute exists on the model
        if hasattr(result, "outlook_text") and not getattr(result, "outlook_text", None):
            failures.append("outlook_text missing")
    if "allowed_severities" in criteria:
        sev = getattr(result, "impact_severity", None)
        if sev not in criteria["allowed_severities"]:
            failures.append(f"impact_severity '{sev}' not allowed")
    if "allowed_recommendations" in criteria:
        rec = getattr(result, "recommendation", None)
        if rec not in criteria["allowed_recommendations"]:
            failures.append(f"recommendation '{rec}' not allowed")
    if "confidence_range" in criteria:
        conf = getattr(result, "confidence", None)
        low, high = criteria["confidence_range"]
        if conf is None or not (low <= conf <= high):
            failures.append(f"confidence {conf} outside {low}-{high}")
    return failures
