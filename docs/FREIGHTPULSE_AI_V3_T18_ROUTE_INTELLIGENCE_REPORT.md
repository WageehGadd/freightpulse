# AI-V3-T18 — Route Intelligence 2.0

## Review state and scope

Implemented Option B only: pure deterministic market-lane evidence composition,
methodology `route-intelligence-v1`. Human review is pending. Four new files are
working-tree additions, untracked and unstaged. No existing file was modified.
No commit, push, runtime migration, ingestion or production generation occurred.

“Trade-lane evidence is not a physical-route model.” The roadmap name does not
establish a maritime path, voyage, sailing service, port sequence or itinerary.

## Contract

`compose_route_evidence(RouteEvidenceRequest) -> RouteEvidenceResult` is pure.
The request requires frozen `MarketSeries(source, trade_lane, container_type)`
and an explicit timezone-aware `evaluated_at`. Optional `decision_input` is the
existing factual T08 DecisionInput, never a caller-supplied completed decision.
Optional advisories are a tuple of frozen AdvisorySnapshot objects.

Identity strings remain exact: no trimming, casefolding, Unicode normalization,
aliasing, substring matching or country/port inference. Blank and nonprintable
identities are rejected. Printable leading/trailing spaces remain significant.
No physical origin/destination is inferred from a lane.

The service traverses declared model fields and exact primitive/domain types
before serialization, rejects missing/extra fields and unsafe copies, then
reconstructs with strict Pydantic validation. Generic mappings and subclasses
are not the service input contract. Bool-as-int, IntEnum-as-int, float money,
naive timestamps and malformed nested evidence fail closed. Revalidation may
canonicalize aware instants to UTC but cannot repair semantic evidence.

Both nested decision series must match the explicit market series. State and
request evaluation instants must agree. Future generation/publication/observation
instants and contradictory stored eligibility snapshots are fatal. Stored false
eligibility cannot be promoted. Existing T08 remains responsible for source
freshness, supersession, expiry, horizon, movement and evidence gates. T18 does
not recompute those policies or query state; authoritative Backend composition
must supply internally coherent factual state.

When DecisionInput is supplied, T18 calls T08 exactly once with application-owned
DecisionPolicy defaults and the explicit instant, then calls T09 exactly once.
No request policy override exists. The completed T08 result and T09 assessment
are preserved; no new recommendation or actionability is computed. Availability
means evidence was supplied, not that it is eligible, accurate or actionable.
T09's own detailed status remains authoritative even when its assessment object
is available.

Without DecisionInput, neither evaluator is called. Decision and assessment are
absent and their statuses explicitly UNAVAILABLE. No MONITOR, zero movement,
false actionability or forecast is fabricated.

The result separates series identity; forecast/decision/assessment statuses;
completed decision and assessment; advisory context; operational gaps;
limitations; provenance statements; methodology; evaluation instant; fingerprint.

## Advisory context and provenance

Classification has five values: VERIFIED_SOURCE_DATA,
PERSISTED_APPLICATION_DATA, DERIVED_INTERPRETATION, SEEDED_DEMO_DATA, UNVERIFIED.
These are upstream assertions, not authentication by this core.

Snapshots preserve record identity, carrier, optional exact series, optional URL,
source text, separately labelled derived summary, publication/observation times,
and separate source/derived effective instants. Missing provenance is not invented.
Source-effective dates may be future scheduled events; no guessed expiry exists.

Only VERIFIED_SOURCE_DATA with exact series, nonblank source text and URL is
AVAILABLE qualified source context. Persisted data alone is not source verification.
Other classifications or incomplete linkage are EXCLUDED_UNVERIFIED, retained
with qualification. A mismatched explicit series is fatal, not a fallback.
Derived summaries remain labelled derived even on a source-qualified snapshot.

No advisory changes T08, T09 or actionability. All operational sections remain
unavailable, even with qualified advisories. No measured severity is inferred.
A plausible URL, classification or hash cannot prove provider authenticity.
Current example.com seeded advisories must be classified SEEDED_DEMO_DATA by
upstream callers, never silently declared live.

Contexts are canonically sorted. Distinct snapshots with the same record ID
produce deterministic conflict notices and are both preserved. The core does
not infer semantic contradictions between unrelated prose, resolve conflicts,
average severity or select a convenient assertion. Canonically identical repeated snapshots
are collapsed; accidental transport multiplicity does not change content identity.
No advisory means no evidence supplied, not no disruption or a safe route.

## Operational gaps and boundaries

Availability states are AVAILABLE, UNAVAILABLE and EXCLUDED_UNVERIFIED, each
with a deterministic explanatory reason. There is no numeric completeness score.
Physical route, verified port operations, distance, transit time, alternatives,
ranking and operational route risk are always UNAVAILABLE under v1.
Unknown congestion is not zero congestion; unknown transit is not zero days;
unknown distance is not zero distance. No risk, ETA or savings fields exist.

T11 evaluation composition is deferred. T14 alert/checkpoint/delivery behavior is
isolated. T15 remains AUDIT COMPLETE / IMPLEMENTATION DATA-GATED. T17 is hypothetical
and ScenarioResult, generic scenario mappings and extra override fields are rejected.
No production T17 import exists. A pure core cannot detect a counterfactual value
that has been stripped of its provenance and deliberately repackaged as a valid
DecisionInput; Backend must retrieve and authenticate factual input. Fingerprints
are reproducibility identifiers, not truth proofs or concurrency controls.

Bunker, FX and static geography are excluded from v1. No fuel coefficient, route
cost, currency-adjusted decision, distance calculation or external provider is added.
Legacy Route Brief GPT recommendation/risk/narrative is neither imported nor used.
No existing Route Brief prompt, generator, schema, task, API or PDF behavior changed.
A future separately authorized narrative adapter could consume this evidence;
it would require a narrative-only contract and independent grounding review.

## Determinism, money and time

Monetary snapshots remain Decimal, including their original scale. No binary-float
money conversion or silent monetary rounding occurs. T08/T09 run within an isolated
28-digit ROUND_HALF_EVEN Decimal context to avoid ambient host precision changes;
the caller's Decimal context is restored. T18 does not recreate their calculations.
Existing nonfinite/negative/missing analytical evidence remains deficient evidence
for their authoritative gates rather than being repaired into plausible values.

All input datetime fields must be aware. Equivalent instants become UTC in copied
snapshots; no system clock is read. Dates retain date semantics. Source freshness
remains separate from artifact generation and evidence evaluation. T02's configured
cadence is not proof of external SCFI publication cadence.

SHA-256 covers methodology, exact series, instant, complete factual input within
the T08 result, policy/version, T09 content/status, all advisory snapshots including
provenance and exclusion, operational statuses, limitations and provenance notes.
Canonical JSON uses sorted keys, explicit enum values, exact date/UUID strings,
UTC instants, scale-independent Decimal tuples and canonical signed zero. Floats
use stable representations including deficient nonfinite markers; unordered sets
are sorted. No Python hash, random UUID, repr, pickle or environment identity is used.

All models are frozen; nested public collections are tuples/frozensets and frozen
models. There is no public mutable list/dict evidence collection.

## Failure behavior

RouteEvidenceInputError distinguishes fatal structural/type/linkage/temporal
inconsistency from valid unavailable evidence. Errors do not echo evidence or
credentials. No repair, provider retry, fallback query or generation is attempted.

The core has no database, filesystem, environment, network, clock, random, GPT,
Redis, Celery, FastAPI, persistence, ORM, migration or public API integration.

## Runtime context from approved audit

The prior read-only audit found 248 freight observations, eight series with 31
stored daily observations each, 52 trends, six seeded port rows, three seeded/example
advisories, nine bunker observations, one FX observation, 18 completed legacy briefs,
zero persisted forecasts, zero outlooks and zero rate alerts. This is audit context,
not evidence that external SCFI is daily or that these rows are live market advice.
Bunker/FX lack sufficient row-level provenance to certify source authenticity.

Runtime migration was b2c3d4e5f6a7, behind repository head c3d4e5f6a7b8.
This implementation did not repair or mutate production data. Regression tests
use the existing isolated test-database configuration and existing fixtures.

## Validation

Focused command: `.venv/bin/pytest tests/test_route_intelligence.py -q`:
255 collected, 255 passed, zero failed/skipped/errors, one warning.

Independent regression commands, each `.venv/bin/pytest tests/<file>.py -q`:

- test_decision_engine: 78 collected/passed; one warning.
- test_reliability: 135 collected/passed; one warning.
- test_decision_api: 106 collected/passed; one warning.
- test_forecast_state: 25 collected/passed; one warning.
- test_forecast_persistence: 46 collected/passed; one warning.
- test_forecast_evaluation: 59 collected/passed; one warning.
- test_forecast_evaluation_persistence: 49 collected/passed; one warning.
- test_predictive_alert_evaluator: 159 collected/passed; one warning.
- test_scenario_intelligence: 305 collected/passed; four warnings.

All completed regressions had zero failed/skipped/errors. An initial sandboxed
Decision API attempt had 106 collected, 19 passed, 87 connection setup errors,
zero failures/skips and one warning. Local-service permission resolved that
infrastructure restriction; the completed rerun above passed.

Tests use synthetic data, direct T08/T09 parity oracles and call counters. They
exercise unsafe construction/copies, missing/extra fields, exact types, identity
mutations, missing forecast/context, provenance exclusion, conflict preservation,
UTC equivalence, Decimal scale/signed zero, frozen nesting, fingerprint mutations,
policy representation, infrastructure isolation and T17 rejection. Fresh processes
with distinct PYTHONHASHSEED/TZ settings compare both missing-input fingerprints
and complete factual outputs. No test claims provider or predictive validation.

Pre-hardening full suite: 1,350 collected, 1,344 passed, six skipped, zero
failed/errors, five warnings. The hardened full-suite result is recorded below.
Warnings: one existing class-based Pydantic Config deprecation; one existing Redis
async connection destructor / closed event-loop warning in orchestration; three
existing T17 deliberate-corruption serializer warnings. No warning was hidden.
Focused/regression deprecation warnings are from the existing test import graph,
not new class-based configuration in T18.

## Backend and Frontend handoff / T-FINAL ledger

AI-only core implementation and adversarial hardening are complete for review. No teammate was contacted.
There is no immediate breaking shared-contract blocker.

Backend later owns authoritative persisted forecast retrieval, market-series
resolution, DecisionInput construction, factual-lineage enforcement, current-state
retrieval, advisory retrieval/relevance resolution/source verification, runtime
migrations, public API integration, auth, rate limiting, cache/no-store and sanitized
errors. Resolve the existing runtime
migration mismatch and absent forecasts before advertising integrated evidence.

Frontend later may show exact market lane, availability, unchanged T08 decision,
T09 evidence status, provenance badges, qualified context, operational gaps and
limitations. It must distinguish market-rate decisions from route recommendations,
never label EARLIER/LATER as best route/reroute/safe route/ship now without a
separately approved product mapping, and must not add a
best-route badge, risk gauge, ETA, congestion meter, confidence or savings display.

Integration order: approve the pure contract; establish authoritative Backend
retrieval/provenance; review API/security/cache contract; integrate UI; separately
review any narrative upgrade. Acceptance includes exact identity, coherent evidence,
T08/T09 parity, exclusion of seeded/unverified operational support, scenario isolation
and honest unavailable-state presentation. No T-FINAL file/task was started.

## Claims

Safe: “FreightPulse deterministically assembles available evidence for an exact
market lane and explicitly identifies unavailable or unverified inputs.”
“When structurally valid factual forecast evidence is supplied by an authoritative
upstream composer, FreightPulse reuses its existing deterministic decision and
evidence-assessment methodologies.”
“Trade-lane evidence is not a physical-route model.”

Forbidden capabilities: best/optimal/recommended/fastest/safest/lowest-risk route;
route confidence/probability; live congestion or real-time port conditions;
predicted transit time/ETA/delay probability; expected/guaranteed savings;
route optimization; physical route intelligence; causal route impact.

## Final verification

Branch main; HEAD and origin/main remain
039a8e13b7aeac88531d8aae15d737a79fa0499b; ahead/behind 0/0. Index empty;
tracked worktree clean. Exactly four new T18 files plus eight protected files are
untracked. Protected SHA-256 fingerprints match the pre-implementation baseline.
New-file whitespace and security scans passed; no credential, machine-specific
absolute path, runtime export or generated database artifact is part of T18.

Pre-hardening complete Git-baseline accounting (all four files are new, no deletions):
- schema: 104 insertions;
- service: 188 insertions;
- tests: 382 insertions;
- documentation: 247 insertions;
- total: 921 insertions, zero deletions.

Recommendation after initial implementation: ready for human review, not staged. Stop here;
no commit, push, Backend/Frontend integration or T-FINAL work is authorized.


## Adversarial hardening

T18 establishes structural validity, internal consistency, exact identity linkage
and deterministic evaluation. It does not establish database provenance, provider
authenticity, production persistence or real-world factual truth. A normal-shaped
DecisionInput with a manually substituted hypothetical price passes structural
validation: the pure core cannot detect repackaged hypotheses. This is explicitly
tested. No plausibility heuristic is introduced. Authoritative upstream factual
lineage enforcement is a prerequisite for integration and belongs in the T-FINAL
ledger. Neither a provenance label nor a SHA-256 fingerprint proves truth.

Default policy is constructed directly by the authoritative T08 DecisionPolicy
class, exactly as the existing decision API does. No separate default object or
constant exists in T08; no threshold, history minimum, MAE multiplier, horizon,
blocker or reason-order values are copied into T18. Introspection tests cover every
current authoritative policy field's contribution to the result fingerprint.

Real hardening changes: canonically identical advisory transport entries collapse,
while distinct/conflicting records remain; canonical advisory validation order
prevents transport order from selecting different semantic errors; malformed object
internals are converted only at the caller-controlled boundary, while unexpected
programming attribute/type errors in evaluators are not hidden. Result wording
explicitly distinguishes structural availability from upstream factual lineage.

Provenance classes: VERIFIED_SOURCE_DATA is the upstream assertion of externally
verified source content; PERSISTED_APPLICATION_DATA only asserts application
storage; DERIVED_INTERPRETATION identifies transformed/interpreted content;
SEEDED_DEMO_DATA is synthetic demonstration evidence; UNVERIFIED has no adequate
verification assertion. Only exact-linked source-authored text with URL and the
verified classification becomes qualified context. Unlinked advisories remain
excluded context even when carrier text is present. T18 has no requested carrier
identity or carrier-routing relevance model. Derived text never becomes measured
operational support. A 40-case classification/linkage/authorship/URL matrix verifies
these distinctions and unchanged T08/T09 outputs.

Three availability states remain sufficient. UNAVAILABLE with an explicit
outside-methodology reason describes unsupported physical/operational capabilities,
not a runtime failure. NOT_APPLICABLE would add no useful distinction to v1.
Serialized gaps have string status/reason fields, never numeric or boolean defaults.

Boundary strictness rejects coercion and unsafe object representations, not new
market business conditions. Authoritative copied-evidence schemas accept missing,
negative, nonfinite and subcent monetary evidence; T18 preserves it for T08/T09
blocking/assessment. No new cents, freshness, expiry or supersession policy exists.
Future publication/observation/generation instants fail structural temporal checks;
future effective instants remain scheduled context without guessed expiry.

Advisory semantic equivalence includes timezone-equivalent instants. Every advisory
field and nested factual field is inventoried against schema introspection; changes
must affect identity or fail linkage validation. Every semantic result field except
the self-referential fingerprint contributes to hashing, including limitations,
availability and T09 evidence. Tests cover hostile Decimal precision/rounding/traps/
flags with exact caller-context restoration, signed zero and scale equivalence,
DST folds, microseconds, UTC bounds and controlled conversion overflow. Frozen
nested structures and detached serialized copies are tested.

Fresh processes prove lightweight import without DB/Redis/Celery/FastAPI/OpenAI
initialization, then guarded execution without filesystem/environment/network/
random/clock access. Existing full-output cross-process tests vary hash seeds and
host timezones. Unsupported cross-feature metadata has no generic passthrough:
scenario, legacy narrative/advice, predictive alert and port-value extras reject.
Current T08 returns WITHHOLD for deficient non-null forecasts and UNAVAILABLE only
without an artifact; direct parity is tested. A valid authoritative UNAVAILABLE
result is preserved if the evaluator supplies it; no synthetic business outcome
is created by T18.

Hardening focused result: 255 collected/passed, zero failed/skipped/errors, one
existing Pydantic deprecation warning. Required regressions and hardened full-suite
results are finalized below. No additional environment-blocked attempt occurred in
this phase; regression commands use permitted existing test-service access.


### Final hardening verification

The nine separate regression commands passed again: decision engine 78,
reliability 135, decision API 106, forecast state 25, forecast persistence 46,
forecast evaluation 59, evaluation persistence 49, predictive alert evaluator 159,
scenario intelligence 305. Each number is both collected and passed; failures,
skips and errors were zero. Each had one warning except scenarios (four).

Hardened full suite: 1,500 collected, 1,494 passed, six skipped, zero failed,
zero errors, five existing warnings (51.50 seconds).

Final complete file accounting against HEAD (all new, zero baseline deletions):
- schema: 104 lines (hardening delta 0);
- service: 203 lines (hardening delta +15);
- tests: 707 lines (hardening delta +325);
- report: 349 lines (hardening delta +102);
- total: 1363 additions, zero deletions (net hardening delta +442).

All eight protected fingerprints remain unchanged. Index is empty; tracked worktree
clean; main/HEAD/origin/main remain at the approved baseline, ahead/behind 0/0.
No staging, commit, push, migration, production generation, teammate contact or
T-FINAL work occurred. No unresolved defect requiring a pre-T18 change was found.
Final recommendation: READY TO STAGE, pending human authorization; not staged.
