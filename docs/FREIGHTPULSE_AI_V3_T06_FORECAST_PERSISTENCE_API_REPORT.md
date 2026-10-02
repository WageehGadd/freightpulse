# AI-V3-T06: Forecast Persistence + API

## 1. Executive Summary
T06 transforms the transient in-memory T04 baseline forecast into a durable, traceable, API-accessible artifact. Every persisted `RateForecast` row carries its forecast value, the model that produced it, a snapshot of the backtest evidence that supported it, the input observation provenance, freshness derived from the source (not from `generated_at`), and an explicit safety flag. No GPT calls occur during forecast generation. The API exposes forecasts in four semantic envelopes: `forecast`, `evidence`, `provenance`, and `safety`.

## 2. Pre-Implementation Audit
- **Branch:** `main`
- **HEAD == origin/main:** `d279223f0f725aaee1036c7c1c8e662a991db4c8`
- **Alembic head before T06:** `7a3b421a2c3d`
- **Final T06 head/current:** `a1b2c3d4e5f6` (one consolidated migration)
- **Final review state (2026-10-03):** T06 exists as working-tree changes: tracked edits are unstaged, new files are untracked, and the index is empty. The previous claim that T06 was staged was incorrect. No staging, commit, push, reset, restore, or checkout occurred during this review. HEAD and origin/main remain at the baseline above.

## 3. Existing Architecture Reused
| Component | Source | Reuse |
|-----------|--------|-------|
| `ForecastDatasetBuilder` | T03 | Consumed directly |
| `BaselineForecastingService` | T04 | Champion/backtest reused; exact Decimal prediction added using the same baseline arithmetic |
| `DataQualityService.evaluate_freight_rate_freshness` | T02 | Authoritative shared source freshness used by T02, T04 next-step output, and T06 |
| `get_current_user` / `get_current_admin_user` | `auth/security.py` | Used as-is |
| `RateLimiter` | `auth/rate_limit.py` | Applied to router |
| `AsyncSessionLocal` / `get_db` | `database.py` | Used as-is |
| `/api/v1` prefix | `main.py` | Consistent |
| Error envelope (`{"error": {...}}`) | `main.py` | Inherited via exception handlers |

## 4. Database Design
**Table:** `rate_forecasts`

| Column | Type | Nullable | Notes |
|--------|------|----------|-------|
| `id` | UUID | NO | Primary key |
| `source` | VARCHAR | NO | e.g. 'SCFI' |
| `trade_lane` | VARCHAR | NO | e.g. 'Egypt-China' |
| `container_type` | VARCHAR | NO | '20ft' / '40ft' |
| `forecast_for_date` | DATE | NO | Target prediction date |
| `predicted_rate` | NUMERIC(12,2) | NO | Same cent scale; wider range than FreightRate.rate_usd NUMERIC(10,2) |
| `model_name` | VARCHAR | NO | Per-series T04 champion |
| `model_version` | VARCHAR | NO | Required deterministic numerical implementation version; no database default |
| `forecast_horizon` | INTEGER | NO | Always 1 in T06 |
| `latest_observation_date` | DATE | NO | Source evidence anchor |
| `latest_actual_rate` | NUMERIC(12,2) | NO | Last known rate |
| `history_observations` | INTEGER | NO | Depth of training series |
| `evaluation_points` | INTEGER | NO | Walk-forward eval count |
| `backtest_mae` | FLOAT | NO | Generation-time snapshot |
| `backtest_rmse` | FLOAT | NO | Generation-time snapshot |
| `backtest_smape` | FLOAT | NO | Generation-time snapshot |
| `backtest_directional_accuracy` | FLOAT | NO | Generation-time snapshot |
| `data_readiness` | VARCHAR | NO | T03 readiness ('MINIMAL' etc.) |
| `input_freshness` | VARCHAR | NO | Generation-time evidence; API name input_freshness_at_generation |
| `live_decision_eligible` | BOOLEAN | NO | False while data is stale |
| `warning` | TEXT | YES | Human-readable safety caveat |
| `generated_at` | TIMESTAMPTZ | NO | Server default on insert; explicit now() in conflict update |

## 5. Final Migration
T06 adds one unpublished-then-finalized additive migration:

```text
7a3b421a2c3d -> a1b2c3d4e5f6 (head)
```

`a1b2c3d4e5f6_add_rate_forecasts_table.py` has revision a1b2c3d4e5f6 and down_revision 7a3b421a2c3d. It creates rate_forecasts directly in the final schema, including required model_version (no database default), NUMERIC(12,2) monetary columns, the seven-field unique identity, and all three forecast indexes. Defaults are forecast_horizon=1, live_decision_eligible=false, and generated_at=now(). All columns are non-null except warning. ORM client defaults remain compatible with migration server defaults.

Downgrade drops only the three forecast indexes and rate_forecasts table. It does not collapse versions, modify other tables, or touch pre-T06 data. Tests exercise fresh upgrade, ORM/schema comparison, coexisting versions, scoped downgrade with a preserved sentinel table, and clean re-upgrade in a disposable PostgreSQL schema.

Before publication, the unpublished migration history was consolidated. The local database was legitimately downgraded only to 7a3b421a2c3d, then upgraded using the finalized migration. No manual Alembic version-table edits occurred. Heads/current/history now verify the single final revision above. The eight disposable runtime forecast artifacts were removed by the authorized rebuild; the resulting runtime forecast table is empty. Counts and data fingerprints for all eleven pre-T06 tables match before and after.

## 6. Forecast Identity
A forecast is uniquely identified by the **epoch key**: `(source, trade_lane, container_type, latest_observation_date, forecast_for_date, model_name, model_version)` enforced via `uq_rate_forecast_epoch`.

## 7. Idempotency Policy
On conflict with the epoch key, the row is **upserted in place** (evidence fields and `generated_at` updated). When `latest_observation_date` advances (new FreightRate arrives), a **new row** is inserted — the old row is preserved for historical audit. MA(3) and MA(4) at the same cutoff also coexist because model_name is in the identity. The same name/cutoff/target under materially different model versions also coexist. A repeated identical identity under the same version updates that artifact, not an immutable new execution record. Re-running an older model at the same cutoff can make it the latest generated artifact. Source corrections at the same identity overwrite evidence and latest_actual_rate. The sole identity extension is model_version; existing same-identity update semantics remain.

## 8. Historical Auditability
Because the unique key includes `latest_observation_date`, forecasts produced from different source epochs coexist. The old forecast (epoch D1) is never mutated when epoch D2 arrives. The API uses `row_number()` partitioned by `(source, trade_lane, container_type)` and retains rank 1. Ordering is `latest_observation_date DESC, generated_at DESC, forecast_for_date DESC, model_name ASC, model_version ASC, id ASC`. Result series are ordered by source, trade lane, and container type. This returns exactly one deterministic row per matching series, including model ties. Newest source evidence wins before newest generation.

## 9. Forecast Target-Date Semantics
`forecast_for_date = latest_observation_date + timedelta(days=1)`. This is a **hardcoded current local dataset contract**, not inferred cadence or verified external SCFI publication semantics. Read-only SQL confirmed eight local series, each with 31 distinct observations over 30 days (2026-08-03 through 2026-09-02). T04 also uses +1 day. T03 exposes `expected_cadence_days=7` on its series profile as a nominal configured assumption; ForecastDatasetMetadata does not expose inferred cadence. It is therefore not a trustworthy observed next-period abstraction to reuse. With weekly observations the current code still returns latest date +1 day, which would mislabel the next weekly period. Revisit before weekly/irregular datasets are consumed. No cadence subsystem was added.

## 10. Per-Series Champion Semantics
The `ForecastPersistenceService` calls `backtest()` → identifies the per-series champion from `SeriesBacktestReport.champion_model`. It does NOT substitute the global MA(4) default. Confirmed by test `test_per_series_champion_not_overwritten_by_global_default`.

## 11. Evidence Snapshot
Evidence columns are written at generation time and are never dynamically recomputed from future data. An old forecast artifact retains the evidence that existed when it was created.

## 12. Data Provenance
`latest_observation_date` and `latest_actual_rate` pin the exact source observation. `history_observations` documents the depth of the training series.

## 13. Freshness Semantics
Original T06 used local `date.today()` and a separate 14-day threshold: age <=14 days was fresh, otherwise stale. This duplicated and contradicted T02: at 14 days T02 is aging while original T06 was fresh; at 15 days T02 is aging while original T06 was stale.

Final source of truth is `DataQualityService.evaluate_freight_rate_freshness(latest_observation_date, evaluated_at=None)`, minimally extracted in the existing T02 service and called by T02 and T06 (and T04 next-step output). T02 behavior is preserved: convert the observation date to UTC midnight, compute elapsed seconds at the UTC evaluation time, divide by the configured freight cadence of 604800 seconds, and classify ratio <=1.5 as fresh, <=3.0 as aging, otherwise stale. This cadence is configured, not inferred from local rows. `generated_at` is completely irrelevant to source freshness.

Regression tests exercise exact boundaries and actual T02 report versus T06 persisted status with fixed fresh, aging, and stale inputs. The global T02 report uses the maximum date across all FreightRate rows; T06 uses its own series cutoff. Different cutoffs are different inputs, not contradictory policy. Persisted `input_freshness` remains generation-time evidence. The read API exposes it as `input_freshness_at_generation`, replacing the ambiguous wire name `input_freshness`. Alongside it, `current_input_freshness` is recomputed using the same T02 helper from this artifact's latest_observation_date, with UTC `freshness_evaluated_at` shared by all artifacts in that response. Reads never mutate the stored snapshot or generated_at. A historical fresh snapshot can therefore truthfully accompany a currently stale cutoff.

Current freshness describes the selected artifact's cutoff at read time. It does not claim that newer source observations were queried or that the forecast is currently valid market advice. T08/any future Decision Engine must evaluate actual source data with T02 again at decision time and check model eligibility; neither stored freshness nor an old GET response is lasting decision authorization.

## 14. Safety Contract
`live_decision_eligible` requires both T02 source eligibility (fresh or aging) and T04 model eligibility. The current T04 baseline remains historical-only and always returns model eligibility false; consequently fresh source alone cannot enable live decisions. Stale source is always ineligible. Warning text is persisted alongside. The API always exposes both in the `safety` envelope.

## 15. API Design
```
GET  /api/v1/forecasts          — list latest per-series (query: source, trade_lane, container_type)
GET  /api/v1/forecasts/latest   — alias
POST /api/v1/forecasts/generate — (admin-only) trigger generation + persistence
```
Both GET endpoints return HTTP 200 with `{"forecasts": [...], "count": N}`, optional exact-match source/trade_lane/container_type filters, and one deterministic artifact per matching series. A no-match result is an empty list and count 0. Each artifact has this exact schema:

```text
id: UUID string
series: {source: string, trade_lane: string, container_type: string}
forecast: {forecast_for_date: ISO date, predicted_rate: number, model: string, model_version: string, horizon: integer}
evidence: {history_observations: integer, evaluation_points: integer,
           mae: number, rmse: number, smape: number, directional_accuracy: number,
           data_readiness: string}
provenance: {latest_observation_date: ISO date, latest_actual_rate: number,
             input_freshness_at_generation: string, current_input_freshness: string,
             freshness_evaluated_at: ISO datetime, generated_at: ISO datetime}
safety: {live_decision_eligible: boolean, warning: string or null}
```

Wire names `model` and `horizon` map to stored `model_name` and `forecast_horizon`. Evidence wire names `mae`, `rmse`, `smape`, and `directional_accuracy` map to the corresponding `backtest_*` columns; directional accuracy is a historical percentage, not calibrated confidence or probability. Monetary response types remain Pydantic float / JSON numbers for compatibility.

POST accepts no generation parameters/body and completes generation synchronously. HTTP 200 describes the completed batch, rather than 202 for unfinished work ([RFC 9110, sections 15.3.1 and 15.3.3](https://www.rfc-editor.org/rfc/rfc9110.html#name-202-accepted)). The exact completed-batch response is:

```text
attempted: integer
generated: integer
failed: integer
status: "success" | "partial_success" | "failure"
message: "Completed forecast generation: G generated, F failed out of A attempted. No GPT calls were made."
```

`attempted` counts enumerated series; `generated` counts successfully persisted/upserted artifacts; `failed` counts exceptions or attempts producing no artifact (including insufficient history). For every completed batch attempted = generated + failed.

- Complete success: HTTP 200, status=success, failed=0. With no series, counts are all zero: a completed no-op.
- Partial success: HTTP 200, status=partial_success, generated>0 and failed>0. Successful commits remain; failed transactions roll back before continuing.
- Total per-series failure: HTTP 500, status=failure, attempted>0, generated=0, failed=attempted, with the same structured batch response.
- Systemic errors before a reliable batch summary can be produced: existing HTTP 500 safe error envelope, not invented counts. The public message is Forecast generation failed. Check server logs.

No raw exception details, SQL, traceback, credentials, or provider details appear in batch responses. Details stay in server logs. No Celery/deferred execution was added. Missing/invalid/revoked keys or inactive users still return 401; non-admin generation returns 403.

## 16. Authentication
Read endpoints: `get_current_user` (any valid X-API-Key).
Generate endpoint: `get_current_admin_user` (admin flag required), which itself depends on `get_current_user`. No auth bypass or production dependency override was introduced.

**Actual rate limiting:** `Depends(RateLimiter())` is in the router dependencies and applies to every new endpoint, including generate. Existing limiter defaults are 100 requests per user per exact path per 60-second fixed window using Redis. Over limit returns 429 with Retry-After; Redis failures are fail-open. This was already wired at handoff; no new limiter was added.

## 17. Generation Trigger Decision
An authenticated POST endpoint (`/generate`) consistent with the existing HTTP trigger pattern. No Celery forecast scheduling was added.

## 18. Runtime Forecast Data
The current local source dataset still contains eight series, each with 31 distinct stored daily observations, 2026-08-03 through 2026-09-02. That is the local dataset contract, not verified external daily SCFI publication history. Source data is unchanged by migration consolidation.

## 19. Runtime Persistence and Migration Evidence
The current runtime rate_forecasts table was rebuilt through legitimate Alembic operations and contains zero rows. Eight disposable pre-consolidation forecast artifacts were intentionally discarded, as authorized. No runtime regeneration was needed: final-table schema verification and deterministic persistence tests provide validation without changing source data.

Actual PostgreSQL columns, defaults, nullability, indexes and version-aware uniqueness match the RateForecast ORM. Runtime heads/current both report a1b2c3d4e5f6; history shows one T06 revision directly after 7a3b421a2c3d. The downgrade never went below that pre-T06 revision. All eleven pre-T06 tables have identical row counts and data fingerprints before/after consolidation. Runtime database state remains outside Git source.

## 20. Idempotency Evidence
Deterministic tests prove identical generation keeps the primary key and row count; new source cutoffs create distinct historical rows; changing MA(3) to MA(4) at the same cutoff preserves both artifacts. Conflict updates explicitly refresh generated_at, latest_actual_rate and ORM identity-map state; model_version is part of identity and is never rewritten on a conflict. A per-series exception rolls back its transaction before continuing other series.

## 21. Test Environment and Fixture Safety
Tests used the existing `.venv/bin/pytest` and the existing localhost PostgreSQL/Redis services from Docker Compose. Existing `.env.test` loading points to `freightpulse_test_db`; runtime uses `freightpulse_db`. Test tables are created/dropped by the existing db_session fixture, never in the runtime DB during these runs. No environment file or credential was edited or exported.

`authenticated_client` uses a synthetic, test-only key with its SHA-256 hash in the isolated database and a real non-admin test user. It overrides only get_db, not authentication. Cleanup now uses try/finally and restores pre-existing dependency overrides even on failure. Existing tests do not request this new fixture unless explicitly declared. No Azure secret, real API key, or production auth weakening is present.

## 22. Focused Coverage
46 deterministic T06 tests pass. Coverage includes mapping, actual per-series champion matching plus MA(3)/MA(4) preservation, evidence snapshot, stale provenance, fixed-time generation trap, historical-only safety for fresh/aging/stale source, identical identity, new cutoff, same-cutoff model changes, query/HTTP latest ties and one-result-per-series filtering, isolation, read and admin auth, full response fields, no GPT invocation, Decimal arithmetic for each existing baseline, half-cent rounding, and T02/T04/T06 freshness consistency. Nine hardening cases additionally cover fresh-generation/stale-current API reads without mutation, partial/total generation failures with real failed DB transactions or no artifacts, empty batches, safe systemic errors, same-version idempotency/different-version coexistence and tied latest selection, and the consolidated migration's final schema, version coexistence, scoped downgrade and clean re-upgrade. The no-GPT test now patches the real FreightPulseAIClient.generate_structured method; the original test patched a nonexistent module-level attribute with raising=False and did not enforce the claim.

## 23. Independent Regression Results
Each command below was executed independently from the repository with `.venv/bin/pytest`; counts are not an aggregated AI-suite label. Final successful runs (T03 and T01 commands were independently run during the preceding review; those services were untouched in this hardening pass):

- `pytest tests/test_forecast_persistence.py`: collected 46, passed 46, failed 0, skipped 0, errors 0.
- `pytest tests/test_baseline_forecasting.py`: collected 7, passed 7, failed 0, skipped 0, errors 0.
- `pytest tests/test_forecast_dataset.py`: collected 5, passed 5, failed 0, skipped 0, errors 0.
- `pytest tests/test_data_quality.py`: collected 8, passed 8, failed 0, skipped 0, errors 0.
- `pytest tests/test_historical_persistence.py`: collected 2, passed 2, failed 0, skipped 0, errors 0.
- `pytest tests/test_ai/`: collected 75, passed 75, failed 0, skipped 0, errors 0.
- `pytest tests/`: collected 284, passed 278, failed 0, skipped 6, errors 0. The six live AI/HTTP tests remain skipped by default.

During the preceding review, an initial sandboxed attempt collected the original 16 T06 tests and reported 3 passed/13 setup errors due to blocked localhost access; an intermediate expanded run reported 34 passed/1 failed due to an incorrect AI client class name in the revised test, corrected before the final runs. Neither is the accepted validation result. Later 35-test and 37-test runs passed in that review; this hardening pass passed 45 tests initially and all 46 final tests including the migration test. Full-suite output also contains the existing Pydantic class-config deprecation and a Redis connection cleanup warning (`Event loop is closed`); no test fails.

Count reconciliation: excluding T06, 75+7+5+8+2 = 97, explaining how broader relevant-test selection can total 97 while tests/test_ai/ alone totals 75. This is supported by current collection, not proof of an earlier agent's exact command. Original T06 contained 16 tests; the first review expanded it to 37, and this hardening added nine to reach 46. Therefore 278-30 = 248 full-suite passes (plus the same six skips), consistent with the earlier 248+6 claim; the first review's 269+6 is consistent with 21 additional tests. The pre-T06 tracked suite accounts for 238 collected tests (284-46), not 140. The committed T04 report says 133 full-suite integration tests and 8 focused tests; actual focused collection is 7. No preserved exact command/output supports historical 140 or the old T06 document's 156.

## 24. Files Changed
- `app/models/rate_forecast.py` (New ORM model)
- `app/models/__init__.py` (RateForecast registered)
- `app/services/forecast_persistence.py` (New orchestration service)
- `app/schemas/forecast.py` (New API response schemas)
- `app/routers/forecasts.py` (New API router)
- `app/main.py` (Router registered)
- `alembic/versions/a1b2c3d4e5f6_add_rate_forecasts_table.py` (One finalized migration creating the complete version-aware schema)
- `tests/test_forecast_persistence.py` (Test suite)
- `tests/conftest.py` (added `authenticated_client` fixture)
- `docs/FREIGHTPULSE_AI_V3_T06_FORECAST_PERSISTENCE_API_REPORT.md` (this document)
- `app/services/data_quality.py` (minimal authoritative freshness extraction; T02 behavior preserved)
- `app/services/baseline_forecasting.py` (shared freshness and Decimal monetary path; existing models/float backtests retained)

## 25. Known Limitations
- Cadence is hardcoded to +1 day for the current local dataset. Requires revision before weekly/irregular datasets are consumed; external daily SCFI history is not verified.
- Stored freshness/evidence remain generation-time snapshots. GET separately evaluates current freshness of the artifact cutoff, not latest available source data. Re-evaluation at decision time remains required. Current baseline safety stays historical-only.
- Same identity/version reruns overwrite that artifact; model_version now preserves material implementation revisions, but no input-content hash or immutable execution log exists. Source corrections within an identity can replace evidence. Version bumps are manual and must accompany material numerical/model-selection changes; there is no automatic code-change detection or model registry.
- Generation remains synchronous and has no job monitor, cancellation API, or forecast scheduler. Partial success is HTTP 200 with explicit status/counts; clients must inspect status. Detailed series error diagnostics remain server-side. Systemic failures retain the project error envelope because counts cannot be reported reliably.
- Monetary inputs now stay Decimal through prediction and NUMERIC persistence; existing backtesting/model selection uses T03 floats and metrics remain floating-point. API JSON monetary numbers do not promise Decimal client arithmetic.
- No Celery scheduling — generation is triggered via POST endpoint only.
- Global MA(4) is documented as a benchmark but never forced onto per-series selections.
- `data_readiness=MINIMAL` is persisted honestly; no false upgrading.
- The API's `/generate` endpoint is admin-only; frontend cannot trigger it directly.

## 26. T07 Readiness
T06 is ready for human staging review based on passing independent tests, verified migration state, deterministic latest selection, and corrected provenance/safety semantics. This provides evidence for later T07 narration planning under the stated local-data limitations, not permission or an assertion that T07 is complete. T07 was not begun. T05 was not implemented or declared complete. No advanced model, calibrated confidence, Decision Engine, frontend, alert, paid API, Azure feature, or forecast scheduler was added.

## 27. Backend Integration Impact
- New table: `rate_forecasts`. Run `alembic upgrade head` on all environments.
- New endpoints at `/api/v1/forecasts` and `/api/v1/forecasts/generate`.
- `generate` requires admin API key.
- Read provenance.input_freshness_at_generation as historical evidence and provenance.current_input_freshness at freshness_evaluated_at as read-time cutoff freshness. Preserve the model safety warning/live_decision_eligible. Fresh source alone does not make this baseline live booking advice.
- ORM and finalized single-migration schema match names/types/nullability/three indexes/version-aware unique identity; ORM client defaults and migration server defaults supply horizon=1 and live=false. Downgrade drops only the forecast indexes/table. No unrelated schema mutation exists.
- Docker Compose Alembic inspection: heads/current report a1b2c3d4e5f6; history shows 7a3b421a2c3d -> a1b2c3d4e5f6. Legitimate local downgrade/re-upgrade rebuilt only T06; no manual version-table edits or downgrade below the pre-T06 head occurred.

## 28. Frontend Contract Impact
- Read from `GET /api/v1/forecasts/latest`.
- Always display the `safety.warning` text when `safety.live_decision_eligible = false`.
- Do NOT present the forecast as live booking advice when `live_decision_eligible=false`.
- Display `evidence.data_readiness` to set user expectations (currently `"MINIMAL"`).
- Read forecast.model_version for numerical implementation identity. Update consumers to the explicit provenance freshness names and generation batch status/counts.
- No frontend code changes in T06.

## 29. Competition-Safe Claims
**CAN CLAIM:**
- Forecasts are persisted with full model provenance and backtest evidence.
- Freshness is derived from source data, not from generation timestamp.
- Per-series model selection is preserved; global MA(4) does not override.
- Forecast persistence is idempotent.
- API is authenticated and exposes safety flags.
- No GPT calls in the quantitative forecast generation path.

**CANNOT CLAIM:**
- Live decision-grade forecasts (data is stale).
- Calibrated confidence intervals.
- Production-strength forecast accuracy (only 31 observations).


## 30. Review Corrections and Final Git Safety
Bugs corrected: independent T06 freshness policy, multi-row latest ties, fresh-source promotion of a historical-only baseline, avoidable monetary float rounding, conflict updates missing generation timestamp/latest actual provenance and ORM refresh, missing rollback after per-series failure, fragile fixture override cleanup, and an ineffective no-GPT test. T04's constant stale label now uses the authoritative freshness helper while its historical-only safety remains unchanged. Documentation corrects working-tree state, local cadence, precision, POST contract, model auditability, query ordering, exact test results, and readiness claims.

Review-agent edits: app/services/data_quality.py, app/services/baseline_forecasting.py, app/services/forecast_persistence.py, app/models/rate_forecast.py, app/schemas/forecast.py, tests/conftest.py, tests/test_forecast_persistence.py, and this report. The hardening pass subsequently updated the router; migration hygiene then finalized the single unpublished T06 migration. Main registration and model registry were inspected but not edited by the review agent.

The supplied unrelated untracked files (ai_files.txt, back_files.txt, backend/, the four listed pre-existing plan/audit documents, and test_migration.py) were not modified, staged, deleted, or included in T06. T06 source consists only of the twelve listed Python/Markdown files. No SQL dump, SQLite database, JSON export, runtime script, secret, .env file, or generated fixture was added to T06.

Acceptance: all sixteen requested functional categories are covered; all independently requested test commands pass with only six intentionally disabled live tests; one migration head/current verified; no changes staged. Financial precision path is FreightRate NUMERIC(10,2) -> Decimal source history -> existing T04 baseline arithmetic via predict_rate -> Decimal quantize(0.01) (half-even) -> RateForecast NUMERIC(12,2). ORM monetary annotations now say Decimal. The existing response contract intentionally remains float/JSON number.

Final recommendation: READY TO STAGE for human review of these twelve files only. This recommendation does not stage anything. Index remains empty; HEAD and origin/main remain d279223f0f725aaee1036c7c1c8e662a991db4c8. Do not include unrelated untracked files. No commit, push, or T07 work occurred.


## 31. Final Contract Hardening Decisions
The minimum structural safety change is explicit generation versus current freshness in the read schema, with the shared T02 helper and no historical evidence mutation. A documentation-only warning was rejected because the ambiguous field could too easily become current decision input. Current freshness is timestamped and is never a live-use recommendation.

Synchronous generation now returns a completed-batch summary with attempted/generated/failed/status/message. All series with no artifact count as failed; the API does not silently present these as full success. Complete and partial completed batches use 200; a nonempty batch with zero successful artifacts uses 500. A no-series batch is an explicit zero-count success. Global/systemic errors retain the existing safe error envelope. Existing authentication and rate limiting are untouched.

Lightweight model_version is justified now because material changes under the same MA(3) name must remain distinguishable. BaselineForecastingService.MODEL_VERSION = baseline-v1-decimal identifies the existing naive/MA/drift numerical implementation, MAE/RMSE/model-name champion rule, and Decimal prediction with half-even cent persistence. The admin endpoint retains default initial_train_size=15; model_version is algorithm identity, not a full configuration/input-content hash. Bump the constant for material implementation changes, not time, random generation, or unrelated Git commits. New versions coexist historically; same-version reruns are idempotent. The finalized migration creates model_version directly as a required field, with no guessed implementation version or backfill. New forecasts explicitly supply the deterministic version from the existing baseline service.

Final latest ordering is observation date DESC, generated_at DESC, forecast_for_date DESC, model_name ASC, model_version ASC, UUID ASC. Generation time determines recency within a cutoff; version-name ordering is only a deterministic tie-break, not an assertion of semantic version recency. Exactly one artifact remains selected per series.

Files edited in this hardening pass: app/schemas/forecast.py, app/routers/forecasts.py, app/services/forecast_persistence.py, app/models/rate_forecast.py, app/services/baseline_forecasting.py (version constant only), tests/test_forecast_persistence.py, this report, and the model-version migration work subsequently consolidated into the single finalized T06 migration. T02 helper/thresholds, Decimal arithmetic, champion selection, target-date contract, fixtures, authentication, limiter, frontend, and GPT functionality were not changed in this pass. T05/T07 were not started.


## 32. Final Migration-Hygiene Verification
Only migration hygiene changed in this pass: the final model_version column and uniqueness were consolidated into alembic/versions/a1b2c3d4e5f6_add_rate_forecasts_table.py; the unpublished extra migration was removed; the migration-specific test was updated; this report now describes only the finalized graph. No API, forecast, freshness, auth, rate-limit, monetary, model-selection, or target-date behavior changed.

The final migration test compares every column name/type affinity/nullability, monetary precision/scale, timezone, defaults, primary key, unique columns, and three indexes against the ORM. It verifies model-version coexistence and that downgrade/re-upgrade leaves a non-T06 sentinel table and its data intact. Migration consolidation does not increase test count.

All five commands requested for this pass were independently rerun using .venv/bin/pytest. Final results: forecast persistence collected/passed 46/46; baseline 7/7; data quality 8/8; tests/test_ai 75/75; full tests collected 284, passed 278, skipped 6. Failed=0 and errors=0 for every command. Existing Pydantic deprecation/Redis cleanup warnings remain. T03/T01 results earlier in this report belong to the preceding review and their services were unchanged.

All pre-existing unrelated untracked file fingerprints remain unchanged. Git index is empty, HEAD equals origin/main equals d279223f0f725aaee1036c7c1c8e662a991db4c8. Working-tree whitespace checks cover tracked changes and all intended untracked T06 source. Final intended T06 source is the twelve files in section 24. No staging, commit, push, reset, restore, checkout, or T07 work occurred. READY TO STAGE for human review only.
