# AI-V3-T14 — Predictive Alerts

## Scope and architecture

Option B implements a small pure deterministic transition evaluator. Policy is
`predictive-alerts-v1`, independent of `decision-rules-v1`, `evidence-v1`,
`baseline-v1-decimal`, and `baseline-evaluation-v1`.

Exactly four new files:

- `app/schemas/predictive_alert.py`
- `app/services/predictive_alert_evaluator.py`
- `tests/test_predictive_alert_evaluator.py`
- `docs/FREIGHTPULSE_AI_V3_T14_PREDICTIVE_ALERTS_REPORT.md`

No existing tracked file is changed. No database, persistence, API, scheduler, delivery,
frontend, GPT, or new dependency is implemented. Existing alert code is untouched.
The entry point is `evaluate_predictive_alert(PredictiveAlertInput)`.

T06 supplies immutable forecast evidence through T08. T08 owns the decision,
movement, thresholds, history/evaluation minimums, error-scale guard, freshness,
horizon, temporal checks, and safety gates. T09 owns evidence assessment. T14
does not call those services, collect state, recompute rules, or assess evidence.
It checks consistency of supplied copies and consumes their authoritative flags,
decisions, and statuses.

## Input contract

`PredictiveAlertInput` is frozen, forbids extra fields, and contains:

- `policy_version`: literal `predictive-alerts-v1`.
- `series`: existing frozen T08 `SeriesIdentity(source, trade_lane, container_type)`.
- `decision`: existing frozen T08 `DecisionResult`, including policy, reasons,
  limitations, signals, forecast identity, input snapshot and current state.
- `evidence`: matching existing frozen T09 `EvidenceAssessment`.
- `previous_checkpoint`: optional frozen `AlertCheckpoint` accepted by Backend.

Exact series identifiers are preserved, including case, whitespace, Unicode, and
escaping. Blank, whitespace-only and control-only identifiers are invalid.
Identifiers with printable non-whitespace content are retained exactly, including
any surrounding whitespace or embedded controls. No trimming, aliasing,
case-folding, or Unicode normalization changes identity. A missing forecast is
valid only with a matching UNAVAILABLE decision/evidence pair; explicit series
remains necessary when no forecast exists. Missing the evidence object is
structurally invalid, distinct from a supplied unavailable evidence status.

Forecast generation is the existing forecast UUID plus timezone-aware
`generated_at`, not UUID alone. Both the copied forecast/input and T09 provenance
must agree. Safety-state winner generation must agree for unblocked decisions.
This distinguishes same-ID T06 regeneration without inventing model versioning.

## Output and checkpoint contracts

`PredictiveAlertResult` contains:

- `policy_version`: literal `predictive-alerts-v1`.
- `status`: BASELINE_ONLY, EMIT, SUPPRESS, or INVALID_INPUT.
- `transition`: optional DIRECTIONAL_ENTERED, DIRECTION_REVERSED, or
  ACTIONABILITY_WITHDRAWN.
- `category`: optional DIRECTIONAL or OPERATIONAL.
- `signal_identity`: optional 64-character lowercase SHA-256 hex digest.
- `reasons`: ordered immutable tuple of `AlertReason`.
- `evidence`: matching full T09 assessment for valid input; absent on invalid input.
- `next_checkpoint`: deterministic proposal for valid input; absent on invalid input.

Only EMIT carries transition/category/signal identity. Withdrawals must be
OPERATIONAL. Directional emissions require an eligible checkpoint direction.

`AlertCheckpoint` contains policy version, exact series, `CheckpointState`,
`previous_token`, `state_fingerprint`, and `accepted_checkpoint_token`.
The token field names its intended role after acceptance: a returned checkpoint
is still a proposal, not an accepted or persisted write.

`CheckpointState` contains the original T08 `decision` and `actionable`, optional
`eligible_direction`, optional `ForecastGeneration(forecast_id, generated_at)`,
T09 historical/sample/decision statuses, and `evidence_fingerprint`.
Original T08 actionability is retained separately from evidence-supported signal
eligibility. A legitimate unsupported T09 methodology may accompany a directional
T08 result; T14 preserves that result but cannot signal a booking direction.
The checkpoint records the evidence digest/statuses; the output retains the full
assessment, factors, limitations, provenance and nested original evidence.
Backend decides whether it needs to persist that full immutable evidence too.

All nested contracts are frozen existing/new Pydantic models, immutable tuples,
frozensets, or scalar values. No mutable list/dictionary field is exposed.

## Transition rules

The effective monitored direction is the T08 direction only when T08 is actionable
and T09 reports AVAILABLE historical evidence, POLICY_MINIMUMS_MET samples, and
DIRECTIONAL_RULES_PASSED decision evidence. These statuses are consumed without
performance grading or threshold recomputation. AVAILABLE does not mean accuracy,
reliability, confidence, or verified provenance.

The complete transition mapping is:

- No accepted previous checkpoint, any valid current state: BASELINE_ONLY,
  PREVIOUS_CHECKPOINT_ABSENT, no signal. This includes first actionable observations.
- Non-directional to eligible earlier/later: EMIT / DIRECTIONAL_ENTERED / DIRECTIONAL.
- Earlier to later or later to earlier: EMIT / DIRECTION_REVERSED / DIRECTIONAL.
- Earlier to earlier or later to later: SUPPRESS / UNCHANGED_DIRECTION, including
  new forecast generations that retain the same direction.
- Eligible direction to valid WITHHOLD, MONITOR, UNAVAILABLE, or unsupported evidence:
  EMIT / ACTIONABILITY_WITHDRAWN / OPERATIONAL. This is loss of actionability,
  never an opposite booking prediction or a confidence downgrade.
- Non-directional to non-directional, including MONITOR to MONITOR and blocked
  to MONITOR: SUPPRESS / NO_DIRECTIONAL_TRANSITION.
- Structurally contradictory input: INVALID_INPUT, no signal and no checkpoint.

T08 blockers such as stale/superseded/expired/historical-only/unsupported-horizon
states yield normal non-actionability, not structural failure. Contradictory
directional claims with unsafe copied state fail closed instead. Stored false
eligibility cannot be promoted. MONITOR never creates a directional signal.
T14 reasons follow enum declaration order; upstream factors/reasons/limitations
remain in their original deterministic order.

## Invalid-input boundary

The evaluator revalidates nested models from Python-mode dumps to catch
`model_copy`/`model_construct` validator bypass. It rejects malformed types,
wrong T14 policy, blank or mismatched exact series, mismatched T08/T09 pairs,
provenance/generation disagreement, inconsistent copied metrics/sample fields,
impossible outcomes/movements, and directional/monitor safety contradictions.
It verifies prior checkpoint state digest and chained token before using it.
Revalidation is strict: validator-bypassed boolean/numeric/string types are not
silently coerced into a valid authoritative result. T09 descriptive numeric fields
must be finite; non-finite raw deficient T08 snapshot values remain valid blocked
evidence and cannot become actionable. Every supplied datetime, including an
incidental evaluation instant, must be aware even when omitted from hashing.

Safety checks consume upstream flags (stored/effective eligibility, supersession,
series match, context, supplied freshness classification) and blocker reasons.
They do not calculate ages, source cadence, MAE comparisons, movement, or policy
minimums. T09 owns sanitization: missing sanitized metrics remain legitimate for
blocked decisions. Unsupported/unavailable evidence cannot support direction.

This is an internal trusted-producer boundary, not a cryptographic attestation of
T08/T09 computation. A malicious party could forge a fully consistent assessment
or rehash a fabricated checkpoint. Backend must enforce ownership and composition
from authoritative current data. T09 carries the complete T08 result, which permits
value-level pair comparison, but no persisted decision artifact ID or signed linkage.
T14 can verify copied identity, raw metrics/counts, status correspondence, policy
and safety flags; it cannot attest that T09's derived ratios/factor narratives were
genuinely computed by T09 without recomputing that methodology. It preserves those
outputs instead. Hashes are not authentication, signatures, authorization,
tamper-proof persistence or concurrency control; collisions are not claimed impossible.

## Identity, retries, cycles and canonicalization

Identity uses standard-library SHA-256 over structured canonical JSON with sorted
keys, explicit separators, ASCII Unicode escaping, UTF-8 bytes and forbidden
JSON NaN literals. Finite Decimal encoding is a sign/coefficient/exponent tuple
with insignificant trailing coefficient zeroes removed; signed zero is canonical
zero. Thus 1, 1.0 and 1.00 have the same identity within Decimal-typed fields.
Floats use exact hexadecimal encoding and normalize signed zero; schema-typed
numbers are not converted through Decimal/float round trips. Non-finite deficient
raw T08 evidence has explicit textual numeric tags, whereas non-finite T09
descriptive output is rejected. Decimal handling does not perform context-sensitive
arithmetic, including very large exponents. Sets are sorted canonically;
ordered evidence tuples retain order. UUIDs/dates have stable textual forms;
aware timestamps become UTC ISO strings. Unicode remains exact, including composed
versus decomposed forms. Equivalent aware timezone offsets normalize to the same
UTC instant; microsecond generation changes remain distinct. Structured fields
prevent separator-concatenation ambiguity.
Pair comparisons also use canonical UTC instants, retaining evaluation times for
consistency checks. Distinct DST-fold instants cannot pass as equal merely because
Python wall-time equality treats them as equal in the same timezone.

All `evaluated_at` fields are excluded from identity. They remain visible in the
returned evidence. Forecast generation timestamps, source/target dates, policy,
decision, current-state flags, quantitative evidence, factors and limitations
remain identity-bearing. Equivalent numeric formatting does not change fingerprints.

- Evidence fingerprint: hash of canonical full supplied T09 assessment, including
  its T08 snapshot, excluding incidental evaluation instants.
- State fingerprint: hash of canonical `CheckpointState`.
- Checkpoint token: hash of structured kind=checkpoint, T14 policy, exact series,
  explicit genesis marker OR previous accepted token, and current state fingerprint.
- Signal identity: hash of structured kind=signal, T14 policy, exact series,
  previous accepted token, transition, and current state fingerprint.

Same previous/current/policy yields identical next checkpoint and signal. A genuine
EARLIER → blocked → EARLIER cycle changes the accepted chain and produces a distinct
later entry signal even when the final evidence matches the first entry. Different
generations/series/policies/parents are distinguished. No clock, UUID generation,
worker ID, random input, or database-generated checkpoint ID enters hashing.

If canonical current state equals the accepted checkpoint state, the evaluator
returns that accepted checkpoint unchanged: exact semantic retries do not advance
the chain. Changed evidence or generation proposes one new chained checkpoint,
even when direction stays unchanged or both states are non-actionable; no signal
is emitted for those changes. Retry before acceptance repeats the same proposal;
retry after acceptance suppresses and retains the accepted checkpoint. Backend
must recognize equal input/output tokens as no change rather than perform another
acceptance. There is no cooldown or delivery rate policy.

### Fingerprint inventory and rationale

Checkpoint state fields are original decision/actionability (authoritative outcome),
eligible direction (effective monitored state), generation UUID/time (same-ID
regeneration), historical/sample/decision statuses (evidence availability), and
full evidence fingerprint (immutable input linkage). Series and T14 policy are
outside the state digest but are included in checkpoint/signal identity.

The evidence fingerprint recursively covers every supplied T09 field except
evaluation instants:

- Assessment version: evidence methodology identity.
- Full decision result: engine version, policy and supported-horizon set, decision,
  actionability, movement, reasons, signals and limitations preserve the outcome
  and methodology; copied forecast/input snapshot preserve exact evidence.
- Forecast snapshot: UUID, exact series, target/cutoff dates, prediction/actual,
  model/version/horizon, history/evaluation counts, four backtest metrics,
  readiness, stored freshness/eligibility, warning and generation time preserve
  the evidence generation and distinguish corrections/regeneration.
- Current state: exact series, latest source date, winner UUID/generation, matching
  and supersession flags, current freshness, stored/effective eligibility, context
  and warning preserve currentness and safety.
- Historical/sample/decision statuses and sample evidence preserve assessment
  availability, counts and readiness.
- Historical error and directional evidence preserve descriptive metrics/ratios
  and unavailable directional denominator; decision margin preserves supplied
  signals, policy values and within-error-scale flag without recalculation.
- Model provenance preserves model, artifact, generation, cutoff/target/horizon
  and supplied methodology-supported status.
- Factors and assessment limitations preserve their dimension/code/kind/reference,
  observed value, requirement, explanation and ordered limitations.

T08 and T09's repeated immutable copies are intentionally retained; T14 does not
introduce another forecast or decision policy representation. UUID formatting and
equivalent timezone/numeric representations do not cause churn. Dictionaries are
key-sorted and set-like policy horizons are sorted. Reasons, limitations and factors
are ordered contract data and are not sorted. Supplied warning/explanation text is
retained as auditable evidence: changing it intentionally changes the evidence
fingerprint, though an unchanged direction still emits nothing. Authoring/text-order
changes can therefore advance a checkpoint without producing a directional signal.

## Concurrency and integration boundary

Pure T14 performs no acceptance or delivery. Two workers using the same accepted
parent/current evidence produce identical signals/checkpoints. Backend must
revalidate current generation and atomically compare-and-set the accepted parent
while storing/deduplicating the transition and arranging reliable delivery.
Out-of-order results must be rejected at that boundary. Pure hashes alone do not
provide durable concurrency safety or exactly-once delivery.

## Evidence, provenance and scientific limitations

The full T09 output is preserved for valid input, including historical/sample/
decision statuses, current state, factors, assessment limitations, model provenance,
copied T08 policy/reasons/limitations and evaluation timestamps. No second score,
confidence tier, probability, interval, severity or business-outcome estimate exists.
T09 has no explicit verified historical-source classification; T14 does not invent
one. Current local/sample historical provenance remains UNVERIFIED.

Known prior read-only runtime baseline, retained rather than re-queried here:
248 FreightRate, zero RateForecast, zero RateOutlook; eight exact series with
31 observations each. No live runtime rows, alerts, checkpoints, forecasts or
migrations were generated during implementation. Tests use the established isolated
test database fixtures, not production runtime composition.

Current data cannot produce actionable predictive booking signals: no persisted
forecast exists; history is below T08 minimum; applicable evaluation evidence is
below the required policy; baseline eligibility remains historical-only /
`live_decision_eligible=False`. No policy is weakened and no runtime demo is fabricated.

Existing upstream limitations remain: heuristic policy values, MAE guard is not a
confidence interval, BASELINE_READY does not validate accuracy, same-date source
corrections are undetected, target +1 day is the local dataset contract, and genuine
daily external SCFI cadence has not been verified. T11 does not justify calibrated
confidence, uncertainty intervals, predictive alert accuracy or booking benefits.

Approved capability claim: “FreightPulse can deterministically identify changes
in eligible forecast-backed decision states and produce reproducible predictive
signal identities.” This is a system capability claim, qualified by unverified
local/sample history, no persisted runtime forecasts, and no current live-actionable
baseline eligibility. It is not validated booking-outcome performance.

Forbidden claims include perfect/optimal booking timing, proven optimization,
alert accuracy percentage, confidence/probability of increase or success, proven
savings/ROI/causal benefit, or verified real-time market predictions.

## Existing alert integration findings — handoff only

1. Application user-rule alerts are reactive historical change/threshold checks.
2. Legacy AI anomaly alerts are reactive statistical anomalies, not forecast-backed.
3. Rule/evaluation-date deduplication is different from T14 transition identity.
4. Existing rule selectors lack required exact source/container identity.
5. Legacy and application RateAlert persistence contracts may be incompatible.
6. Application analysis wrappers reference missing AI modules.
7. Automatic Redis/WebSocket delivery is not wired into audited persistence paths.
8. No production email/mobile-push delivery was found.

No listed issue is repaired in T14.

## Backend handoff ledger — no teammate contact

- Exact-series predictive subscriptions and current T06/T08/T09 composition.
- Durable accepted checkpoints and atomic compare-and-set acceptance.
- Current-generation revalidation before acceptance; out-of-order rejection.
- Durable signal uniqueness/deduplication and immutable event/evidence persistence.
- Auth/user ownership, public API and read/unread state.
- Outbox/reliable delivery; Redis/WebSocket if chosen; email/push if required.
- Scheduling/triggering, no-op acceptance policy, deployment and any chosen migrations.
- Reconcile existing alert contracts and missing analysis-wrapper modules.

## Frontend handoff ledger — no teammate contact

- Predictive alert card and notification center.
- Exact source/lane/container identity; entered/reversed/operational-withdrawn states.
- Timestamp, freshness, evidence/provenance limitations and supersession/current-state UX.
- Links to forecast/decision detail and read/unread UX.
- T12 Forecast UI, T13 Decision Card and T16 Evidence Panel remain FRONTEND HANDOFF.

T15 Live Port Data, T17 Scenario Intelligence and T18 Route Intelligence 2.0 are
not begun.

## Verification record

Focused adversarial tests use real T08 evaluations and T09 assessments. They cover
the entire six-by-six transition matrix, first-observation suppression, retries,
recurring cycles, exact-series mismatches, same-ID regeneration, malformed policy/
checkpoints/pairs, current-state blockers, missing/unsupported/deficient evidence,
canonical Unicode/escaping/order, policy/parent separation, evaluation-time exclusion,
frozen nested models, deterministic ordering and absent unsupported fields.
The sixth state is a legitimate unsupported T09 methodology with an otherwise
directional T08 result, monitored as non-directional. With NONE initialization this
covers 42 valid conceptual pairs. Impossible combinations (directional/actionable
disagreement, generation present with UNAVAILABLE, contradictory evidence status,
or incorrect direction/movement) are invalid inputs, not extra reachable states.

Fresh-process proof blocks SQLAlchemy, Redis, Celery, FastAPI, OpenAI, Azure and
HTTP client imports; removes database/Redis/provider configuration; blocks socket
creation/connections, environment access, open calls, subprocess, random/UUID
generation and clocks during evaluation; evaluates repeated real inputs successfully.
Library/source loading and fixture deserialization happen before runtime access
guards, because importing Python/Pydantic necessarily loads source files. Import
guards are active before T14 imports. Three processes use different PYTHONHASHSEED
values and C/en_US.UTF-8 locale settings and match the complete parent result.
Source inspection confirms no implicit datetime.now/today, randomness, filesystem,
environment, subprocess or infrastructure access in either production T14 file.

Each command below is independent and uses `.venv/bin/pytest`:

- `tests/test_predictive_alert_evaluator.py`: 159 collected, 159 passed.
- `tests/test_decision_engine.py`: 78 collected, 78 passed.
- `tests/test_reliability.py`: 135 collected, 135 passed.
- `tests/test_decision_api.py`: 106 collected, 106 passed.
- `tests/test_forecast_state.py`: 25 collected, 25 passed.
- `tests/test_forecast_persistence.py`: 46 collected, 46 passed.
- `tests/test_grounded_rate_outlook.py`: 49 collected, 49 passed.
- `tests/test_baseline_forecasting.py`: 7 collected, 7 passed.
- `tests/test_forecast_evaluation.py`: 59 collected, 59 passed.
- `tests/test_forecast_evaluation_persistence.py`: 49 collected, 49 passed.
- `tests/test_data_quality.py`: 8 collected, 8 passed.
- `tests/test_ai/`: 75 collected, 75 passed.
- `tests/`: 940 collected, 934 passed, 6 skipped, zero failed/errors.

Individual commands have zero failed/skipped/errors. Existing class-based Pydantic
Config deprecation warnings remain visible (one per independent targeted command).
The full suite reports two warnings: that deprecation and an existing Redis
`AbstractConnection.__del__` unraisable exception, `RuntimeError: Event loop is
closed`. Neither is suppressed.
The six skipped tests are not counted as passed. No existing tracked files are
modified. Compared with the reviewed 781-test baseline, the 159 T14 tests account
for all 940 collected tests.

### Hardening defects and fixes

The initial 85 tests missed accepted-state retry behavior and representation
equivalence. Twenty-five newly added targeted cases failed against the original
implementation and then passed after fixes. A later adversarial run reproduced
two further failures (non-finite T09 descriptions and coercion of bypassed boolean
types). Final tests also enforce the previously unenforced output evidence contract.
Subsequent targeted tests reproduced escaped exceptions for a missing constructed
decision field and an aware generation outside representable UTC range, plus
contradictory historical evidence supplied with an absent forecast.

1. Exact semantic reevaluation advanced the chain: return the verified accepted
   checkpoint unchanged when current and prior canonical state fingerprints match.
2. Equivalent Decimal scales and signed float zero changed identity: canonicalize
   finite Decimal coefficients/exponents and signed numeric zero without arithmetic.
3. Control-only series values were accepted: require printable non-whitespace
   content without changing the supplied identifier.
4. Naive evaluation timestamps were skipped by hashing and accepted: validate
   all datetime values before excluding incidental evaluation timestamps.
5. Rehashed impossible checkpoint status combinations were accepted: enforce
   T09 outcome/status correspondence and absent-forecast evidence constraints.
6. Non-finite T09 descriptive outputs were accepted: reject these inconsistent
   supplied descriptions while preserving raw deficient T08 evidence.
7. Validator-bypassed actionability integers were coerced: strict revalidation and
   a pre-dump boolean check fail closed without silently repairing input.
8. Result schemas allowed valid output without evidence: enforce valid-result
   evidence presence and invalid-result evidence absence.
9. The new pre-dump boolean guard initially read a missing decision outside the
   exception boundary: move it inside to return INVALID_INPUT rather than raising.
10. Extreme aware generation timestamps could overflow UTC conversion: catch
    this detectable invalid identity and return no checkpoint/signal.
11. No-forecast T09 pairs could carry invented copied historical evidence:
    require the authoritative absent-forecast description to have empty evidence.
12. Python datetime equality could hide different generations in a repeated DST
    wall-time hour: compare copied models/timestamps using canonical UTC instants,
    including evaluation times for consistency while excluding them from identity.
    Three provenance/winner/decision-pair cases reproduced the defect before fixing.

The matrix oracle now uses explicit expected rows rather than mirroring service
branches. Coverage adds accepted retries, changed non-actionable evidence, repeated
cycles, timezone equivalence, microseconds, distinct UUIDs, semantic numeric
equivalence, controls, complete result comparisons across processes and guarded
runtime access. Tests exercise behavior; private hash helpers are used only for
canonicalization contracts or deliberately constructing detectable corruption.

Production complexity is justified by explicit frozen input/checkpoint/output
contracts, fail-closed copy checks, canonical hashing and transition rules. No
dead public fields, infrastructure abstractions or shadow T08/T09 policy were
found. One existing decision/status mapping was shared with checkpoint validation
to avoid duplicate representations; no aesthetic refactor was performed.
Project-local dependencies are only `app.schemas.decision`,
`app.schemas.reliability`, and `app.schemas.predictive_alert`; those upstream schema
imports are safe domain definitions, with no service/config/startup import.

## Self-review and Git safety

Implementation review specifically checked cycle collapse, duplicate directional
signals, incidental timestamp contamination, normalization, generation ambiguity,
policy duplication, unsupported scoring, first-observation flooding, MONITOR noise,
withdrawal category, unsafe state emission, checkpoint tampering, mutable fields,
infrastructure imports and scope creep. Defensive copy/provenance consistency and
context checks were added within the new files before final test execution.
No upstream defect was changed; existing integration findings remain handoff work.

Baseline branch `main`, HEAD and origin/main both
`8f366599fa9cb61a522a6ae6755ffd3b8017f87d`, ahead/behind 0/0, empty index,
clean tracked tree. Final verification includes full untracked-file accounting,
explicit whitespace/security scans and unchanged SHA-256 fingerprints for all
eight protected files. The four T14 files remain untracked for human review.
Nothing is staged, committed or pushed.
