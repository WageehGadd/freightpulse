# FreightPulse AI V3 — Backend Handoff

## 1. Handoff Context

AI V3 CODE STATUS = COMPLETE FOR APPROVED SCOPE

Baseline: `de65aff978234cd1b43a0050ebf92b9293951334`. Backend owns operational composition/integration, not a redesign of AI methodology. Repository implementation and tests do not establish deployment or runtime population. T05/T15 remain DATA-GATED; T12/T13/T16 are Frontend handoffs. The [Final Status](FREIGHTPULSE_AI_V3_FINAL_STATUS.md) contains the authoritative T00–T18 matrix.

## 2. What AI Already Provides

- **T06:** `ForecastPersistenceService.generate_and_persist_all`, `generate_and_persist_series`, and `get_latest_forecasts` in `app/services/forecast_persistence.py`; ORM `RateForecast`; `ForecastListResponse` / `ForecastGenerateResponse` in `app/schemas/forecast.py`.
- **T07:** `RateOutlookService.create/read/context_state` in `app/services/rate_outlook.py`; ORM `RateOutlook`; `GroundedOutlookCreateResponse` / `GroundedOutlookResponse` in `app/schemas/outlook.py`; `RateOutlookNarrator.narrate_grounded` in `app/ai/rate_outlook_narrator.py`. Worker function `generate_rate_outlook_async` and Celery wrapper `generate_rate_outlook` are in `app/tasks/rate_outlook_generation.py`; registered task name is `app.tasks.rate_outlook_generation.generate_grounded_rate_outlook`.
- **T08/T09/T10:** `evaluate_decision`, `assess_evidence`, and `DecisionAPIService.latest` in their respective `app/services/decision_engine.py`, `reliability.py`, and `decision_api.py` files. `ForecastStateCollector.collect` and `snapshot_forecast` preserve exact-series state and copied evidence. Public DTO is `DecisionAPIResponse` in `app/schemas/decision_api.py`.
- **T11:** Pure `evaluate(EvaluationInput, EvaluationConfig)` in `app/services/forecast_evaluation.py`; `EvaluationResult` in `app/schemas/forecast_evaluation.py`; `EvaluationPersistenceService.extract/load/persist` in `app/services/forecast_evaluation_persistence.py`. Internal capability only; no public evaluation job/API is supplied by T11.
- **T14:** `evaluate_predictive_alert(PredictiveAlertInput)` returns `PredictiveAlertResult`; schemas in `app/schemas/predictive_alert.py`. Pure proposal computation, not persistence or delivery.
- **T17:** `evaluate_scenario(baseline, request, policy, evaluated_at)` in `app/services/scenario_intelligence.py`, returning `ScenarioResult` from `app/schemas/scenario.py`. Pure core, no public scenario endpoint.
- **T18:** `compose_route_evidence(RouteEvidenceRequest)` in `app/services/route_intelligence.py`, returning `RouteEvidenceResult` from `app/schemas/route_intelligence.py`. Pure core, no public route-evidence endpoint.

T06/T07/T10 routes are registered under `/api/v1` in `app/main.py`. T08/T09 are exposed through T10, not independent generation APIs.

## 3. P0 — Forecast → Outlook Orchestration

Backend must establish the sequence: fresh required source data → exact series → T06 generation/persistence → available persisted forecast → dependent T07 grounded outlook → consumer exposure.

`app/tasks/orchestration.py` currently chains ingestion, trend computation, rate-alert evaluation and `schedule_rate_outlook`; it does not generate T06 forecasts. `app/tasks/rate_outlook_orchestrator.py` schedules resolved artifacts without forecast generation. This is an operational integration gap, not an AI-methodology defect. The previous audit found forecast/outlook runtime artifacts absent; this handoff did not requery those tables.

Keep scheduling, failure recovery and readiness checks Backend-owned. Do not narrate nonexistent evidence. T06 reports attempted/generated/failed counts and success/partial_success/failure; successful series must remain distinguishable from failed ones. Do not turn partial success into a claim that all series are ready.

T06 `uq_rate_forecast_epoch` identity is `(source, trade_lane, container_type, latest_observation_date, forecast_for_date, model_name, model_version)`. Same identity upserts in place; another cutoff/model/version can retain a distinct artifact. T07 `uq_rate_outlook_generation` is `(trend_id, forecast_id, forecast_generated_at, prompt_version)`, preserving generation identity even when T06 reuses an ID. Coordinate scheduling with those identities rather than inventing new deduplication semantics.

T07 worker claims protect duplicate execution. Explicit transient retry uses a 60-second cooldown and at most three attempts; retryable codes are `timeout`, `service_unavailable`, and `queue_unavailable`. BudgetGuard and non-retryable failures remain terminal. These artifact retries are distinct from the shared provider client's internal retries. Preserve evidence when narration fails and expose pending/failed state honestly.

## 4. P0 — Exact-Series Consumption

Preserve `source + trade_lane + container_type` exactly; no lane aliases, normalization or silent substitution. `SeriesIdentity`, `ForecastSnapshot` and `ForecastState` in `app/schemas/decision.py` carry factual identity and generation state.

T06 selects one winner per series by observation date descending, generation timestamp descending, target date descending, model name ascending, model version ascending, then ID ascending. `ForecastStateCollector` reuses T02 freshness and T06 ordering; detects source and forecast/generation supersession, including same-ID regeneration; never promotes stored eligibility=false.

T07 derives lane from `RateTrend`. Optional `source` and `container_type` must be supplied together; multiple candidate series cause 409, absent evidence 404, and historical/superseded context 409. Preserve trend-specific checks as well as forecast state.

## 5. P0 — T06/T10 Stable Consumption

**T06 endpoints** in `app/routers/forecasts.py`:

- `GET /api/v1/forecasts` and `GET /api/v1/forecasts/latest`: optional exact `source`, `trade_lane`, `container_type`; normal-user authentication; `ForecastListResponse {forecasts, count}`.
- `POST /api/v1/forecasts/generate`: admin authentication; no GPT; `ForecastGenerateResponse {attempted, generated, failed, status, message}`. Success/partial success use 200; total/systemic failure uses 500.

Each `RateForecastResponse` has `id`, `series`, `forecast`, `evidence`, `provenance`, `safety`. Forecast fields are `forecast_for_date`, `predicted_rate`, `model`, `model_version`, `horizon`. Evidence exposes history/evaluation counts, MAE/RMSE/sMAPE/directional accuracy and readiness. Provenance separates `input_freshness_at_generation`, `current_input_freshness`, `freshness_evaluated_at`, source cutoff/actual and `generated_at`. T06 monetary presentation fields are JSON numbers, although persistence uses Decimal/NUMERIC. Its stored `safety.live_decision_eligible` is not a complete current supersession decision; use T10 for authoritative current decision composition.

**T07 endpoints** in `app/routers/rates.py`:

- `POST /api/v1/rates/trends/{trend_id}/outlook`: 202; selectors `source`, `container_type`, `retry`; response `trend_id`, `outlook_id`, `forecast_id`, `status`.
- `GET /api/v1/rates/outlooks/{outlook_id}`: `GroundedOutlookResponse`, containing quantitative generation snapshot, `exact_values`, current `context_state`, effective eligibility/warning, and `narration` with status/text/error/attempt/retry timing and actual `input_evidence`.

T07 `exact_values` uses exact Decimal JSON strings for predicted rate, actual rate, change and percentage change. Stored generation evidence is separate from read-time freshness/supersession. The grounded production path pins v2 and accepts narrative-only output; legacy recommendation/confidence fields are non-authoritative.

**T10 endpoint** in `app/routers/decisions.py`: `GET /api/v1/decisions/latest`, requiring all three exact selectors. Normal-user authentication; no implicit generation/GPT; successful responses use `Cache-Control: no-store`. `DecisionAPIResponse` contains `identity`, `forecast`, `decision`, `evidence`, `current_state`, `policy`, `provenance`; Decimal values serialize as strings. Missing artifact: 404; invalid selectors: 422; unauthenticated: 401; rate-limited: 429; integrity/infrastructure failure: sanitized 500. WITHHOLD/MONITOR are valid 200 business states.

T06/T07/T10 wire `RateLimiter`; its normal-user auth dependency remains active even on routes without an explicit user argument. Existing default is 100 calls per 60-second fixed window per user/path, Redis failure opens the limiter, not authentication. Preserve the current DTOs and exact-series semantics.

## 6. P0 — Security Boundary

Backend/Deployment must resolve production browser/server authentication and tenant isolation. Do not ship privileged shared/master API secrets in browser code, URLs or public configuration. REST user authentication does not certify every exposure boundary.

`app/websocket_manager.py` accepts header/query credentials, has a master-key bypass and permits local/testing connections when the master key is absent. `app/routers/websocket.py` exposes `/ws/test-alert` without an authentication dependency on that handler. Existing dual WebSocket router registration also requires exposure review. These are retained Backend/Deployment findings, not fixes performed by this handoff. Verify identity-to-tenant ownership, browser-safe access, public test-endpoint restrictions and production configuration before exposure; no production-security certification is claimed.

## 7. P1 — T14 Predictive Alert Operationalization

`PredictiveAlertInput` carries exact series, completed `DecisionResult`, paired `EvidenceAssessment`, and optional `AlertCheckpoint`. `evaluate_predictive_alert` returns `PredictiveAlertResult` with status, transition/category, signal identity, reasons, evidence and proposed next checkpoint.

Statuses are `BASELINE_ONLY`, `EMIT`, `SUPPRESS`, `INVALID_INPUT`; transitions are `DIRECTIONAL_ENTERED`, `DIRECTION_REVERSED`, `ACTIONABILITY_WITHDRAWN`. First observation establishes baseline only. Identical accepted state does not create a repeated transition. Hashes establish deterministic identity, not source authentication.

Backend must persist accepted checkpoints, enforce compare-and-set/concurrency, deduplicate, coordinate transactional/outbox delivery where appropriate, implement tenant transport, scheduling and recovery. A pure proposal is not an accepted/delivered event. Revalidate against authoritative factual evidence before acceptance. T17 hypothetical output must never trigger T14 factual alerts; Frontend consumes accepted operational events, not raw evaluator proposals.

## 8. P1 — T17 Scenario Adapter/API

Backend supplies authenticated factual `DecisionInput`, application-owned `DecisionPolicy` and evaluation instant. Client input is only `ScenarioRequest`: category `MARKET_WHAT_IF`, one discriminated assumption, either `AbsoluteRate` (`ABSOLUTE_PREDICTED_RATE`) or `PercentageAdjustment` (`PERCENTAGE_ADJUSTMENT`), each with `requested_value`. Preserve bounded Decimal/string validation; do not accept client evidence/state/policy overrides.

`evaluate_scenario` copies the baseline, changes only predicted rate, reruns T08 at the same instant/policy, and retains T09 factual evidence only. Result includes factual `baseline_evidence`, applied assumption, `hypothetical_t08_result`, comparisons/blocker changes, fingerprints and deterministic identity. `hypothetical=true`, `non_operational=true`, `live_actionable=false` are mandatory even if nested hypothetical rule actionability is true. No causal or future-occurrence probability is implied; no T14 side effect.

## 9. P1 — T18 Route Evidence Adapter/API

Backend supplies `RouteEvidenceRequest {series, evaluated_at, decision_input, advisories}` with exact `MarketSeries` and authoritative factual lineage. `AdvisorySnapshot` retains record/carrier/series, `ProvenanceClass`, source text/URL, derived interpretation and source/observation timestamps. Provenance classes distinguish verified source, persisted application, derived interpretation, seeded demo and unverified inputs.

`compose_route_evidence` preserves T08/T09 and returns forecast/decision/assessment availability, contextual advisories/conflicts, `OperationalGaps`, limitations/provenance and fingerprint. Qualified advisory context requires asserted verified source data, exact series and nonblank source text/URL; a supplied classification/hash does not authenticate truth. Backend owns verifying lineage. Advisory context cannot change actionability. Operational physical-route, port, distance, transit-time, alternatives, ranking and risk gaps remain unavailable.

Do not convert this into physical route optimization, best-route ranking, ETA, delay/risk probability or savings prediction. No public endpoint exists until a separately owned adapter is implemented.

## 10. P1 — T11 Evaluation Exposure

Migration `alembic/versions/c3d4e5f6a7b8_add_forecast_evaluation_tables.py` has revision `c3d4e5f6a7b8`, parent `b2c3d4e5f6a7`. Infrastructure must apply it before runtime evaluation persistence. The audited runtime lag is historical evidence, not freshly rechecked here.

Backend may expose an authenticated read/job interface if required. `EvaluationPersistenceService` extracts exact series, persists atomically using a savepoint with caller-owned outer commit, and validates loaded evidence integrity. Preserve evaluation fingerprints, point populations and explicit directional denominators. Retrospective dependent outer folds are not independent prospective validation; metrics are not calibrated confidence. T11 does not unlock T05.

## 11. Legacy Route Brief Boundary

Legacy GPT Route Brief and legacy RateTrend advice fields remain separate from deterministic V3 authority. Do not use free-text recommendations or legacy confidence values as factual T08/T09 evidence. Grounded T07 v2 narration is explanatory only.

## 12. Failure and Availability Semantics

Absent evidence stays unavailable/withheld; unknown publication timestamps/age remain unknown; regeneration cannot refresh stale source observations. Stored eligibility=false cannot be promoted. T06 freshness presentation does not query newer source data; T10 shared state includes supersession checks.

T05/T15 gates remain closed until evidence supports unlocking. T17 stays hypothetical. T18 operational gaps stay gaps, not zero-risk defaults. GPT pending/failure cannot erase deterministic evidence or fabricate advice. Local +1-day target semantics and same-date correction limitations remain disclosed. T08 policy defaults (2% movement, 100 history, 30 evaluations, MAE multiplier 1.0, horizon {1}) are heuristic, not calibrated or learned-optimal.

## 13. Deployment Dependencies

Coordinate PostgreSQL, Redis, API, worker, Beat/scheduler, T11 migration, Azure deployment/API compatibility, pricing/budget configuration, logs/metrics and recovery. Availability of source code or local infrastructure does not establish deployment. Shared accounting has no distributed exactly-once, crash-proof or cancellation-safe guarantee; do not extend its claims operationally.

## 14. Backend Acceptance Checklist

These are pending integration acceptance criteria, not assertions of completed Backend work.

- [ ] T06 generation runs before dependent T07 scheduling.
- [ ] Exact series identity preserved.
- [ ] Persisted forecasts available to T10 consumers.
- [ ] Missing evidence and partial failure exposed honestly.
- [ ] T14 checkpoint/dedup/concurrency and acceptance/delivery behavior implemented.
- [ ] T17 exposed as hypothetical/non-operational only.
- [ ] T17 cannot trigger T14 operational alerts.
- [ ] T18 preserves verified factual lineage and advisory qualification.
- [ ] T18 does not claim route optimization.
- [ ] T11 migration applied before evaluation runtime use.
- [ ] Browser/API/WebSocket security boundary resolved; test-alert exposure restricted.
- [ ] Tenant isolation verified.
- [ ] No privileged shared secret exposed to public browser.
- [ ] Seeded/unverified data labeled honestly; T05/T15 gates retained.

## 15. Backend Priority Summary

P0: forecast/outlook orchestration, exact-series integrity, stable T06/T10 consumption, security boundary.

P1: T14 operationalization, T17 adapter, T18 adapter, T11 exposure.

P2: recovery, observability, cache consistency, pagination and legacy hardening. The final AI hotfixes did not change this ordering.
