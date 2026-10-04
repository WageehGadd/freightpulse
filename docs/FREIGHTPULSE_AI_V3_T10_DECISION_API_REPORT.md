# AI-V3-T10 — Decision API

## Scope and baseline

Implemented on main at HEAD/origin/main `6aed32b709fbffe80f341221750d0a2559ee7ec2`, initially 0 ahead/0 behind with an empty index and clean tracked worktree. Five new files: app/schemas/decision_api.py, app/services/decision_api.py, app/routers/decisions.py, tests/test_decision_api.py, and this report. Existing modifications: app/main.py for registration; app/services/forecast_persistence.py only after a mandatory independent-session test reproduced stale winner attributes. No other tracked file changed. Changes remain unstaged; no commit or push.

## Endpoint and authentication

Only GET /api/v1/decisions/latest is added. Required query strings: source, trade_lane, container_type. Missing, empty and whitespace-only selectors return 422. Matching is exact: no trimming, case folding, aliases, default container, optional unique-candidate resolution or arbitrary first-series selection. Container remains a string rather than a new global enum. No body, POST, list, forecast-ID or historical decision endpoint. Unknown extra query values do not override policy.

Normal active-user get_current_user authentication uses the existing X-API-Key dependency; admin is not required. Router-level RateLimiter() follows T06/T07: 100 calls per user/concrete path per 60-second fixed window, existing handled Redis failures fail open, excess returns 429. Rate-limiter Redis bookkeeping is separate from read-only decision-domain behavior. Auth/limiter implementations are unchanged.

Forecast generation remains explicit and admin-only through T06. Decision reading never generates or persists a forecast, outlook, decision or assessment.

## Authoritative composition

DecisionAPIService.latest selects the exact series through ForecastPersistenceService.get_latest_forecasts, copies immutable forecast evidence with snapshot_forecast, captures one UTC evaluation instant, collects ForecastStateCollector state with the expected series, constructs DecisionInput, calls evaluate_decision with the existing DecisionPolicy, calls assess_evidence, and maps into a dedicated public DTO.

No forecast selection, freshness, supersession, rule, metric-assessment or policy-threshold calculation is duplicated. The mapper copies authoritative state and computed signals; it does not use T06's float-converting presentation mapper. T08/T09 are unchanged. Their pure calculation and DTO construction run within a local Decimal context (precision 28, ROUND_HALF_EVEN), isolating arithmetic and Decimal/string validation flags from callers. The public response does not contain DecisionResult, EvidenceAssessment, input_snapshot, raw ORM objects, arbitrary persisted warnings or provider information.

T06 winner ordering is unchanged: latest_observation_date DESC, generated_at DESC, forecast_for_date DESC, model_name ASC, model_version ASC, UUID ASC; partitioned by source/lane/container. No fallback to an older eligible artifact when the winner is blocked.

## Public DTO

Top-level sections and fields:

- identity: source, trade_lane, container_type.
- forecast: forecast_id, predicted_rate, latest_actual_rate, latest_observation_date, forecast_for_date, forecast_horizon.
- decision: decision, actionable, movement, absolute_change, percentage_change, error_scale, movement_within_error_scale, ordered reasons, ordered limitations.
- evidence: historical_evidence_status, sample_sufficiency_status, decision_evidence_status; sample_evidence {history_observations, evaluation_points, data_readiness}; historical_error {mae, rmse, smape}; directional_evidence {directional_accuracy, valid_directional_sample_count}; normalized_signals {mae_relative_to_latest_actual_pct, rmse_relative_to_latest_actual_pct, movement_to_mae_ratio}; ordered factors and assessment_limitations.
- current_state: current_input_freshness, input_freshness_at_generation, latest_source_date, context_state, source_superseded, forecast_superseded, stored_live_decision_eligible, effective_live_decision_eligible.
- policy: movement_threshold_pct, min_history_observations, min_evaluation_points, error_multiplier, sorted supported_horizons.
- provenance: model_name, model_version, methodology_supported, generated_at, evaluated_at, engine_version, assessment_version.

Reasons, limitations and factors remain distinct. Factors expose dimension, code, kind, reference, observed, requirement and explanation. Frozen public DTOs use immutable ordered collections. Full internal snapshots are not repeated in evidence. Policy is copied once; no caller override is accepted by domain composition.

Versions remain separate: forecast model_version, T08 decision-rules-v1, T09 evidence-v1. Forecast UUID identifies an artifact whose generation can change; generated_at is therefore essential provenance.

## Business states and errors

T08 decision taxonomy remains CONSIDER_EARLIER_BOOKING, CONSIDER_LATER_BOOKING, MONITOR, WITHHOLD, UNAVAILABLE. Movement remains INCREASE, DECREASE, NEGLIGIBLE, UNDEFINED. The mapper copies actionable directly; schema validation enforces its correspondence to the two directional decisions. It does not invent a new actionable decision.

With a persisted forecast, valid WITHHOLD, MONITOR and directional results are HTTP 200. Missing source, superseded source/forecast/generation, stale data, expired target, insufficient evidence and ineligibility remain explanatory business blockers. Excellent historical metrics cannot promote them. Effective eligibility is not a substitute for checking decision/actionable: target expiry and other engine gates remain authoritative.

No persisted forecast returns 404: this does not claim that the underlying freight series is absent. No synthetic UNAVAILABLE is constructed. Artifact-backed UNAVAILABLE is an integrity failure, verified against the committed engine and tested with an injected impossible result.

Mappings:

- Missing/invalid auth: 401 through existing auth; revoked/inactive behavior remains the shared dependency's unchanged 401 semantics.
- Excess rate limit: 429 through existing limiter.
- Invalid/missing/partial/empty/whitespace-only selectors: 422 through FastAPI request validation.
- Exact series without a forecast: 404.
- Valid blocked/monitor/directional or unsupported-methodology result: 200.
- Representable deficient evidence: 200 with T08 blockers and T09 evidence status.
- EvidenceInputError, PolicyConfigurationError, snapshot validation, naive provenance/application time, impossible composition and database/unexpected failures: sanitized 500.

No 409 is used for stale or superseded read state. Explicit HTTP errors retain the application's existing {error: {code, message, details}} envelope. T10's explicit 500 uses inherited code ERROR and generic text; raw exceptions are never returned. Framework 422 retains its existing validation response. Global error handling, status-code names and header forwarding were not redesigned.

## Evidence semantics and serialization

Historical statuses: UNAVAILABLE, INVALID_OR_INCOMPLETE, UNSUPPORTED, AVAILABLE. Sample statuses: NOT_ASSESSABLE, LIMITED, POLICY_MINIMUMS_MET. Decision evidence: UNAVAILABLE, BLOCKED, MONITOR_ONLY, DIRECTIONAL_RULES_PASSED. No-artifact UNAVAILABLE is an internal taxonomy, not a successful response for the latest-resource absence path.

AVAILABLE means valid historical evidence is available, not accuracy. POLICY_MINIMUMS_MET means copied heuristic policy minimums are met, not statistical validation. DIRECTIONAL_RULES_PASSED means T08 rules passed, not a correctness probability. Unknown methodology preserves the reviewed T08 outcome while T09 marks UNSUPPORTED; T10 introduces no methodology gate.

Money, movement, percentage change, error scale, Decimal policy values and normalized ratios serialize as exact decimal strings, never through float. Finite persisted backtest metrics remain JSON numbers; invalid metrics become null. Non-finite monetary evidence becomes null, with the existing T08 INVALID_RATE blocker. Public schemas disallow non-finite numbers. No NaN/Infinity sentinel semantics, rounding for presentation, score, confidence or probability field is introduced.

Normalized formulas remain T09's 100 * MAE / actual, 100 * RMSE / actual, and abs(copied T08 absolute_change) / MAE. Invalid/nonpositive denominators yield unavailable ratios; zero MAE does not produce infinite evidence. No normalized-ratio quality threshold exists.

Supported methodology remains exactly baseline-v1-decimal with Naive, MA(2), MA(3), MA(4), Drift. Selection-window non-independence and unavailable directional denominator remain explicit. valid_directional_sample_count is always null, never inferred from evaluation_points. Walk-forward targets are out-of-sample relative to their prefixes, but the champion is selected and reported on the same evaluation window; no independent post-selection holdout is recorded.

Cutoff and target serialize as ISO dates. generated_at/evaluated_at must be timezone-aware, normalize to UTC, and serialize with explicit UTC indication (Z). Naive authoritative timestamps fail rather than being silently reinterpreted.

## Cache, observability and performance

Successful responses include Cache-Control: no-store. There is no decision cache or additional Redis access. Error-header behavior remains the existing application convention; no global middleware was added. Freshness, source currency, expiry and regeneration can change independently of UUID.

Structured events record fixed endpoint, HTTP status, latency, decision, actionable, evidence statuses, freshness and supersession flags. Success includes forecast UUID as log context; no unbounded metric labels or metrics framework were added. Failure logs use exception class only, not exception text, stack traces, headers or internal snapshots. Auth/validation/limiter logging retains shared behavior.

The tested clean-session successful current-source domain path performs three SELECTs: winner selection, exact-series source MAX, then collector winner query. A missing forecast stops after selection. Missing/newer source short-circuits the collector's winner query. Auth has its own reads; short-circuit paths perform fewer queries, and unrelated pending writes in other callers can add autoflush statements. This is a measured path, not a universal query-count guarantee. No mapper query or duplicate freshness query is added. One request-scoped evaluation timestamp is reused by collector, engine and provenance; the pure assessment uses the engine timestamp.

## Mandatory cross-session characterization

Before any shared production change, an isolated integration test used Session A's loaded exact-series winner, copied its evidence, then used independent Session B to regenerate that same UUID by committing a changed generated_at and predicted_rate. Session A then repeated the authoritative winner read. The initial test failed: generated_at remained the old value despite B's committed update. This reproduced identity-map stale attribute reuse without mocks.

The minimal fix applies stmt.execution_options(populate_existing=True) to get_latest_forecasts execution. It refreshes selected ORM scalar values from the query, preserves all existing ranking/filter/order logic, adds no query and introduces no lock. The original characterization then passed, including immutable old-snapshot supersession detection. Additional real two-session HTTP tests regenerate or add a different winner between selection and collection: the response retains copied old forecast evidence and returns HTTP 200 WITHHOLD with supersession/effective-ineligibility.

T06 list/read shapes and T07 paths/contracts remain unchanged. T08/T09 semantics are unchanged. Existing T06/T07/T08 regressions pass. Winner attributes reflect the database view available to the transaction. Normal SQLAlchemy autoflush is preserved: an independent-session test verifies a pending local monetary change is flushed, not discarded, and not implicitly committed (Session B still sees the original committed value). Reads can therefore include their own flushed writes; there is no universal committed-only guarantee. Audited T06/T07/state/T10 read paths contain no pending RateForecast mutations; the existing generation upsert commits before subsequent reads.

This is not transactionally locked or linearizable evaluation. Writes can still occur after collection or between independent reads. Same-date source corrections remain undetected by cutoff-only recency. No new locking/persistence/snapshot-isolation protocol is claimed.

## Tests and runtime

All commands below were executed independently. Counts are collected / passed / skipped / failed / errors:

- .venv/bin/pytest tests/test_decision_api.py: 106 / 106 / 0 / 0 / 0 (repeated independently with the same result).
- .venv/bin/pytest tests/test_reliability.py: 135 / 135 / 0 / 0 / 0.
- .venv/bin/pytest tests/test_decision_engine.py: 78 / 78 / 0 / 0 / 0.
- .venv/bin/pytest tests/test_forecast_state.py: 25 / 25 / 0 / 0 / 0.
- .venv/bin/pytest tests/test_grounded_rate_outlook.py: 49 / 49 / 0 / 0 / 0.
- .venv/bin/pytest tests/test_forecast_persistence.py: 46 / 46 / 0 / 0 / 0.
- .venv/bin/pytest tests/test_baseline_forecasting.py: 7 / 7 / 0 / 0 / 0.
- .venv/bin/pytest tests/test_data_quality.py: 8 / 8 / 0 / 0 / 0.
- .venv/bin/pytest tests/test_ai/: 75 / 75 / 0 / 0 / 0.
- .venv/bin/pytest tests/: 673 / 667 / 6 / 0 / 0.

Characterization initially collected 1 / passed 0 / skipped 0 / failed 1 / errors 0, intentionally exposing the defect; the same test passed after correction. Intermediate focused runs passed 59 and 65 tests before final boundary additions. Final counts above are authoritative. Warnings were unsuppressed: existing Pydantic class-based Config deprecation; full-suite existing Redis asyncio destructor Event loop is closed warning in test_acquire_pipeline_lock. No new warning introduced.

Tests use established isolated DB fixtures with real normal-user authentication and real T06/T08/T09 composition. Redis transport is isolated via a test-local mock, covering rate-limit and handled outage behavior. Tests verify all business outcomes, selectors, absent resources, metric/sample statuses, exact serialization, policy non-overrides, no fallback, one clock, three read-only domain queries, Decimal context isolation, privacy, error sanitization and cross-session supersession. Failures are injected only at external/invariant boundaries. Fresh subprocess tests import T10 composition and router with GPT/Azure/Celery/T07 imports blocked; router import also traps database connections. The full existing application retains pre-existing provider/worker imports; no application-wide import-isolation claim is made. Generation/narration calls are trapped on successful and absent reads; forecast/outlook row counts show no generation.

Read-only production transaction on October 4, 2026 reconfirmed FreightRate=248, RateForecast=0, RateOutlook=0. Current exact-series decision resource is therefore absent (404), not synthetic UNAVAILABLE. No production forecast/outlook was generated. No live production-key HTTP request was needed; authenticated 404 behavior is verified in isolated HTTP tests. Positive responses were demonstrated exclusively with isolated fixtures.

## Final hardening review

Two defects were reproduced and corrected within the approved files. Python treats U+001C through U+001F as whitespace, while the original regex accepted them; all three selectors now require a character outside Unicode whitespace and those four controls, without transforming valid identities. Direct public DTO mapping could set the caller's Decimal InvalidOperation flag; the public helper now isolates Decimal settings and flags, as HTTP composition already did. No rule, assessment or policy changed.

The initial regression subset produced 13 failures and 6 passes: twelve control-only selector cases and one mapper-context case failed. An annotated-validator attempt was ineffective with installed FastAPI Query handling (101 collected, 89 passed, 12 failed), and was replaced by the tested query pattern. An intermediate corrected run passed 103 tests; final 106-test runs passed twice. Forty cases were added to the original 66: Unicode/control whitespace, standalone mapping context, independent-session new-row selection, normal autoflush, Decimal edges, freshness/eligibility parity, router import isolation, recursive schema restrictions, safe error logs and neighboring-series isolation.

Same-ID regeneration and new-row winner tests use independent sessions and real commits. HTTP race tests retain old immutable copied evidence and report supersession rather than mixing generations. These are bounded characterizations, not protection against writes after collection. Decimal serialization covers zero, signed zero, very small values, Numeric-range values and trailing zeros without cosmetic rounding.

T10-owned failure logs use a bounded exception-class field, never injected exception text. Shared auth/Redis/global-handler logging is outside that claim and unchanged. Established isolated database fixtures clean up rows and dependency overrides; limiter transport mocking is local to the test module. Repeated focused tests and the full suite pass. OpenAPI exposes only the single new GET with three required string selectors and the dedicated response schema. No production generation, teammate contact or scope expansion occurred during hardening.

## Claims, limits and handoff

Safe claims: deterministic booking decision support, evidence-backed API, explicit blockers, read-time freshness/source-currency checks, forecast/model provenance, decomposed historical evidence and an LLM-independent deterministic path. No optimal booking, guaranteed savings, calibrated confidence, correctness probability, statistically validated recommendation, causal savings or validated live-advice claim.

Remaining limitations include read-time races, same-date corrections, local hardcoded next-day targets with no verified daily SCFI publication semantics, baseline-only characterized methodology, unavailable directional denominator, no holdout/calibration and heuristic policy. Current baseline generation remains stored-ineligible. Frontend source is absent here; a shared browser-exposed API key remains non-blocking production-auth debt. Public decisions do not accept policy overrides.

Team impact: AI-only schemas/composition/tests; backend internal router registration and tested winner refresh (defer handoff); frontend future T12 forecast, T13 decision-card and T16 evidence-panel consumption (defer handoff). No immediate RED blocker or teammate notification required. No frontend, T11 evaluation/calibration, model, migration, worker, prompt or scheduling change.

Protected unrelated files remain unchanged/untracked. Index remains empty, HEAD/origin unchanged, and only approved T10 files changed. READY TO STAGE. No stage, commit or push.
