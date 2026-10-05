"""Frozen hypothetical contracts, deliberately distinct from current forecasts."""
from datetime import datetime
from decimal import Context, Decimal, ROUND_HALF_EVEN, localcontext
from enum import Enum
import re
from typing import Annotated, Literal

from pydantic import Field, StrictBool, field_validator

from app.schemas.decision import Decision, DecisionResult, Frozen, Movement, Reason, SeriesIdentity
from app.schemas.reliability import EvidenceAssessment

METHODOLOGY_VERSION = "scenario-intelligence-v1"
CENT = Decimal("0.01")
MAX_RATE = Decimal("9999999999.99")  # T06 NUMERIC(12,2), not an economic limit.
MAX_NUMERIC_DIGITS = 28  # Bounded input representation for the fixed context.
DECIMAL_TEXT = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z")


def decimal_input(value):
    """No float/bool coercion; bound representation before Decimal arithmetic."""
    if type(value) is str:
        if len(value) > 64 or not DECIMAL_TEXT.fullmatch(value):
            raise ValueError("Numeric text must be bounded ASCII decimal notation")
        with localcontext(Context(prec=28, rounding=ROUND_HALF_EVEN)):
            try:
                value = Decimal(value)
            except ArithmeticError as exc:
                raise ValueError("Invalid Decimal") from exc
    if type(value) is not Decimal or not value.is_finite():
        raise ValueError("A finite Decimal or decimal string is required")
    parts = value.as_tuple()
    if len(parts.digits) > MAX_NUMERIC_DIGITS or abs(parts.exponent) > MAX_NUMERIC_DIGITS:
        raise ValueError("Numeric representation exceeds the precision/exponent budget")
    return value


def money(value):
    value = decimal_input(value)
    with localcontext(Context(prec=28, rounding=ROUND_HALF_EVEN)):
        if value <= 0 or value > MAX_RATE or value != value.quantize(CENT):
            raise ValueError("Rate must be positive, cent-representable and fit NUMERIC(12,2)")
    return value


class AssumptionType(str, Enum):
    ABSOLUTE_PREDICTED_RATE = "ABSOLUTE_PREDICTED_RATE"
    PERCENTAGE_ADJUSTMENT = "PERCENTAGE_ADJUSTMENT"


class AbsoluteRate(Frozen):
    type: Literal["ABSOLUTE_PREDICTED_RATE"] = "ABSOLUTE_PREDICTED_RATE"
    requested_value: Decimal

    _money = field_validator("requested_value", mode="before")(money)


class PercentageAdjustment(Frozen):
    type: Literal["PERCENTAGE_ADJUSTMENT"] = "PERCENTAGE_ADJUSTMENT"
    requested_value: Decimal

    _decimal = field_validator("requested_value", mode="before")(decimal_input)


Assumption = Annotated[AbsoluteRate | PercentageAdjustment, Field(discriminator="type")]


class ScenarioRequest(Frozen):
    category: Literal["MARKET_WHAT_IF"] = "MARKET_WHAT_IF"
    assumption: Assumption


class AppliedAssumption(Frozen):
    provenance: Literal["USER_SUPPLIED_HYPOTHETICAL"] = "USER_SUPPLIED_HYPOTHETICAL"
    requested: Assumption
    applied_predicted_rate: Decimal


class ScenarioComparison(Frozen):
    predicted_rate_delta: Decimal
    predicted_rate_delta_pct: Decimal
    baseline_movement: Movement
    hypothetical_movement: Movement
    baseline_decision: Decision
    hypothetical_decision: Decision
    decision_changed: StrictBool
    baseline_rule_actionable: StrictBool
    hypothetical_rule_actionable: StrictBool
    rule_actionability_changed: StrictBool
    added_hard_blockers: tuple[Reason, ...]
    removed_hard_blockers: tuple[Reason, ...]


class ScenarioResult(Frozen):
    methodology_version: Literal["scenario-intelligence-v1"] = METHODOLOGY_VERSION
    category: Literal["MARKET_WHAT_IF"] = "MARKET_WHAT_IF"
    series: SeriesIdentity
    evaluated_at: datetime
    baseline_predicted_rate: Decimal
    # Assessment contains the complete factual T08 result/input without duplicating it.
    baseline_evidence: EvidenceAssessment
    assumption: AppliedAssumption
    # Nested T08 actionability is hypothetical rule actionability, never live advice.
    hypothetical_t08_result: DecisionResult
    comparison: ScenarioComparison
    hypothetical: Literal[True] = True
    non_operational: Literal[True] = True
    live_actionable: Literal[False] = False
    analytical_only: StrictBool
    limitations: tuple[str, ...]
    baseline_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    scenario_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
