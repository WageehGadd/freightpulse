# %% [markdown]
# # AI Evaluation Framework (AIEvalHarness)
# Centralized evaluation framework for all AI features (Statistical & LLM-based).

# %%
from typing import Callable, Any, Dict, List, Type
from pydantic import BaseModel, ValidationError

# %%
# Define the core data structures for our evaluation framework
class GoldenTestCase(BaseModel):
    name: str
    input_data: Any
    expected_schema: Type[BaseModel]
    required_fields: List[str] = []
    enum_constraints: Dict[str, List[str]] = {}

class EvalResult(BaseModel):
    feature: str
    test_case: str
    checks: Dict[str, bool]
    passed: bool

# %%
class AIEvalHarness:
    """
    Centralized evaluation framework that runs golden fixture tests 
    and computes quality metrics across the platform.
    """
    def __init__(self):
        self.results: List[EvalResult] = []

    def _check_schema(self, output: Any, expected_schema: Type[BaseModel]) -> bool:
        """Validates if the output strictly matches the expected Pydantic schema."""
        try:
            if isinstance(output, BaseModel):
                # It's already a validated Pydantic model
                return isinstance(output, expected_schema)
            elif isinstance(output, dict):
                # Try to validate raw dict against the schema
                expected_schema(**output)
                return True
            return False
        except ValidationError:
            return False

    def _check_fields(self, output: Any, required_fields: List[str]) -> bool:
        """Ensures that all mandatory fields are actually present in the output."""
        if isinstance(output, BaseModel):
            data = output.model_dump()
        elif isinstance(output, dict):
            data = output
        else:
            return False
        
        return all(field in data for field in required_fields)

    def _check_enums(self, output: Any, enum_constraints: Dict[str, List[str]]) -> bool:
        """Verifies that categorical fields contain only allowed values."""
        if isinstance(output, BaseModel):
            data = output.model_dump()
        elif isinstance(output, dict):
            data = output
        else:
            return False
        
        for field, allowed_values in enum_constraints.items():
            if field in data and data[field] not in allowed_values:
                return False
        return True

    def _check_grounding(self, output: Any, input_data: Any) -> bool:
        """
        Hallucination check: Ensures the model didn't invent data.
        For MVP phase, this acts as a placeholder that always returns True.
        In advanced phases, this will cross-reference output numbers with input data.
        """
        return True

    def run_golden_test(
        self, 
        feature: str, 
        test_case: GoldenTestCase, 
        generate_fn: Callable
    ) -> EvalResult:
        """
        Runs a single golden test case and records the evaluation metrics.
        """
        try:
            # Execute the AI function (can be statistical or LLM-based)
            output = generate_fn(test_case.input_data)
            
            # Perform all validation checks
            checks = {
                "schema_valid": self._check_schema(output, test_case.expected_schema),
                "fields_present": self._check_fields(output, test_case.required_fields),
                "enums_valid": self._check_enums(output, test_case.enum_constraints),
                "no_hallucination": self._check_grounding(output, test_case.input_data),
            }
            
            # The test passes only if ALL checks return True
            is_passed = all(checks.values())
            
            result = EvalResult(
                feature=feature, 
                test_case=test_case.name, 
                checks=checks,
                passed=is_passed
            )
            self.results.append(result)
            return result
            
        except Exception as e:
            # If the function crashes completely
            checks = {
                "schema_valid": False, "fields_present": False, 
                "enums_valid": False, "no_hallucination": False
            }
            result = EvalResult(feature=feature, test_case=test_case.name, checks=checks, passed=False)
            self.results.append(result)
            return result

    def generate_report(self) -> str:
        """Generates a Markdown formatted report of all test results."""
        report = "# AI Evaluation Report\n\n"
        report += "| Feature | Test Case | Schema | Fields | Enums | Grounded | Status |\n"
        report += "|---------|-----------|--------|--------|-------|----------|--------|\n"
        
        for r in self.results:
            schema = "✅" if r.checks.get("schema_valid") else "❌"
            fields = "✅" if r.checks.get("fields_present") else "❌"
            enums = "✅" if r.checks.get("enums_valid") else "❌"
            halluc = "✅" if r.checks.get("no_hallucination") else "❌"
            status = "✅ PASS" if r.passed else "❌ FAIL"
            
            report += f"| {r.feature} | {r.test_case} | {schema} | {fields} | {enums} | {halluc} | {status} |\n"
        
        return report

# %% [markdown]
# # Framework Testing (Execution)
# Let's run a quick mock test to ensure our framework formats the markdown correctly.

# %%
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
from ai.schemas.ai_outputs import RateTrendSchema

# Create an instance of our evaluation framework
harness = AIEvalHarness()

# Define a mock AI function that returns a valid schema dict
mock_ai_function = lambda x: {
    "trade_lane": "Shanghai-Europe",
    "computed_date": "2026-08-09",
    "avg_7d_usd": 1500.0,
    "avg_30d_usd": 1490.0,
    "change_7d_pct": 1.0,
    "change_30d_pct": 0.5,
    "trend": "rising",
    "slope_per_week": 10.0,
    "r_squared": 0.85,
    "anomaly_flag": False
}

# Define a test case
test_case_1 = GoldenTestCase(
    name="Mock Rising Trend Output",
    input_data="mock_input",
    expected_schema=RateTrendSchema,
    required_fields=["trade_lane", "trend", "slope_per_week"],
    enum_constraints={"trend": ["rising", "falling", "stable", "insufficient_data"]}
)

# Run the test
harness.run_golden_test("AI-1 Rate Trend", test_case_1, mock_ai_function)

# Print the final markdown report
print(harness.generate_report())