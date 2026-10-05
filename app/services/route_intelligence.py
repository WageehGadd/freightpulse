"""Pure composition. Upstream supplies factual provenance; hashes do not verify it."""
from datetime import date, datetime, timezone
from decimal import Decimal, Context, localcontext, ROUND_HALF_EVEN
from enum import Enum
from hashlib import sha256
import json
import math
from types import UnionType
from typing import Union, Literal, get_args, get_origin, get_type_hints
from uuid import UUID
from pydantic import BaseModel
from app.schemas.decision import DecisionPolicy
from app.schemas.route_intelligence import (
    RouteEvidenceRequest, RouteEvidenceResult, Availability, ProvenanceClass,
    EvidenceStatus, AdvisoryContext, OperationalGaps,
)
from app.services.decision_engine import evaluate_decision
from app.services.reliability import assess_evidence


class RouteEvidenceInputError(ValueError):
    """Malformed or contradictory evidence, distinct from valid unavailability."""


def _check(value, annotation):
    """Check raw declared fields before serializers can erase or coerce attacks."""
    origin, args = get_origin(annotation), get_args(annotation)
    if origin in (Union, UnionType):
        for option in args:
            try:
                _check(value, option)
                return
            except RouteEvidenceInputError:
                pass
        raise RouteEvidenceInputError("Wrong union member or primitive type")
    if origin is Literal:
        if not any(type(value) is type(v) and value == v for v in args):
            raise RouteEvidenceInputError("Wrong literal")
    elif origin in (tuple, frozenset):
        if type(value) is not origin:
            raise RouteEvidenceInputError("Mutable or malformed collection")
        for item in value:
            _check(item, args[0])
    elif isinstance(annotation, type) and issubclass(annotation, BaseModel):
        if type(value) is not annotation:
            raise RouteEvidenceInputError("Exact domain model required")
        if set(value.__dict__) != set(annotation.model_fields) or value.model_extra:
            raise RouteEvidenceInputError("Missing or undeclared domain fields")
        hints = get_type_hints(annotation)
        for field in annotation.model_fields:
            _check(value.__dict__[field], hints[field])
    elif type(value) is not annotation:
        raise RouteEvidenceInputError("Wrong primitive type; coercion prohibited")
    if type(value) is datetime and (value.tzinfo is None or value.utcoffset() is None):
        raise RouteEvidenceInputError("Timezone-aware timestamps required")


def _canonical(value):
    if isinstance(value, BaseModel):
        return _canonical(value.model_dump(mode="python"))
    if isinstance(value, Enum):
        return value.value
    if type(value) is datetime:
        return value.astimezone(timezone.utc).isoformat()
    if type(value) is date:
        return value.isoformat()
    if type(value) is UUID:
        return str(value)
    if type(value) is Decimal:
        if not value.is_finite():
            return {"decimal_special": str(value)}
        sign, digits, exponent = value.as_tuple()
        digits = list(digits)
        if not any(digits):
            sign, digits, exponent = 0, [0], 0
        else:
            while digits[-1] == 0:
                digits.pop()
                exponent += 1
        return {"decimal": [sign, "".join(map(str, digits)), exponent]}
    if type(value) is float:
        return {"float": (0.0 if value == 0 else value).hex() if math.isfinite(value) else str(value)}
    if isinstance(value, dict):
        return {k: _canonical(v) for k, v in value.items()}
    if isinstance(value, frozenset):
        return sorted((_canonical(v) for v in value), key=_serialize)
    if isinstance(value, tuple):
        return [_canonical(v) for v in value]
    return value


def _serialize(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def _utc_document(value):
    if type(value) is datetime:
        return value.astimezone(timezone.utc)
    if isinstance(value, dict):
        return {k: _utc_document(v) for k, v in value.items()}
    if isinstance(value, tuple):
        return tuple(_utc_document(v) for v in value)
    return value


def _status(availability, reason):
    return EvidenceStatus(availability=availability, reason=reason)


def compose_route_evidence(request: RouteEvidenceRequest) -> RouteEvidenceResult:
    """No policy override. Exactly one T08/T09 call when factual input is present."""
    try:
        with localcontext(Context(prec=28, rounding=ROUND_HALF_EVEN)):
            return _compose(request)
    except RouteEvidenceInputError:
        raise
    except (ValueError, ArithmeticError) as exc:
        raise RouteEvidenceInputError("Invalid route evidence input") from exc


def _validated_request(request):
    # Only the caller-controlled boundary converts malformed object internals.
    # Unexpected programming errors in evaluators/composition remain visible.
    try:
        _check(request, RouteEvidenceRequest)
        raw = request.model_dump(mode="python")
        validated = RouteEvidenceRequest.model_validate(_utc_document(raw), strict=True)
        if _canonical(raw) != _canonical(validated):
            raise RouteEvidenceInputError("Evidence must not require repair")
        return validated
    except RouteEvidenceInputError:
        raise
    except (ValueError, TypeError, AttributeError, KeyError, ArithmeticError) as exc:
        raise RouteEvidenceInputError("Malformed route evidence boundary") from exc


def _compose(request):
    request = _validated_request(request)
    series, now, factual = request.series, request.evaluated_at, request.decision_input
    decision = assessment = None
    if factual is not None:
        f, s = factual.forecast, factual.current_state
        expected = series.model_dump()
        if f.series.model_dump() != expected or s.series.model_dump() != expected:
            raise RouteEvidenceInputError("Exact series mismatch")
        if s.evaluated_at != now:
            raise RouteEvidenceInputError("State evaluation instant mismatch")
        if f.generated_at > now or (s.latest_forecast_generated_at is not None and s.latest_forecast_generated_at > now):
            raise RouteEvidenceInputError("Future generation evidence")
        if s.stored_live_decision_eligible != f.stored_live_decision_eligible:
            raise RouteEvidenceInputError("Contradictory stored eligibility")
        if s.effective_live_decision_eligible and not s.stored_live_decision_eligible:
            raise RouteEvidenceInputError("Stored ineligibility cannot be promoted")
        decision = evaluate_decision(factual, DecisionPolicy(), now)
        assessment = assess_evidence(decision)
    contexts = []
    # Canonical order also makes semantic validation errors independent of transport order.
    for advisory in sorted(request.advisories, key=lambda a: _serialize(_canonical(a))):
        if advisory.series is not None and advisory.series != series:
            raise RouteEvidenceInputError("Advisory exact series mismatch")
        if any(t is not None and t > now for t in (advisory.published_at, advisory.observed_at)):
            raise RouteEvidenceInputError("Future advisory observation/publication")
        qualified = (advisory.classification == ProvenanceClass.VERIFIED_SOURCE_DATA
                     and advisory.series == series and advisory.source_text is not None
                     and bool(advisory.source_text.strip()) and advisory.source_url is not None
                     and bool(advisory.source_url.strip()))
        contexts.append(AdvisoryContext(snapshot=advisory, status=_status(
            Availability.AVAILABLE if qualified else Availability.EXCLUDED_UNVERIFIED,
            "Qualified source context; upstream verification assertion" if qualified else
            "Not verified exact-series source context; excluded from factual support")))
    # Collapse duplicate transport entries only; retain every distinct snapshot.
    unique = {_serialize(_canonical(c)): c for c in contexts}
    contexts = [unique[key] for key in sorted(unique)]
    conflicts = []
    for record_id in sorted({c.snapshot.record_id for c in contexts}):
        variants = {_serialize(_canonical(c.snapshot)) for c in contexts if c.snapshot.record_id == record_id}
        if len(variants) > 1:
            conflicts.append("Conflicting snapshots for advisory record: " + record_id)
    available = _status(Availability.AVAILABLE, "Structurally valid input supplied; factual lineage is asserted upstream; availability is not eligibility")
    missing = _status(Availability.UNAVAILABLE, "No factual DecisionInput supplied")
    advisory_status = _status(
        Availability.AVAILABLE if any(c.status.availability == Availability.AVAILABLE for c in contexts) else
        Availability.EXCLUDED_UNVERIFIED if contexts else Availability.UNAVAILABLE,
        "Context only; cannot alter T08/T09" if contexts else "No advisory supplied; disruption state unknown")
    operational = OperationalGaps(**{name: _status(Availability.UNAVAILABLE, "Outside methodology; authoritative data unavailable")
                                    for name in OperationalGaps.model_fields})
    content = dict(series=series, evaluated_at=now,
        forecast_status=available if factual else missing, decision_status=available if factual else missing,
        assessment_status=available if assessment else missing, decision=decision, assessment=assessment,
        advisory_status=advisory_status, advisories=tuple(contexts), advisory_conflicts=tuple(conflicts),
        operational=operational, limitations=(
            "Trade-lane evidence is not a physical-route model.",
            "Existing T08 decision is a market-rate decision, not a route recommendation.",
            "Advisory context cannot change decision or actionability.",
            "Unknown operational evidence is not zero or safe.",
            "Unwrapped hypothetical values cannot be authenticated by a pure core; authoritative upstream composition is required.",
        ), provenance=(
            "T18 validates structure and consistency; authoritative upstream integration must establish factual source lineage.",
            "Classification and SHA-256 fingerprint are not source authentication or proof of truth.",
        ))
    document = {"methodology": "route-intelligence-v1", **content}
    fingerprint = sha256(_serialize(_canonical(document)).encode("utf-8")).hexdigest()
    return RouteEvidenceResult(**content, fingerprint=fingerprint)
