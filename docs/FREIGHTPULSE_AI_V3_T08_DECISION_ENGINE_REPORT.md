# AI-V3-T08 — Deterministic Decision Engine

## Scope and baseline

Implemented against main at `f9fd2a71164eab578454f89cc354c9857fd9575d`, also origin/main. All T08 changes are working-tree changes, unstaged. No API, persistence, migration, model, prompt, task, frontend, Azure, Redis, or runtime-data changes. T09/T10 remain deferred.

New files: app/schemas/decision.py, app/services/decision_engine.py, app/services/forecast_state.py, tests/test_decision_engine.py, tests/test_forecast_state.py, and this report. Modified: app/services/rate_outlook.py only.

## Architecture and reproducibility

The pure `evaluate_decision(input_snapshot, policy, evaluated_at)` function accepts frozen Pydantic evidence and state structures. It performs no I/O, imports only standard-library calculation helpers and the internal decision schema, and has no ORM, RateTrend, RateOutlook, GPT, Azure, Redis, BudgetGuard, or Celery dependency. No decision is persisted. Expected evidence deficiencies produce structured non-actionable results; invalid policy raises PolicyConfigurationError. Collector database exceptions propagate rather than becoming UNAVAILABLE.

The result carries decision, actionable, movement, ordered reasons, Decimal signals, separate static limitation codes, forecast identity/evidence, UTC evaluated_at, semantic engine_version `decision-rules-v1`, complete effective policy, and input_snapshot. There are no confidence, probability, or score fields. Nested models are frozen; reasons/limitations are tuples and supported horizons a frozenset. The copied forecast includes exact series, ID, target, prediction, model/version/horizon, cutoff, actual, history/evaluation counts, all four metrics, readiness, generation freshness, stored eligibility, warning, and generated_at. Current state records source date, winner ID/generation, separate supersession flags, freshness, and effective eligibility. Mutation of an ORM row after copying does not change the snapshot; re-evaluation uses those copied values.

## Shared forecast state and T07 parity

ForecastStateCollector operates only on an explicitly identified forecast snapshot. MAX(FreightRate.rate_date) filters source, trade_lane AND container_type. Latest selection delegates to T06 ForecastPersistenceService.get_latest_forecasts, preserving cutoff DESC, generated_at DESC, target DESC, model name ASC, model version ASC, UUID ASC. A newer exact-series observation supersedes source evidence. A different deterministic winner, missing winner, or changed generation supersedes the forecast. Same-ID regeneration invalidates an older snapshot. Same-date source corrections remain undetectable with current provenance.

Freshness and effective eligibility use a shared helper delegating to T02 DataQualityService. T02 uses a seven-day cadence: age/cadence <=1.5 fresh, <=3 aging, otherwise stale. generated_at cannot refresh source age. Effective eligibility is stored eligibility AND fresh/aging AND current context; false is never promoted. T08 additionally applies all evidence and temporal gates.

T07 context_state now delegates forecast checks to the collector; trend-specific historical/mismatch checks remain in T07. Its warning precedence and messages are retained. Read-time freshness/effective eligibility delegate to the shared helper using the immutable original outlook evidence, preserving generation safety even if the forecast row is subsequently updated. Persistence identity, exact values, API, prompt v2, narration, retry/cooldown, worker claims, Azure and cache behavior are unchanged. The existing 49 grounded outlook tests pass, including historical evidence, freshness, source/generation supersession, failed narration and retries.

## Taxonomies and rules

Movement is INCREASE, DECREASE, NEGLIGIBLE, or UNDEFINED. Decision is CONSIDER_EARLIER_BOOKING, CONSIDER_LATER_BOOKING, MONITOR, WITHHOLD, or UNAVAILABLE. Only the two conditional directional suggestions are actionable. MONITOR means gates passed but movement is below threshold. WITHHOLD preserves the existence of a blocked artifact. UNAVAILABLE means no forecast input, with NO_FORECAST.

Policy defaults: movement_threshold_pct Decimal("2.0"), min_history_observations 100, min_evaluation_points 30, error_multiplier Decimal("1.0"), supported_horizons {1}. Threshold and multiplier must be finite/positive, evidence minimums nonnegative, horizons nonempty/positive. Configuration is revalidated before evaluation. The 2%, 30-point and MAE multiplier defaults are transparent heuristics. The 100-observation default aligns with T03 BASELINE_READY, not proof of forecast accuracy. Policy changes cannot bypass stored eligibility, freshness, supersession or other hard gates.

Absolute change is predicted minus actual; percentage is change/actual*Decimal(100). Unrounded Decimal values determine boundaries. Equality at +threshold increases, equality at -threshold decreases. Invalid/nonpositive actual or prediction blocks; undefined movement accompanies invalid rates. After all gates pass, negligible movement yields MONITOR. Directional movement with abs(change) <= MAE*multiplier yields WITHHOLD/MOVEMENT_WITHIN_ERROR_SCALE. Equality is blocked. This is a conservative heuristic error-scale guard, not a confidence interval, significance test, calibration, or next-period probability. Directional accuracy remains evidence only, with no arbitrary minimum.

Hard gates accumulate in fixed order: series mismatch; unavailable source; source/winner/generation supersession; stale/unknown freshness; model ineligibility; insufficient readiness; insufficient/negative history; insufficient/negative evaluation; invalid rates; missing/nonfinite/negative/out-of-range metrics; unsupported horizon; expired target; invalid temporal context. Readiness must be BASELINE_READY or EXTENDED_HISTORY independently of history minimum. MAE/RMSE must be finite >=0; sMAPE 0..200 matches T04's average-absolute-value denominator; directional accuracy 0..100. Aging is allowed but appended as informational AGING_INPUT. Results do not infer a historical-only cause merely from a false flag.

Current local temporal contract is horizon 1 and target=cutoff+1 calendar day, hardcoded, not inferred external SCFI cadence. UTC evaluated date >target expires; equality alone does not expire. Future cutoff, inconsistent target/horizon, or state collected at a different evaluation instant blocks. Weekly/irregular datasets require revisiting the contract. T02 freshness itself is unchanged.

Reason codes: NO_FORECAST, SERIES_MISMATCH, SOURCE_UNAVAILABLE, SUPERSEDED_FORECAST, STALE_INPUT, UNKNOWN_FRESHNESS, MODEL_INELIGIBLE, MINIMAL_READINESS, INSUFFICIENT_READINESS, INSUFFICIENT_HISTORY, INSUFFICIENT_EVALUATION, INVALID_RATE, INVALID_METRICS, UNSUPPORTED_HORIZON, EXPIRED_TARGET, INVALID_TEMPORAL_CONTEXT, FORECAST_INCREASE, FORECAST_DECREASE, MOVEMENT_BELOW_THRESHOLD, MOVEMENT_WITHIN_ERROR_SCALE, AGING_INPUT.

Separate limitation codes: HEURISTIC_MOVEMENT_THRESHOLD, HEURISTIC_EVALUATION_MINIMUM, HEURISTIC_ERROR_SCALE, BASELINE_MODEL_ONLY, SAME_DATE_CORRECTIONS_UNDETECTED, LOCAL_TARGET_CADENCE. These describe interpretation, not additional blockers.

## Tests and runtime

Sensitivity tests sweep thresholds 1/2/3% and MAE multipliers 0.5/1/1.5 on synthetic evidence. Positive/negative movement is symmetric, Decimal equality is explicit, increasing thresholds does not create additional actions, and safety blockers remain blockers across thresholds. This tests rule sensitivity, not model performance or policy optimization.

Each command was executed independently with the existing .venv runtime and isolated test database. Final results are recorded below. No warnings were filtered. The existing Pydantic class-based Config deprecation remains; the new schema's model_ namespace warnings were corrected. Docker read-only verification also reports the existing compose version attribute warning.

Runtime read-only check: rate_forecasts=0, rate_outlooks=0, freight_rates=248. No forecasts generated and no runtime data changed. Thus current persisted evaluation is UNAVAILABLE. The known eight 31-observation local series would remain WITHHOLD if T06 generated artifacts: minimal evidence, stale source, and stored model ineligibility cannot be promoted for demonstration.

## Claims, limitations and team impact

Supported claims: application-owned deterministic rules, reproducible copied evidence, explicit conservative safety gates, structured reasons, quantitative evidence, LLM-independent decisioning. No claim of optimal booking, savings, causal advice, calibrated probability/confidence, learned policy, verified daily SCFI history, or validated live booking advice. Thresholds are not empirically optimized; current baseline artifacts remain model-ineligible. Same-date corrections and local target cadence are known limits. The collector is a read-time check, not a transactionally locked decision/persistence workflow.

T09 reliability/calibration concerns and T10 public selection/authentication/API concerns are deferred. AI owns rules/schema/tests. Backend internal impact is the shared state extraction; no breaking teammate action is required. Frontend has no current change; T10 may later consume this internal contract. No teammates contacted.

All eight protected unrelated files retain their original SHA256 fingerprints. Index remains empty. No commits or pushes performed. Final recommendation is subject to the final test and Git verification recorded below.

## Final validation record

All invocations use `.venv/bin/pytest` followed by the listed argument. Counts are collected / passed / skipped / failed / errors:

- tests/test_decision_engine.py: 78 / 78 / 0 / 0 / 0.
- tests/test_forecast_state.py: 25 / 25 / 0 / 0 / 0.
- tests/test_grounded_rate_outlook.py: 49 / 49 / 0 / 0 / 0.
- tests/test_forecast_persistence.py: 46 / 46 / 0 / 0 / 0.
- tests/test_baseline_forecasting.py: 7 / 7 / 0 / 0 / 0.
- tests/test_data_quality.py: 8 / 8 / 0 / 0 / 0.
- tests/test_ai/: 75 / 75 / 0 / 0 / 0.
- tests/: 432 / 426 / 6 / 0 / 0.

Full-suite warnings: existing Pydantic class-based Config deprecation; existing Redis asyncio connection destructor cleanup raising Event loop is closed in test_acquire_pipeline_lock. Earlier focused T07 invocation also saw the new model namespace warnings before the namespace configuration fix; final full-suite verification has neither of those new warnings.

Git diff --check passes. Only the seven scoped files changed; standard git diff --stat lists the tracked T07 refactor only because the six new files remain untracked. Baseline HEAD and origin/main are unchanged and the index is empty. Protected fingerprints are unchanged. READY TO STAGE.


## Final hardening review

All six new files were inspected completely, along with the full tracked refactor and committed pre-T08 T07 source. Scope remains exactly seven files, with no router/task/prompt/model/migration/frontend changes.

Two implementation gaps were corrected: boolean metric coercion and the collector's extra latest-forecast query after an already-blocking source condition. Boolean metrics normalize to missing evidence and produce INVALID_METRICS/WITHHOLD; the pure evaluator also rejects booleans if supplied through an unchecked Pydantic copy. Policy count/horizon integers are strict, prohibiting bool/string/fractional coercion. Duplicate horizons normalize to a frozenset (set semantics); zero/negative or invalid members are rejected. Engine version is a fixed literal. The complete policy is reconstructed before evaluation, so caller-owned containers cannot change a prior result.

The shared collector now preserves committed T07 source-first short circuit. A successful missing-source or newer-source result does not query the forecast winner. Database failures in queries that actually execute propagate. Six direct comparison tests execute the original committed T07 context implementation and compare state/warnings for current, missing source, newer source, different winner, generation mismatch, and historical trend. Eight eligibility cases cover fresh/aging/stale/unknown with true/false stored flags across current/superseded/historical/missing-source contexts. Existing T07 read-time and narration regressions remain green.

REASON_ORDER explicitly adopts the declared Reason enum order as the output contract; output is normalized to that order independently of discovery order. Hard blockers are explicitly enumerated, and DecisionResult validates both actionable equivalence with directional decisions and prohibition of directional decisions carrying blockers. Tests exercise extremely small thresholds (0.000000000001%), combined stale/model/readiness/history blockers, negative boundary neighbors, exact MAE equality and immediate Decimal neighbors, strict policy failures, policy copy isolation, frozen nested structures, UTC offset conversion, and copied snapshot evaluation after ORM mutation. Added 23 engine cases and 14 state/parity cases; focused totals are now 78 and 25.

MAE conversion intentionally uses Decimal(str(float_metric)), never Decimal(float_metric). Monetary input remains Decimal. Negligible movement bypasses the directional MAE guard and cannot acquire both normal outcome reasons. Readiness recognizes only explicit BASELINE_READY/EXTENDED_HISTORY; MINIMAL and unknown/INSUFFICIENT labels block. Naive evaluated_at is rejected. Offset-aware timestamps are normalized to UTC before date comparison.

An additional offline behavioral verification imported and evaluated the engine in a fresh Python process with OpenAI/Azure/Redis/Celery/FastAPI/SQLAlchemy, app models, AI, routers and tasks imports blocked. Eligible copied evidence still produced the conditional directional result without narration or services.

Read-only runtime counts remain 0 forecasts, 0 outlooks, 248 freight rates. Current persisted availability is UNAVAILABLE. WITHHOLD describes hypothetical artifacts from the known insufficient current data, not an existing persisted decision. No runtime data was generated or changed. No T09 scoring/calibration or T10 endpoint/HTTP selection/mapping was added. No unsupported result semantics, secrets, credentials, environment values, absolute local paths, dumps, debug artifacts or temporary files occur in the scoped implementation.

All eight required commands were rerun independently after Python/test changes; the final validation record above supersedes the initial counts. Warnings were not suppressed: Pydantic deprecation in each command, Redis closed-loop cleanup warning in the full suite, obsolete Docker Compose version warning in runtime verification. All protected file hashes remain unchanged, whitespace checks cover tracked and all six new files, index remains empty, and HEAD/origin remain the approved baseline. READY TO STAGE, subject to human approval; no files staged.
