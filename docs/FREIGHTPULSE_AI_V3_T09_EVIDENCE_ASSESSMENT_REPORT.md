# AI-V3-T09 — Evidence Assessment & Explainability

## Scope and baseline

Implemented on main with HEAD and origin/main at `2edd984ea0841b6ca77d52aefea63fbd0942691c`. Exactly four new files: app/schemas/reliability.py, app/services/reliability.py, tests/test_reliability.py, and this report. No existing production or test file was modified. All changes remain untracked/unstaged; no commit or push performed. No T10/T11 work.

## Evidence Assessment, not confidence

T09 describes available evidence and its limitations, not forecast correctness. There is no confidence percentage, aggregate 0–100 score, weighted reliability score, probability, learned model, quality cutoff or optimization. Descriptive metrics cannot establish calibrated correctness. POLICY_MINIMUMS_MET does not mean statistically validated. DIRECTIONAL_RULES_PASSED does not mean probability of correctness. AVAILABLE historical evidence does not mean high reliability.

`assess_evidence(decision_result)` consumes the completed immutable T08 DecisionResult and returns a frozen EvidenceAssessment with semantic version `evidence-v1`. It preserves the original result, engine version `decision-rules-v1`, complete policy, reasons, limitations, input snapshot, identity, and evaluated_at. It does not call T08 again, recalculate any decision, read the clock, query state, recalculate freshness, determine supersession, or promote eligibility. Assessment current_state is exactly the copied T08 state.

## Exact status semantics

HistoricalEvidenceStatus:

- UNAVAILABLE: no forecast artifact/snapshot exists.
- UNSUPPORTED: model name/version is outside the explicitly characterized methodology.
- INVALID_OR_INCOMPLETE: supported artifact exists but a required metric/count is missing or invalid, or there are zero history/evaluation samples to support performance aggregates.
- AVAILABLE: supported methodology has valid descriptive historical metrics and positive valid counts, without any performance-quality threshold.

Precedence is no artifact, unsupported methodology, incomplete historical evidence, available. Unknown methodology plus invalid metrics is UNSUPPORTED, with the invalid-evidence factor also retained. Invalid rates do not erase otherwise valid historical metrics; they prevent applicable normalized ratios and T08 already owns the safety result.

SampleSufficiencyStatus:

- NOT_ASSESSABLE: counts missing, noninteger, boolean, or negative.
- LIMITED: valid nonnegative counts exist but at least one copied policy minimum is not met.
- POLICY_MINIMUMS_MET: both counts meet the exact recorded T08 policy.

Zero counts remain valid for sample-policy comparison, but cannot establish available historical performance aggregates. Default T08 requirements are 100 history observations and 30 evaluation points; T09 introduces no minimum. Custom recorded policy is honored. Readiness is exposed unchanged, not recategorized or described as accuracy.

DecisionEvidenceStatus maps only T08 decision:

- UNAVAILABLE → UNAVAILABLE.
- WITHHOLD → BLOCKED.
- MONITOR → MONITOR_ONLY.
- Either conditional directional suggestion → DIRECTIONAL_RULES_PASSED.

No separate actionable field is added. Historical performance or methodology support cannot alter the mapping. A future unknown model can therefore retain T08's original directional outcome while T09 explicitly marks historical methodology UNSUPPORTED; this is not T09 endorsement.

## Typed dimensions and reproducibility

EvidenceAssessment retains the original immutable DecisionResult and contains evaluated_at, three statuses, sample_evidence, historical_error, directional_evidence, current_state, decision_margin, provenance, ordered factors, and assessment_limitations.

Sample evidence records sanitized counts, unchanged readiness, and sample status. Historical error records valid MAE/RMSE/sMAPE and three optional Decimal ratios. Directional evidence records the valid historical percentage with valid_directional_sample_count fixed to None. Invalid metrics sanitize to None in descriptive dimensions; the original result retains its original evidence losslessly in memory. JSON serialization represents non-finite raw Decimal/float evidence as null, avoiding NaN/Infinity tokens or sentinel strings; finite Decimal values remain decimal strings. Invalid raw evidence is therefore intentionally not losslessly round-tripped through JSON. Model provenance records forecast ID, model/version, generated_at, cutoff, target, horizon, and methodology_supported. Exact series, generation freshness, warning, stored eligibility, T08 reasons/limitations and full policy remain available in the retained result, avoiding new taxonomies for them.

Decision margin contains the copied T08 Signals, threshold, error multiplier, and a descriptive abs(change) <= copied error_scale comparison. This comparison does not run a new decision guard, including for negligible movement; the original decision explains the guard's actual role. Missing/nonfinite signals or negative error scale yield no comparison. No new margin thresholds.

All assessment structures are frozen; collections are tuples, and methodology model sets are frozensets. Nested original T08 models remain frozen. The evaluator does not mutate its input, and repeated input produces identical output. Assessment construction and ratios run inside a local Decimal context with precision 28 and half-even rounding. This isolates both arithmetic and Pydantic Decimal/string union-probing flags; caller precision, rounding, traps and flags remain unchanged.

## Numerical evidence and validation

MAE and RMSE must be finite, nonnegative numeric values. sMAPE must be finite in 0..200, matching T04's average-absolute-value denominator. Directional accuracy must be finite in 0..100. Boolean numeric values are not accepted. None/NaN/Infinity/negative/out-of-range values produce structured deficient evidence, not performance grades. Individual valid metrics may remain visible when another required metric is invalid.

Approved descriptive signals:

- mae_relative_to_latest_actual_pct = 100 × MAE / latest actual.
- rmse_relative_to_latest_actual_pct = 100 × RMSE / latest actual.
- movement_to_mae_ratio = abs(copied T08 absolute_change) / MAE.

Metric conversion is Decimal(str(value)), never Decimal(float_value). Monetary values remain Decimal. Invalid/nonpositive actual makes rate-relative ratios unavailable. Zero/invalid MAE makes movement/MAE unavailable, never infinite evidence. Missing/invalid T08 movement makes movement/MAE unavailable. No ratio is called confidence, calibration, correctness, or a quality score; no threshold is applied. These current-rate normalizations do not establish complete cross-series comparability.

## Methodology and limitations

The centralized immutable SUPPORTED_METHODOLOGIES declaration recognizes exactly `baseline-v1-decimal` with Naive, MA(2), MA(3), MA(4), and Drift. It matches T04/T06 identifiers without importing their database/pandas dependency graph. Future models/versions are explicitly unsupported until assessed and versioned. Material changes to formulas, status/factor semantics or support rules require an assessment-version bump; T08 version is separate.

T04 uses expanding walk-forward predictions (default training prefix 15). Each fold predicts without its target in the training prefix. However, the same evaluation window compares/selects the champion and reports its historical metrics. No independent post-selection holdout is recorded. SELECTION_WINDOW_NOT_INDEPENDENT is a required limiting factor for supported methodology. This does not make the backtest invalid or useless; it remains descriptive evidence, not independent post-selection validation.

T04 excludes both-flat directional cases, counts one-flat/one-moving as incorrect, and counts matching nonzero directions as correct. Its valid-direction denominator is transient and not persisted in T06/T08. DIRECTIONAL_DENOMINATOR_UNAVAILABLE is explicit; valid_directional_sample_count is None. Evaluation points are never substituted. Stored zero accuracy may mean zero correctness or no defined directional cases. This percentage is not a next-period probability.

No prediction/confidence intervals, residual quantiles, bootstrap, conformal computation, calibration, empirical coverage or independent-validation substitute is implemented. T04 per-fold predictions/errors exist transiently, not in the assessment snapshot. Those research/evaluation concerns belong to T11/data-gated work.

## Factors and authoritative safety

Factor kinds: SUPPORTING, LIMITING, INFORMATIONAL. Each frozen factor contains dimension, code, reference, optional observed/requirement, and short deterministic explanation.

Codes: METHODOLOGY_UNSUPPORTED; HISTORICAL_EVIDENCE_INVALID_OR_INCOMPLETE; POLICY_SAMPLE_MINIMUM_MET; POLICY_SAMPLE_MINIMUM_NOT_MET; SAMPLE_COUNTS_INVALID_OR_UNAVAILABLE; NORMALIZED_ERROR_AVAILABLE; NORMALIZED_ERROR_UNAVAILABLE; SELECTION_WINDOW_NOT_INDEPENDENT; DIRECTIONAL_DENOMINATOR_UNAVAILABLE.

Explicit order: unsupported methodology, invalid historical evidence, sample assessment, normalized MAE/RMSE/movement signals, selection limitation, directional limitation. Exactly one sample outcome factor is emitted. Exactly one availability factor per normalized signal reference is emitted, preventing contradictory pairs. Meeting sample minimums is a neutral supporting policy fact, not strong statistical support. Poor numerical performance does not change availability status. Limitation order is selection-window then directional-denominator when applicable.

T08 safety reasons are not duplicated. Its reasons, limitations, movement, signals and policy remain authoritative and explain BLOCKED/MONITOR_ONLY/directional outcomes. Excellent historical metrics cannot erase stale/superseded/model-ineligible conditions or change actionable. Historical evidence can be AVAILABLE while current decision evidence is BLOCKED; this separation is intentional.

## Purity, failures and boundaries

Production imports are standard-library math/Decimal and immutable schema definitions only. No database/SQLAlchemy, Redis, GPT/OpenAI, Azure, Celery, narrator, RateTrend, RateOutlook, router, or clock dependency. Offline behavioral testing imports/evaluates in a fresh process while provider/infrastructure/model/router/task imports are blocked. No persistence, migration, endpoint or scheduler.

Expected evidence deficiencies yield structured statuses/factors. Missing/non-DecisionResult input or inconsistent forecast identity versus input snapshot raises typed EvidenceInputError. The completed-result boundary also rejects invalid outcome/actionable pairs, UNAVAILABLE with an artifact (or a non-UNAVAILABLE outcome without one), and malformed non-string model identifiers. MONITOR/directional outcomes must not contradict copied hard-blocking reasons, stored/effective eligibility, series identity, source availability, forecast/generation identity, evaluation instant, supersession flags, freshness category, required metric validity or recorded sample minimums. These checks reject inconsistent callers; they never repair, demote, promote, or rerun the T08 decision. Unknown well-formed model/version strings remain UNSUPPORTED, not caller errors. Blocked snapshots with deficient metrics/counts remain assessable. This is not exhaustive revalidation of all T08 monetary/temporal calculations: T08-produced typed snapshots remain the authoritative input contract. Programming errors are not broadly caught and reclassified as limited evidence. Infrastructure exceptions cannot originate from I/O inside the pure evaluator because it performs none.

T10 later owns public selection/authentication/API/HTTP serialization and composition. T11 owns independent holdouts, residual retention, expanded/regime evaluation, coverage/calibration, outcome studies, challenger evaluation and policy tuning. T07 is unchanged; no T09 evidence is sent to GPT.

## Runtime reality

Read-only audit established FreightRate=248, RateForecast=0, RateOutlook=0; eight exact SCFI series have 31 distinct local stored observations each, August 3–September 2, 2026, MINIMAL readiness and stale freshness. Implementation does not generate forecasts or modify runtime data. Current persisted availability is UNAVAILABLE.

Hypothetical T06 artifacts from that data would have 16 default evaluation points: historical evidence AVAILABLE if valid/supported, sample LIMITED, decision BLOCKED for the T08 stale/minimal/insufficient/model-ineligible/expired context. This is not a claim that such artifacts currently exist. Baseline forecasts remain stored-ineligible; extra history cannot promote them. Same-date source corrections, local +1-day targets and unverified external daily-history semantics remain T08 limitations.

## Validation record

Every command below was executed independently using the existing .venv environment (database regressions use the established isolated test database). Counts: collected / passed / skipped / failed / errors.

- .venv/bin/pytest tests/test_reliability.py: 135 / 135 / 0 / 0 / 0.
- .venv/bin/pytest tests/test_decision_engine.py: 78 / 78 / 0 / 0 / 0.
- .venv/bin/pytest tests/test_forecast_state.py: 25 / 25 / 0 / 0 / 0.
- .venv/bin/pytest tests/test_grounded_rate_outlook.py: 49 / 49 / 0 / 0 / 0.
- .venv/bin/pytest tests/test_forecast_persistence.py: 46 / 46 / 0 / 0 / 0.
- .venv/bin/pytest tests/test_baseline_forecasting.py: 7 / 7 / 0 / 0 / 0.
- .venv/bin/pytest tests/test_data_quality.py: 8 / 8 / 0 / 0 / 0.
- .venv/bin/pytest tests/test_ai/: 75 / 75 / 0 / 0 / 0.
- .venv/bin/pytest tests/: 567 / 561 / 6 / 0 / 0.

Initial focused invocation collected 69: 67 passed, 2 failed, no skips/errors, due to duplicate model_version keywords in the new test helper. The helper was corrected; three additional meaningful tests cover ambient Decimal context independence, structural input errors, and unsupported/invalid status precedence. Those were initial implementation results. During final hardening, a focused run collected 125: 124 passed and one failed, exposing a real Decimal InvalidOperation flag leak. After isolating construction in localcontext, an intermediate run passed 130 tests; final independent commands above are authoritative.

Warnings were not hidden: existing Pydantic class-based Config deprecation in all suites; existing Redis asyncio destructor Event loop is closed warning in full-suite test_acquire_pipeline_lock. No new schema warning was introduced.

Tests cover all status mappings, supported registry, missing/nonfinite/boolean/range-invalid metrics, exact/custom sample policy, invalid counts, normalized Decimal values, denominator edge cases, stale/aging/unknown/superseded/ineligible state, excellent metrics with blockers, limitations/factor ordering, immutability/versioning, absent unsupported schema semantics, and behavioral offline independence.

## Claims, team impact and final state

Supported claims: deterministic Evidence Assessment, decomposed historical evidence, transparent policy sample sufficiency, explicit copied freshness/currency, application-owned factors, methodology limitations, LLM independence, and preserved authoritative safety blockers. No calibrated confidence, correctness probability, guaranteed savings, optimal timing, causal quality, or statistically validated live-advice claim.

AI-only ownership: schemas, pure service, factors, tests. Backend: future T10 composition only. Frontend: future T13/T16 presentation. No breaking teammate action and no teammates contacted. Remaining limitations include selection bias, unavailable directional denominator, missing independent holdout/calibration, baseline-only methodology support, and inherited T08 data/cadence limitations.

Protected unrelated files remain unchanged/untracked. No tracked modifications or staged files; only the four new scoped T09 files. Whitespace checks include every untracked file. READY TO STAGE. No stage/commit/push or T10/T11 work.


## Final hardening evidence

Three correctness defects were fixed within these four new files: acceptance of contradictory completed T08 outcomes; non-finite raw Decimal serialization as NaN/Infinity strings; and a caller Decimal flag leak caused by schema union validation. The selection-factor explanation now explicitly includes prefix out-of-sample walk-forward folds, the shared champion-selection/reporting window, and absent independent post-selection holdout. No existing tracked file changed.

Additional tests exercise impossible copied safety/evidence inputs, both count types, negative-infinity metrics, exact case/whitespace methodology matching, three serialized versions, JSON null sanitation with retained original evidence, caller-container isolation, full Decimal-context preservation, extreme finite ratios, copied zero/tiny movement, and hash-seed-independent factor ordering. Offline import blocking also includes HTTP clients. Assertions target observable contracts; no infrastructure is mocked into the pure computation. Arbitrary corruption of every nested model via unchecked model_construct/model_copy is not an alternate supported input protocol.

Factor inventory (none duplicates T08 safety reasons):

- METHODOLOGY_UNSUPPORTED: METHODOLOGY / LIMITING; unknown exact name/version; excludes baseline selection-window limitation.
- HISTORICAL_EVIDENCE_INVALID_OR_INCOMPLETE: HISTORICAL_ERROR / LIMITING; any required metric/count invalid or zero samples; absent for AVAILABLE historical evidence (can coexist with UNSUPPORTED).
- POLICY_SAMPLE_MINIMUM_MET: SAMPLE / SUPPORTING; both valid counts meet copied policy; excludes both other sample outcomes.
- POLICY_SAMPLE_MINIMUM_NOT_MET: SAMPLE / LIMITING; valid counts fall below either policy minimum; excludes both other sample outcomes.
- SAMPLE_COUNTS_INVALID_OR_UNAVAILABLE: SAMPLE / LIMITING; missing/noninteger/boolean/negative count; excludes both other sample outcomes.
- NORMALIZED_ERROR_AVAILABLE: HISTORICAL_ERROR / INFORMATIONAL; one computable descriptive ratio; excludes unavailable for that same reference.
- NORMALIZED_ERROR_UNAVAILABLE: HISTORICAL_ERROR / LIMITING; invalid/missing input or nonpositive denominator; excludes available for that same reference.
- SELECTION_WINDOW_NOT_INDEPENDENT: METHODOLOGY / LIMITING; supported baseline artifact; excludes unsupported-method factor.
- DIRECTIONAL_DENOMINATOR_UNAVAILABLE: DIRECTIONAL / LIMITING; any forecast artifact; denominator remains None even when the accuracy metric is invalid. No available-denominator factor exists.

With no artifact, factors and assessment limitations are empty. Ordered status precedence and distinct dimensions avoid contradictory availability claims. No aggregate evidence score exists. No clock, random, environment, database, provider or HTTP dependency is introduced. Regression tests use only the established isolated test environment; production runtime was not queried again or modified and no production forecast was generated.
