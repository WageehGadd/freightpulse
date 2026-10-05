# T17 — Deterministic Scenario Intelligence

## Reviewed scope and architecture

Option C: one ephemeral MARKET_WHAT_IF evaluation plus factual/hypothetical
comparison. Methodology: `scenario-intelligence-v1`. Four new files only:
scenario schema, pure service, synthetic tests and this report. Existing T06,
T07, T08, T09, T10, T11 and T14 code is unchanged. No boundary solver, scenario
grid, ORM, migration, router, task, scheduling, cache, GPT or frontend exists.

The application supplies authoritative DecisionInput, DecisionPolicy and an
explicit evaluation instant. The user supplies a ScenarioRequest containing
exactly one discriminated assumption. Extra fields and unsupported categories
are rejected. A supplied application policy is not a user scenario control;
Backend must never accept policy/evidence/state overrides from a client.

## Assumptions and arithmetic

ABSOLUTE_PREDICTED_RATE accepts a finite positive Decimal or decimal string,
already cent-representable and within T06 NUMERIC(12,2): maximum 9999999999.99.
It does not silently round. Floats, integers and booleans are not assumption
inputs. Both assumption types accept exactly built-in Decimal or ASCII decimal
text: optional sign, fractional part and scientific exponent. Underscores,
non-ASCII digits, whitespace, integer/float/bool values, numeric-like objects and
string/Decimal subclasses are rejected without invoking custom conversions.
Equivalent trailing decimal zeroes are permitted within representation limits.

PERCENTAGE_ADJUSTMENT applies to the factual **predicted** rate, not the actual:

`raw = baseline_predicted_rate * (1 + requested_percentage / 100)`.

The fixed local Decimal context uses precision 28 and ROUND_HALF_EVEN. The
final hypothetical rate is quantized once to cents, then validated as money.
Raw intermediates are not exposed as a second authoritative scenario price.
Decimal intermediate operations retain this finite precision; this is not
unlimited-precision rational arithmetic. No float money round-trip occurs.
Zero and signed-zero percentages are valid and retain scenario provenance.
Nonpositive/out-of-range applied values fail closed. Percentage arithmetic
overflow is translated into ScenarioInputError.

Input representation is bounded to 28 coefficient digits and exponent magnitude
28; decimal text is limited to 64 characters without surrounding whitespace.
These are computational/representation limits, not economic slider bounds.
Percentage delta is `(applied - baseline_prediction) / baseline_prediction * 100`
in the same isolated context. The baseline prediction and actual must be valid
positive cent-representable money; missing or malformed monetary baselines are
rejected rather than repaired. Invalid historical float metrics remain copied
factual evidence, permitting T08's existing blocked result.

## Authoritative evaluation and factual preservation

Both evaluations call T08 evaluate_decision with the same application policy
and explicit UTC instant. T17 contains no movement/history/evaluation/MAE,
readiness, horizon, expiry or freshness decision formulas. Policy defaults and
decision versions remain authoritative upstream.

T08 objects are reconstructed from their Python documents, even if supplied
through unsafe model_construct/model_copy. Monetary validity and detectable
composition contradictions are rejected. Policy representation types are
checked before authoritative validation, including members of supported-horizon
sets, because T08's custom __init__ can coerce values despite strict
model_validate. Nested representation checks detect coercion without adding a
new decision policy. Missing/undeclared fields retained by unsafe model_copy are
rejected before model_dump can silently erase them. Exact authoritative model
classes are required; subclass serialization hooks are not accepted.

Canonical structural comparison also rejects unsafe copies that require metric
coercion/repair (for example a boolean metric converted to missing evidence).
Composition checks reject exact-series mismatch, conflicting stored eligibility,
unreported source/generation supersession, inconsistent context state, and
evaluation-instant mismatch. Legitimately stale, superseded, source-unavailable,
historical-only, insufficient-sample, invalid-metric and unsupported-horizon
inputs remain analytical comparisons with T08 blockers intact.

Timezone-aware generation/state/evaluation timestamps are canonicalized to UTC
before T08 evaluation as well as hashing. Python comparisons around a DST fold
can otherwise ignore distinct local instants. No clock is read. Equivalent
instants preserve identity; microseconds and distinct fold instants remain
distinguishable. Series strings receive no case/whitespace/Unicode normalization.
T08's internal SeriesIdentity permits blank strings. T17 now rejects blank,
whitespace-only and nonprintable/control identities at its own trust boundary,
without trimming or aliasing printable strings. Public API selectors remain
Backend-owned. Timezone conversion overflow and unrepresentable T08 arithmetic
or next-date calculations become ScenarioInputError; there is no fallback result.

The hypothetical DecisionInput is fully reconstructed and validated. It differs
from the canonical factual input only in forecast.predicted_rate. Neither input
is mutated. Retained forecast ID/generation is artifact context for T08, not a
claim that its model generated the assumption. Never persist or publish the
hypothetical copy as a RateForecast.

T09 assess_evidence is called exactly once, on the factual T08 result. Its
EvidenceAssessment contains the complete factual input/result. There is no
hypothetical evidence-v1 assessment. T11 runs are neither required nor attached.
Historical metrics describe the original method, not the assumed price.

## Result and safety contract

ScenarioResult contains methodology/category, exact series, evaluation instant,
explicit baseline predicted rate, factual baseline EvidenceAssessment, requested
assumption and applied rate, hypothetical_t08_result, comparison, operational
labels, limitations and SHA-256 fingerprints. All models are frozen; exposed
nested collections are tuples/frozensets, not mutable dictionaries/lists.

The wrapper is always HYPOTHETICAL, NON_OPERATIONAL and `live_actionable=false`.
Nested hypothetical_t08_result retains T08's invariant that its own actionable
matches a directional decision; the named comparison field is
`hypothetical_rule_actionable`. Neither is a live recommendation.
`analytical_only=true` whenever the factual T08 result is non-actionable,
including MONITOR; this conservatively covers more than just failed eligibility.
Every scenario remains non-operational even when analytical_only is false.

Comparison returns monetary/percentage deltas, both movements and decisions,
decision_changed, both rule-actionability flags, rule_actionability_changed and
added/removed hard blockers. Blockers/order come from T08 HARD_BLOCKERS and
REASON_ORDER. Outcome reasons are not blockers. Movement changes can coexist
with unchanged WITHHOLD. No probability/confidence/savings/ROI/score exists.

## Identity and immutability

Baseline fingerprint covers the complete canonical factual DecisionInput.
Scenario identity covers methodology, category, exact series, baseline hash,
forecast ID/generation, policy, evaluation instant, assumption provenance/type,
canonical requested value and applied rate. It is a reproducibility fingerprint,
not a signature, authorization token, durable identity or concurrency control.

Decimal coefficient/exponent canonicalization is context-independent, removes
trailing zeroes and normalizes signed zero. Datetimes use UTC; UUIDs/enums use
stable representations. Dictionaries sort keys and sets sort canonical members.
Historical float metrics use stable hexadecimal/nonfinite tagged representations.
Same-ID regeneration changes identity. Absolute and percentage assumptions with
the same applied rate have distinct identities because their provenance differs.

## Failure and infrastructure isolation

Typed request validation rejects missing/multiple assumptions, unsupported types,
extra fields and attempts to override factual evidence/policy. Missing factual
DecisionInput raises ScenarioInputError; no generation is attempted. Authoritative
structural ValidationError/ValueError failures propagate to Backend for sanitized
mapping. Deficient evidence remains a T08 WITHHOLD result where structurally valid.

Production dependencies are standard library, Pydantic and pure T08/T09/T17
modules. No database/configuration/network/environment/filesystem/subprocess,
randomness, T07, T14, publishers, Redis, Celery or WebSocket integration occurs.
Fresh-process import and guarded evaluation tests verify this boundary.

## Adversarial review

Attacks cover unsafe copying, field/policy overrides, mutation, live promotion,
identity/provenance mismatch, nonfinite/overflow/subcent money, caller Decimal
context, timezone representations, DST folds and process/hash-seed differences.
Self-review fixed isolated invalid-string parsing, typed percentage overflow,
DST-aware generation comparisons/evaluation, policy coercion detection, and
silent historical-metric repair through unsafe copies.
All fixes are confined to the new files; no upstream behavior was weakened.

The adversarial hardening phase reproduced additional defects: permissive
Decimal text parsing (underscores/Unicode digits), nested IntEnum horizon
coercion, acceptance of blank/control series, raw timezone OverflowError,
serialization erasing unsafe-copy extras, and missing constructed fields leaking
AttributeError. These are fixed solely inside T17. Tests strengthen all-field
fingerprints, type contracts, exact call counts and hostile-context coverage.

The mutation inventory is checked against every ForecastSnapshot/ForecastState
field and each nested SeriesIdentity field. No factual field is excluded from
the baseline fingerprint. Fields requiring coupled identity updates reject when
changed alone; independent changes must produce different public fingerprints.
Policy fields are all covered in scenario identity, separately from factual
baseline identity. Ordered evidence tuples retain order; sets are canonicalized.

Successful invocations perform exactly two T08 calls and one factual T09 call,
with the same policy/instant and inputs differing only in predicted rate. There
is no caller-supplied T09 assessment. With valid positive rates and all factual
gates fixed, genuine hard-blocker membership cannot change. Thus added/removed
blocker fields remain empty in supported successful scenarios; tests do not
fabricate blocker transitions or use outcome reasons as hard blockers.

## Scientific and runtime limitations

This is deterministic input substitution, not forecasting, causal identification,
Monte Carlo, calibrated uncertainty, optimization or policy learning. T08 movement
and evidence thresholds remain heuristic. Its MAE guard is not a confidence
interval. BASELINE_READY does not establish predictive accuracy. Existing source
provenance, same-date-correction and local +1-day target limitations remain.

No bunker/FX/advisory effects or port controls exist. T15 remains DATA-GATED;
seeded port data and PortWatch feasibility do not authorize scenario inputs.

Prior read-only audit verified 248 FreightRate rows, eight SCFI series with 31
observations each (2026-08-03 through 2026-09-02), zero RateForecast and zero
RateOutlook rows. T04 baseline artifacts remain stored-live-ineligible. This
implementation does not create runtime forecasts or a real persisted demo.
All scenario fixtures are explicitly synthetic. Post-test read-only verification
confirmed the same counts, series sizes and date range; no runtime forecasts or
outlooks were generated. Test databases are separate from production data.

Safe wording: “Under this hypothetical rate assumption, the existing deterministic
rule returns X.” “This scenario does not predict that the assumed rate will occur.”
Forbidden claims: scenario probability/confidence, optimal booking, expected
savings, causal impact, model-generated assumed values or live recommendations.

## Backend handoff / T-FINAL ledger

Compose one authoritative exact-series baseline from persisted Decimal values,
matching current state/generation, application-owned policy and one explicit
instant. Do not use float-valued public forecast responses as the monetary input.
Clients supply only ScenarioRequest, never eligibility, freshness, counts,
metrics, generation, policy or baseline prices. Implement auth/rate limiting,
no-store responses and sanitized errors separately. No implicit generation,
persistence, T14 calls, notifications or current-state mutation. Saved scenarios
require separate product authorization.

## Frontend handoff / T-FINAL ledger

Baseline card, assumption selector, absolute/percentage input, applied rate,
comparison, decision/movement/blocker changes and reset-to-baseline are future
Frontend work. Always show HYPOTHETICAL and NON-OPERATIONAL; show ANALYTICAL_ONLY
for blocked/non-actionable factual baselines. Explain percentage adjustment to
prediction versus movement relative to actual. No confidence/probability/savings,
optimal action or live recommendation UI.

Integration order: pure AI core review, Backend authoritative composition/API,
then Frontend scenario UX. No teammate contact, T18 or T-FINAL implementation.

## Validation record

The initial implementation record below is retained as history. Counts are collected / passed / failed /
skipped / errors / reported warnings:

- `.venv/bin/pytest tests/test_scenario_intelligence.py -q`: 119 / 119 / 0 / 0 / 0 / 4.
- `.venv/bin/pytest tests/test_decision_engine.py -q`: 78 / 78 / 0 / 0 / 0 / 1.
- `.venv/bin/pytest tests/test_reliability.py -q`: 135 / 135 / 0 / 0 / 0 / 1.
- `.venv/bin/pytest tests/test_decision_api.py -q`: 106 / 106 / 0 / 0 / 0 / 1.
- `.venv/bin/pytest tests/test_forecast_state.py -q`: 25 / 25 / 0 / 0 / 0 / 1.
- `.venv/bin/pytest tests/test_forecast_persistence.py -q`: 46 / 46 / 0 / 0 / 0 / 1.
- `.venv/bin/pytest tests/test_forecast_evaluation.py -q`: 59 / 59 / 0 / 0 / 0 / 1.
- `.venv/bin/pytest tests/test_forecast_evaluation_persistence.py -q`: 49 / 49 / 0 / 0 / 0 / 1.
- `.venv/bin/pytest tests/test_predictive_alert_evaluator.py -q`: 159 / 159 / 0 / 0 / 0 / 1.
- `.venv/bin/pytest tests/ -q`: 1059 / 1053 / 0 / 6 / 0 / 5.

The focused and full commands were first run without/with quiet output during
development; records above describe the completed pre-hardening runs.
Earlier focused runs passed 113 and 117 tests as adversarial coverage was added.
An intermediate focused run failed one unsafe-policy test, exposing coercion;
that defect was fixed. Earlier full runs failed three context-flag assertions
(1048 and 1050 passed respectively, six skipped). Those assertions compared the
special Decimal flags mapping directly; materializing it as a plain dictionary
resolved the suite-order-sensitive checks. No arithmetic change was needed for
that test correction. Those focused/full runs passed on the initial content.

Warnings are not suppressed: existing Pydantic class-Config deprecation;
three serializer warnings from deliberately unsafe float/bool model copies;
and, in the full suite, Redis async connection destructor cleanup after an
event loop closed. Six live-AI tests remain skipped by the existing configuration.

Cross-process checks passed for two PYTHONHASHSEED values. Separate production
import and guarded evaluation processes excluded infrastructure access. Tests
verify direct upstream parity and every non-rate field, rather than implementing
an alternate decision oracle. No predictive-accuracy metric is claimed.

Initial Git verification: main; HEAD and origin/main unchanged at the approved
baseline; ahead/behind 0/0; index empty; existing tracked files unchanged;
four T17 files untracked, plus the eight protected files with original SHA-256
fingerprints. New-file whitespace/security scans pass. No staging, commit, push
or T18 work. READY FOR REVIEW, not authorization to stage or integrate.

## Final adversarial hardening record

No unresolved T17 architecture defect was found after the scoped fixes. All
production/test changes are confined to the same four untracked T17 files.
Pre-hardening SHA-256 values were recorded before edits:

- Schema: 2cad25b367ab6259fe1f47f9a1b2034b59032e6a8cfe182ea501e9358322d9d8
- Service: fd659d51316e178017544ba95b563f76b4b027e85068e18c2f2d85a5d682cc6e
- Tests: a9cbbf3d9a5cda840c2301197c62720bdf928a809d51f9e85796b8df281b6ad5
- Report: 5969a77f352429702d41ef366eba779169fafe94c780cee835a34b9acb7564d7

The fingerprint inventory covers 20 forecast fields, 13 state fields and six
nested series leaves. All five policy fields affect scenario identity. Separate
tests exercise valid coupled generation changes and same-generation evidence
changes. Private fingerprint helpers are used only for canonicalization/omission
unit tests; completed decisions are checked against direct T08, not a private
scenario helper or copied rule logic. Rejected single-field composition changes
are explicitly classified, not accepted through a blanket exception assertion.

Final commands were run independently after the last code changes. Counts below
are collected / passed / failed / skipped / errors / reported warnings:

- `.venv/bin/pytest tests/test_scenario_intelligence.py -q`: 305 / 305 / 0 / 0 / 0 / 4.
- `.venv/bin/pytest tests/test_decision_engine.py -q`: 78 / 78 / 0 / 0 / 0 / 1.
- `.venv/bin/pytest tests/test_reliability.py -q`: 135 / 135 / 0 / 0 / 0 / 1.
- `.venv/bin/pytest tests/test_decision_api.py -q`: 106 / 106 / 0 / 0 / 0 / 1.
- `.venv/bin/pytest tests/test_forecast_state.py -q`: 25 / 25 / 0 / 0 / 0 / 1.
- `.venv/bin/pytest tests/test_forecast_persistence.py -q`: 46 / 46 / 0 / 0 / 0 / 1.
- `.venv/bin/pytest tests/test_forecast_evaluation.py -q`: 59 / 59 / 0 / 0 / 0 / 1.
- `.venv/bin/pytest tests/test_forecast_evaluation_persistence.py -q`: 49 / 49 / 0 / 0 / 0 / 1.
- `.venv/bin/pytest tests/test_predictive_alert_evaluator.py -q`: 159 / 159 / 0 / 0 / 0 / 1.
- `.venv/bin/pytest tests/ -q`: 1245 / 1239 / 0 / 6 / 0 / 5.

The increase from 119 to 305 focused tests (+186) covers strict type/notation,
domain endpoints, all series dimensions, 39 field mutations, policy coercion and
identity, missing/extra constructed fields, custom subclasses, exact call counts,
immutability, locale/timezone independence and context traps. Six existing
live-AI skips remain. Intermediate hardening runs exposed an outdated import
allowlist (fixed to permit standard-library re) and a missing-field guard ordering
defect (fixed before series access); no final failures remain.

Final warnings: existing Pydantic class-Config deprecation; three deliberate
unsafe-history-count serializer warnings (Decimal NaN, Decimal Infinity and a
string where an int was required); full-suite Redis destructor cleanup after a
closed event loop. Earlier monetary/policy corruption warnings disappeared
because those types now reject before serialization. No warnings are suppressed.

Full output and identity match across fresh processes with different hash seeds,
locale settings and system timezones. Hostile precision/rounding/traps/preset
flags leave caller context unchanged. Guarded fresh-process evaluation still
proves pure infrastructure/GPT/T14 isolation. READY TO STAGE is a review verdict
only: no staging, commit, push, teammate contact or T18 work was performed.
