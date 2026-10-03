# AI-V3-T07 — Grounded Rate Outlook implementation review

## Scope and baseline

Pre-implementation branch main; HEAD and origin/main both 07aedd7a5f5c251b5c6d35d1c3eb89e1ddd78708. Tracked tree/index were clean. Protected unrelated untracked files were preserved. T07 is working-tree-only: no staging, commit, push, frontend edits, T08 decisions, computed confidence, advanced models, new providers, deployments, or paid services.

## Old and new architecture

Old POST queued a trend-ID job. Lane-only context selected a current rate, lane-aggregated averages/trend/slope and advisory summaries. GPT v1 produced outlook_text, categorical booking recommendation and 0–100 confidence; results went into RateTrend and a lane/date Redis cache. That path mixed series and lacked quantitative grounding.

New path: selected T06 RateForecast → persisted RateOutlook linked to trend/forecast/generation/prompt → stable outlook-ID Celery job → narrative-only GPT v2 → additive result GET. T07 never invokes T04/T06 forecast generation. No forecast means explicit unavailable 404 and no Azure call.

RateTrend is still a lane/date aggregate, not a source/container series. Its historical aggregates are not supplied as selected-series evidence. Advisories are omitted from T07 rather than implying series-compatible causal effects; no additional market inputs were added.

## Artifact persistence and identity

RateOutlook contains UUID id, trend_id FK, forecast_id FK, forecast_generated_at, prompt_version, evidence_snapshot JSONB, status, nullable outlook_text/error_message, attempt_count, nullable failure_code/retry_after/narration_input, created_at and nullable completed_at. Foreign keys are non-cascading and preserve linked history. Indexes cover trend_id and forecast_id. Unique identity: (trend_id, forecast_id, forecast_generated_at, prompt_version).

A snapshot is required because T06 upserts can mutate the same forecast row. Foreign-key linkage alone would not identify the numbers explained by historical prose. The immutable generation snapshot records the T06 response evidence and exact Decimal monetary values/derived change; read-time freshness is calculated on a copy. narration_input additionally records exactly the context supplied to the latest Azure attempt, including its freshness evaluation timestamp. Once completed, neither snapshot changes on GET or T06 regeneration. No content hashing or ML registry was introduced. Model and series identities are included in the snapshot and bound by forecast_id.

Repeated POST reuses the same generation/prompt artifact. Different artifact/model version, T06 regeneration timestamp, or prompt version creates another historical artifact. Completed/pending/generating artifacts are reused. Explicit retry=true may requeue transient timeout, Azure connection/server/provider rate-limit, or queue failures after a 60-second cooldown, bounded to three attempts for the same identity. Default POST does not retry failed rows; BudgetGuard budget/request-limit rejection, validation, and unknown internal errors are terminal. No duplicate artifact row is created. No Redis narration cache or TTL is used. Old cached advice cannot enter v2. Persisted text is validated against the narrative schema when read; invalid text is withheld with failed read status while numbers remain available.

## Selection, time and safety

POST accepts source/container_type as paired optional query parameters. An explicit pair resolves that exact series for the trend lane. Omission succeeds only for one matching series, otherwise 409. A partial pair is 422; absent selected forecast or trend is 404.

T06 get_latest_forecasts is reused: one result per source/lane/container, ordered by observation date DESC, generation DESC, target date DESC, model ASC, version ASC, UUID ASC. This is deterministic audit selection, not a model superiority claim.

Supersession compares max FreightRate.rate_date using exact source/lane/container against artifact cutoff. Newer data gives explicit regeneration conflict and prevents Azure. The latest forecast winner and forecast generation timestamp are also checked. Checks occur at creation, before Azure, after Azure and on GET. A change during Azure discards prose rather than marking it current. Date comparison cannot detect same-date source corrections; no source content-hash subsystem was added.

Current outlook requires trend lane equality, trend computed_date >= forecast cutoff, and the newest persisted trend date for the lane. Old trend IDs conflict rather than blending timeframes. This is not an as-of forecasting system. A latest trend can still be old in wall-clock terms: stale forecasts are allowed only as explicitly historical explanations.

T02 DataQualityService.evaluate_freight_rate_freshness remains the sole policy: UTC cutoff age divided by configured weekly cadence, fresh through ratio 1.5, aging through 3, otherwise stale. generated_at does not refresh source age. input_freshness_at_generation is stored history; current_input_freshness and freshness_evaluated_at are computed on every read/worker context. Readiness MINIMAL remains visible. Stored live_decision_eligible is preserved; effective eligibility additionally requires fresh/aging source and current context. The current T04 historical baseline stays ineligible even with fresh inputs.

## GPT ownership and infrastructure

GroundedRateOutlookOutput has only outlook_text, length 50–1500; extra fields are forbidden. RateOutlook v2 explicitly prohibits numerical forecasting, numerical change calculation, confidence/probability, booking recommendations, and representing historical metrics as probability. It requires disclosure of stale/MINIMAL/historical-only limits and treats inputs as untrusted. Numerical restatement is minimized; there is no brittle prose-number regex. Schema/prompt constraints do not mathematically guarantee truthful prose; consumers must use structured fields as authoritative.

GPT receives selected series, forecast/date/model/version/horizon, history/evaluation counts, MAE/RMSE/sMAPE/directional accuracy/readiness, cutoff/actual rate/generation freshness/current freshness/evaluation time/generation time, eligibility/warning and application-calculated exact change. No lane-mixed current-rate query is used. Decimal predicted_rate minus Decimal latest_actual_rate determines absolute change; percent divides by actual and multiplies by 100, quantized to four decimal places; zero denominator gives null. Snapshot exact values serialize as strings; the embedded T06 API shape retains existing JSON-number compatibility.

Existing AsyncAzureOpenAI, configured gpt-5-mini-1 deployment, logical gpt-5-mini, parse(), BudgetGuard, telemetry and client retry taxonomy are reused. No live Azure call was required. Grounded production is explicitly pinned to registered rate_outlook/v2, independent of legacy v1 setting; AI health reports v2. v1 prompt is unchanged. Legacy narrator/adapter/schema remain marked compatibility-only and are not used by authoritative routes or scheduling. Grounded calls use default temperature 1.0, which the existing client omits from Azure parameters.

## Async lifecycle and degradation

POST persists evidence before enqueueing. Response 202 includes trend_id, outlook_id, forecast_id and status; enqueue failure returns failed state with evidence retrievable. Worker atomically claims pending → generating, preventing duplicate worker calls. It receives only stable outlook identity and never reselects a different forecast. The client owns bounded transient retries. Budget/rate-limit rejection is terminal and gets no extra Celery retries.

Azure errors, exhausted client retries/timeouts, refusal/structured validation errors produce failed narration with safe messages. No fallback narrative or quantitative forecast is manufactured. GET always returns persisted evidence when the artifact exists and infrastructure is available. It is independent of Azure. Current context and freshness are rechecked even for completed prose; historical text may remain readable with explicit superseded/historical flags.

Existing scheduled orchestration was fixed only in the affected path: scalar UUID values are used directly, a stable outlook artifact is resolved first, and the registered Celery task is dispatched instead of calling .s() on a plain async function. Ambiguous/unavailable/historical lanes are skipped. No forecast scheduler was added.

Hard worker/process termination after claim can leave generating state; no lease/recovery subsystem was added. Deployment should drain old trend-ID jobs and restart workers after migration. The registered T07 task has a new name; old named jobs are rejected as unregistered, and direct old trend-UUID payloads fail safely without fallback or writes. Database outages can prevent persistence/read and remain infrastructure failures, not fabricated successful degradation.

## HTTP and frontend handoff

POST /api/v1/rates/trends/{trend_id}/outlook with optional paired source/container query; no body. 202 response: trend_id string, outlook_id UUID, forecast_id UUID, status string. 404 missing forecast/trend; 409 ambiguous/superseded/historical context; 422 partial selection or invalid UUID; 401 auth; 429 limiter; 500 unexpected infrastructure failure. Existing HTTPException envelope is preserved, including generic ERROR code for 409; framework UUID validation retains the existing FastAPI response.

GET /api/v1/rates/outlooks/{outlook_id}: 200 grounded result or 404, with existing 401/422/429/500 behavior. Fields: id, trend_id, forecast_id, prompt_version, created_at, completed_at, quantitative, exact_values, context_state, context_warning, effective_live_decision_eligible, narration.

quantitative contains id plus:
- series: source, trade_lane, container_type.
- forecast: forecast_for_date, predicted_rate, model, model_version, horizon.
- evidence: history_observations, evaluation_points, mae, rmse, smape, directional_accuracy, data_readiness.
- provenance: latest_observation_date, latest_actual_rate, input_freshness_at_generation, current_input_freshness, freshness_evaluated_at, generated_at.
- safety: live_decision_eligible, warning.

exact_values: predicted_rate, latest_actual_rate, expected_change, expected_change_pct (Decimal strings; percent nullable).
context_state: current, superseded, historical_trend, source_unavailable.
narration: status (pending/generating/completed/failed/unavailable), nullable text, nullable error_message, attempt_count, retryable, nullable retry_after, nullable input_evidence.

Auth remains active normal X-API-Key user through RateLimiter dependency; admin is not required. Router limiter is actually wired, default 100/60 per user/concrete path, Redis fail-open. API selection/read paths have HTTP auth/429 regression tests.

Additive: result GET, artifact fields and exact numbers. Semantically changed: POST resolves explicit series and current context; ambiguous/historical requests conflict. Breaking for previous polling consumers: GET rates/{lane} legacy outlook_text/recommendation/confidence now return null; it does not report T07 completion. Legacy database fields remain untouched, including status/error; consumers must poll the returned outlook_id. Legacy lane GET's 30-day-window 404 remains deferred because authoritative GET has no such window. API handoff updated; frontend repository not modified.

## Migration and runtime safety

Single graph: 7a3b421a2c3d → a1b2c3d4e5f6 → b2c3d4e5f6a7. New migration is additive rate_outlooks only; clean downgrade drops its indexes/table only. Disposable-schema test verifies columns/types/nullability, FKs, unique identity, indexes, prompt-distinct artifacts, downgrade parent preservation and reupgrade. Docker project runtime alembic heads/current both report b2c3d4e5f6a7. Existing twelve runtime tables have identical data fingerprints before/after migration; no runtime rows or exports are source fixtures. Current runtime RateForecast count is zero after the earlier authorized T06 hygiene rebuild; no forecast/narration was generated automatically.

## Verification

All Azure calls in deterministic tests are mocked. Focused tests replace legacy workflow/cache expectations with artifact/scheduler assertions; legacy v1 unit/evaluation tests remain compatibility coverage, not evidence that confidence is used by T07.

Test command results are recorded below after final verification. Each requested regression command is executed independently using .venv/bin/pytest and the established isolated test databases. Initial sandbox-only attempts could not connect to local PostgreSQL (PermissionError); authorized runs use the same existing runtime. No separate environment or paid call was introduced.

## Limitations and competition-safe claims

Supported claims: persisted algorithm-owned numerical forecasts ground LLM explanation; historical backtest evidence/provenance/freshness are exposed; narration failure preserves numbers; unsupported GPT confidence/probability/booking recommendations are absent from authoritative output.

Unsupported claims: calibrated probability, causal prediction, production-grade forecasting accuracy, actionable live booking advice while ineligible, verified daily external SCFI history, or advanced forecasting superiority. The local hardcoded next-day target contract remains T06's limitation. Same-date corrections, worker-crash recovery and external frontend compatibility require explicit operational awareness. No T05/T08/T09 work was implemented.

## Final independent test results

Every command below completed with failed=0 and errors=0. Commands use the existing .venv/bin/pytest executable; no live AI tests were enabled.

- pytest tests/test_grounded_rate_outlook.py: collected 49, passed 49, failed 0, skipped 0, errors 0.
- pytest tests/test_rate_outlook_workflow.py: collected 2, passed 2, failed 0, skipped 0, errors 0.
- pytest tests/test_rate_outlook_integration.py: collected 2, passed 2, failed 0, skipped 0, errors 0.
- pytest tests/test_forecast_persistence.py: collected 46, passed 46, failed 0, skipped 0, errors 0.
- pytest tests/test_baseline_forecasting.py: collected 7, passed 7, failed 0, skipped 0, errors 0.
- pytest tests/test_data_quality.py: collected 8, passed 8, failed 0, skipped 0, errors 0.
- pytest tests/test_ai/: collected 75, passed 75, failed 0, skipped 0, errors 0.
- pytest tests/: collected 329, passed 323, failed 0, skipped 6, errors 0.

Existing class-based Pydantic Config deprecation and Redis event-loop cleanup warnings remain. Full collection increased from 284 to 329: 49 grounded tests, while eight legacy workflow/integration expectations were replaced with four grounded worker/scheduler tests. Test count is not the acceptance criterion; behaviors are covered explicitly.

Focused coverage includes selection/ambiguity/missing/partial selection; immutable evidence and exact Decimal change; schema rejection of prediction/confidence/recommendation fields; v2 evidence/prompt/default temperature; stale/MINIMAL/historical eligibility; fresh-by-age supersession; exact-series isolation; historical trends; model/version ties and regeneration snapshot preservation; Azure/budget/rate/validation/timeout failure; invalid worker and persisted output; legacy Redis bypass; idempotent reuse; prompt/series isolation; HTTP identity/read/enqueue failure/auth/429; supersession during Azure; unavailable source; legacy advice suppression; additive migration and scoped downgrade; registered Celery dispatch and scalar scheduler iteration.

## Final source ownership

New:
- alembic/versions/b2c3d4e5f6a7_add_rate_outlooks_table.py
- app/ai/prompts/rate_outlook_v2.py
- app/models/rate_outlook.py
- app/schemas/outlook.py
- app/services/forecast_presentation.py
- app/services/rate_outlook.py
- docs/FREIGHTPULSE_AI_V3_T07_GROUNDED_RATE_OUTLOOK_REPORT.md
- tests/test_grounded_rate_outlook.py

Modified:
- app/ai/adapter.py (legacy annotation only)
- app/ai/prompts/registry.py
- app/ai/rate_outlook_narrator.py
- app/models/__init__.py
- app/routers/ai_admin.py (truthful active grounded prompt)
- app/routers/forecasts.py (shared presentation extraction, behavior unchanged)
- app/routers/rates.py
- app/schemas/ai_outputs.py
- app/schemas/rate.py (legacy annotation only)
- app/tasks/rate_outlook_generation.py
- app/tasks/rate_outlook_orchestrator.py
- docs/api_contract_handoff.md
- tests/test_rate_outlook_integration.py
- tests/test_rate_outlook_workflow.py

22 intended T07 source files total. No protected untracked file is part of T07. No secret, .env, runtime DB/export, or disposable validation script belongs to this source list. Validation scripts/logs/fingerprints live outside the repository in /tmp.

Acceptance: requested deterministic behaviors and regressions pass; migration has one head/current and additive downgrade coverage. Backend deployment must migrate and restart/drain old jobs; frontend consumers must adopt outlook_id polling and structured safety/evidence. No frontend code was changed. Human review remains required before staging. Recommendation: READY FOR REVIEW, not production accuracy certification or permission to implement T08.


## Final hardening review

All 22 intended files were reviewed, including complete tracked diff and untracked implementation. No protected file changed; no secrets, absolute local paths, dumps, debugger statements, test-only production auth hooks or commented-out implementation were added. Stale forecast-router schema imports were removed after shared presentation extraction.

The grounded artifact factory pins v2. Worker rejects non-v2 metadata before narrator construction. narrate_grounded rejects a non-v2 argument and resolves get_prompt(rate_outlook, v2) explicitly; absent v2 raises without v1 fallback. Environment AI_RATE_OUTLOOK_PROMPT_VERSION and legacy narrator constructor defaults do not select the grounded prompt. Regression tests exercise both.

Caller audit: production routes/scheduler call only the new named grounded task with outlook-ID. Worker calls only narrate_grounded and GroundedRateOutlookOutput. v1 registry, RateOutlookOutput and narrate() are legacy compatibility APIs used by old unit/live-evaluation tests; those live tests remain skipped by default. Legacy adapter has no production caller and is compatibility/dead production code; its legacy writes are not reachable from T07 routes/tasks. AI health reports v2. RouteBrief recommendation is a separate feature and was not changed.

Retry metadata is persisted in the same unpublished b2c3d4e5f6a7 revision; no second migration/head. The local unpublished T07 table was verified empty before scoped downgrade/reupgrade. All T06/source runtime contents remain preserved. Atomic pending claims increment attempt_count, and atomic retry compare-and-set only changes eligible failed rows. Concurrent workers cannot duplicate Azure work; duplicate delivery signals for pending work are harmless because of this claim. Budget failures have no automatic Celery retry, explicit POST retry, or hidden provider call. Unknown internal failures are non-retryable. Database transaction errors are rolled back and propagated instead of pretending evidence persistence succeeded.

Transient failed → explicit retry=true → cooldown satisfied and attempt_count<3 → pending → generating is the only retry transition. Completion is reused; pending/generating are never reset. Queue failures consume an attempt and cooldown. Scheduler omits retry=true and never retries failed rows. Terminal failures require operational review or a new actual forecast generation. No retry storm or new job framework was introduced.

Additional hardening tests cover v2 configuration independence/missing-registry rejection/non-v2 artifact rejection, explicit cooldown/recovery/exhaustion on the same row, BudgetGuard/validation no-requeue, pending/generating/completed reuse, real overlapping worker claims, distinct task namespace, direct legacy UUID rejection, completed immutable GPT input/evidence across all forecast-field mutations, and exact source/container recency isolation. Legacy lane GET lifecycle is now none/null as well as null advice fields.

API matrix: missing trend/forecast 404; partial pair 422; multiple series/superseded/historical 409; valid new/reused artifact 202 (including failed reuse); unauthorized 401; limiter breach 429. GET is 200 for an existing artifact regardless of narration success, with fresh current state and safe nullable text/error, or 404 if absent. Ordinary read/dependency failures remain safe infrastructure errors. Explicit retry does not alter quantitative evidence.

Remaining limitations: same-date source corrections are not detected; hard process loss can strand generating state; prose is not automatically proven faithful; provider client retries plus at most three narration attempts can still incur bounded repeated spend; latest-attempt narration input is preserved rather than a full per-attempt event log. The legacy lane data-window 404 remains. None of these imply calibrated probability, causal inference or live booking advice.

Final hardening recommendation: READY TO STAGE after this human review. Index remains empty; no commit/push/T08 work.
