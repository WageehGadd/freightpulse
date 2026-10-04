# AI-V3-T11 — Baseline evaluation evidence

Hardening verdict: READY TO STAGE, subject to separate human authorization. This is internal, retrospective evaluation infrastructure, not a public prediction or decision feature. All T11 source changes remain unstaged/untracked. Baseline HEAD and origin/main are `2356be6665a306dd44d68b7903643c579445f7fd`. No staging, commit, push, T12 work, or teammate contact occurred.

## Architecture and scientific scope

The pure evaluator accepts one exact source/lane/container series, a frozen Decimal observation snapshot, and frozen configuration. It produces immutable tuples of fold evidence, candidate aggregates, final champion, outer aggregates, winner counts, switch count, and explicit limitations. It performs no database, provider, network, GPT, Redis, Celery, or API work. A separate internal persistence service extracts exact-series observations and stores completed artifacts.

The two phases are `SELECTION_WINDOW` and `NESTED_OUTER`. Evaluation version is `baseline-evaluation-v1`. Defaults are initial training size 15, exploratory minimum inner evaluation count m=4, horizon 1, and ordered candidates Naive, MA(2), MA(3), MA(4), Drift. The m=4 value is approved configuration, not a statistically validated sample-size threshold.

T04 uses expanding walk-forward predictions: each target is excluded from its own training history. Its final champion is selected using those same errors whose aggregates are reported. That selection-window reuse can make the selected champion's reported performance optimistic; it does not make T04 predictions ordinary in-sample fits.

For selection-window target ordinal t, every candidate predicts from observations `[0:t]`, then scores observation t. Each candidate receives N−15 target points when N>15. Final champion uses all selection-window targets, ordered by MAE ascending, RMSE ascending, then model name ascending.

For outer target t, starting at t=15+4, the selector sees only candidate selection-window errors with target ordinal strictly below t. It selects the winner using the same deterministic order, predicts using `[0:t]`, and only then scores target t. Each outer point records its selected candidate and inner evaluation count t−15. Cached earlier candidate predictions are reused rather than rerunning the forecasting formulas for each inner replay. Earlier aggregate rescans and history slices still have quadratic worst-case cost; no large-dataset performance claim is made.

Current and future outer targets cannot influence their own selection or prediction. Tests perturb both and verify this causality. Outer evaluation measures the model-selection procedure. It does not independently validate the final all-history champion. Retrospective time-series folds remain dependent observations.

## T04 semantic reuse

The conditional baseline_forecasting.py modification was necessary to reuse T04 without importing its database-coupled dataset/data-quality modules into the pure evaluator. Dataset imports now occur only for type checking; data-quality import occurs inside the existing forecast method. The unchanged `(MAE, RMSE, model_name)` selection tuple was extracted into `baseline_selection_key`, used by both T04 and T11.

T11 directly reuses T04 prediction, direction, and sMAPE functions. No candidate formulas, default model list, T04 aggregate behavior, forecast target semantics, or source freshness policy were changed. Tests prove every candidate's fold predictions/errors and final champion match direct T04 evaluation on deterministic fixtures. Existing T04 and downstream regression tests pass.

## Numerical evidence

Input snapshots preserve exact Decimal monetary values, dates, and order. Float/bool monetary input is rejected. Duplicate or nonincreasing dates are rejected rather than sorted or deduplicated. Observation ordinal is explicit and stable. Extraction filters all three identity fields, optionally bounds the cutoff, orders by date, and disables autoflush.

Evaluation deliberately follows T04 float arithmetic after converting the exact snapshot. Predictions, actuals used for scoring, previous actual, residuals, errors, and metrics are finite float outputs, stored as double precision. This does not convert the persisted monetary snapshot back from float. Snapshot persistence uses NUMERIC(10,2), rejecting nonfinite values, out-of-range values, and subcent values that would require rounding.

Signed residual is actual−prediction. Absolute error is its absolute value; squared error is residual squared. MAE is mean absolute error; RMSE is square root of mean squared error. sMAPE component is `200 * abs(actual−prediction) / (abs(actual)+abs(prediction))`, with zero when the denominator is zero. Aggregate sMAPE is the mean of these components, expressed as a percentage.

Direction compares prediction and actual separately against the immediately preceding actual, yielding INCREASE, DECREASE, or UNCHANGED using T04's exact sign semantics. A direction comparison is valid unless both movements are unchanged. Correctness is equality of the two directions. Both-flat points have valid=false and correct=null. Directional accuracy is correct/valid×100; when valid count is zero it is null, not a fabricated zero-percent result. Counts and each comparison are retained. T04's existing zero-denominator aggregate behavior was not weakened or changed.

Aggregates are reproducible from stored points in deterministic target/candidate order. Winner counts describe outer selected candidates; switch count counts changes between consecutive outer winners. These are descriptive stability measures, not confidence or probabilities. Switch count is null when no outer points exist.

Nonfinite input is rejected by Pydantic validation. Finite inputs whose float conversion or subsequent arithmetic becomes invalid/overflows produce INVALID evidence with no partial points or fabricated aggregates. Unsupported version, candidate name, or horizon produces UNSUPPORTED evidence. Invalid configuration structure is rejected. With no selection targets, selection is INSUFFICIENT_HISTORY; with fewer than four prior selection targets available for any later target, outer evaluation is INSUFFICIENT_HISTORY. Valid selection evidence can therefore exist without outer evidence. Empty snapshots have a nullable cutoff and no champion. Supported completed insufficient/unsupported artifacts can be persisted without pretending evaluation succeeded.

## Fingerprints and identity

Canonical JSON uses sorted keys, compact separators, ASCII escaping, disallows NaN, and is hashed with SHA-256 over UTF-8 bytes. Dataset identity includes source, trade_lane, container_type, and ordered `[ordinal, ISO date, canonical exact Decimal value]` observations. Decimal canonicalization uses fixed-point formatting with trailing fractional zero removal; it performs no normalization under a global Decimal context. Numerically equal encodings such as 100 and 1E2 share identity. Any actual value/date/order/series change changes the fingerprint.

Configuration identity includes version, train size, inner minimum, horizon, ordered candidate names, explicit MA windows, baseline methodology version, selection order, metric version, both phases, prior-target outer selection rule, and null zero-direction denominator semantics. It excludes clocks, UUIDs, and machine paths. Changing meaningful configuration/version changes identity. No runtime Git command is needed.

Run uniqueness is exactly `(source, trade_lane, container_type, dataset_fingerprint, evaluation_version, configuration_fingerprint)`. Cutoff alone is insufficient: same-date corrections create a new dataset identity. Creation timestamp and random storage IDs do not determine evaluation identity. A separate content fingerprint covers the complete reconstructed result, with canonical exact snapshot money.

## Three-table persistence

`forecast_evaluation_runs` stores UUID ID, exact series, nullable cutoff, observation count, dataset/configuration/content fingerprints, version, complete JSONB methodology/configuration, train size, inner minimum, horizon, selection target count, outer count, nullable final champion, phase statuses, nullable switch count, UNVERIFIED provenance, and server creation timestamp. It has the unique run identity and source/lane/container/cutoff index.

`forecast_evaluation_observations` stores UUID ID, run FK, ordinal, date, and NUMERIC(10,2) rate. Unique constraints are `(run_id, ordinal)` and `(run_id, observation_date)`. A database check rejects nonfinite rates.

`forecast_evaluation_points` stores UUID ID, run FK, phase, target ordinal/date, candidate, training count, nullable inner count, previous actual, actual, prediction, residual, absolute/squared errors, sMAPE component, both directions, valid flag, and nullable correctness. Unique identity is `(run_id, protocol_phase, target_ordinal, candidate_name)`. The partial unique index `uq_evaluation_outer_target` additionally enforces one `(run_id, target_ordinal)` where phase is NESTED_OUTER, regardless of candidate. Selection targets retain their complete candidate populations. Checks constrain phase and reject nonfinite scoring fields. Child FKs use ON DELETE CASCADE; their unique indexes support run-prefixed access. No fourth aggregate table is required.

Persistence verifies the complete result against deterministic evaluation before writing. A savepoint contains run insertion, input snapshot, and both phases. Child failure rolls back the artifact; there is no hidden commit or outer rollback. The caller owns transaction durability and can roll back even after persist returns. SQLAlchemy begin_nested normally flushes preexisting caller work before entering the savepoint; tests verify this behavior rather than claiming the service isolates that preflush.

PostgreSQL INSERT ON CONFLICT DO NOTHING against the named run constraint arbitrates concurrent attempts. The loser loads the existing complete artifact and checks content identity; it never overwrites conflicting evidence. A real two-session READ COMMITTED test proves one logical run with complete children. Higher transaction isolation can require caller-level serialization retries; no distributed locking or scheduling subsystem was added.

Frozen Pydantic structures expose tuples, not mutable nested lists/dicts. ORM update/delete listeners reject changes to completed run/observation/point records. Persistence provides no mutation path. Loading refreshes both parent and children from persisted values before validation, including when cached ORM objects remain referenced. It reconstructs aggregates and checks content/config/header fingerprints and derived metadata. Separate structural checks verify complete ordered candidate populations, exactly one outer point per expected target, phase availability, target dates, training counts and inner counts. Malformed validation/configuration evidence is rejected as an integrity error. This is application/ORM append-only protection and integrity detection, not a database permission barrier against administrative or bulk SQL. Raw SQL can bypass ORM listeners; corruption detection is explicitly tested. An administrator able to rewrite both evidence and fingerprints is outside this guarantee.

## Migration

Revision `c3d4e5f6a7b8`, parent `b2c3d4e5f6a7`, adds only the three evaluation tables, series/cutoff index and phase-specific outer-target unique index. Upgrade matches ORM columns, types, nullability, defaults, primary/foreign keys, cascade behavior, finite checks, and uniqueness. Downgrade drops the outer index, children before parent and series index; no unrelated schema mutation exists.

Alembic has one source head, `c3d4e5f6a7b8`. Baseline migration history has one head, its parent. The new migration path/revision do not occur in baseline history or other reachable Git history. Runtime remains at `b2c3d4e5f6a7`: neither implementation nor hardening migrated or wrote to runtime. The PostgreSQL test creates a disposable schema, executes the real migration chain through the pre-T11 head, upgrades T11, verifies ORM/migration parity, round-trips a complete 92-point artifact through migration-created tables, then downgrades only T11 while preserving all baseline tables and sentinel data. Test schema changes are rolled back.

## Final tests

Each command was run independently using the repository virtual environment. Counts below are collected / passed / skipped / failed / errors.

- `pytest tests/test_forecast_evaluation.py`: 59 / 59 / 0 / 0 / 0.
- `pytest tests/test_forecast_evaluation_persistence.py`: 49 / 49 / 0 / 0 / 0.
- `pytest tests/test_forecast_dataset.py`: 5 / 5 / 0 / 0 / 0.
- `pytest tests/test_baseline_forecasting.py`: 7 / 7 / 0 / 0 / 0.
- `pytest tests/test_forecast_persistence.py`: 46 / 46 / 0 / 0 / 0.
- `pytest tests/test_grounded_rate_outlook.py`: 49 / 49 / 0 / 0 / 0.
- `pytest tests/test_decision_engine.py`: 78 / 78 / 0 / 0 / 0.
- `pytest tests/test_forecast_state.py`: 25 / 25 / 0 / 0 / 0.
- `pytest tests/test_reliability.py`: 135 / 135 / 0 / 0 / 0.
- `pytest tests/test_decision_api.py`: 106 / 106 / 0 / 0 / 0.
- `pytest tests/test_data_quality.py`: 8 / 8 / 0 / 0 / 0.
- `pytest tests/test_ai/`: 75 / 75 / 0 / 0 / 0.
- `pytest tests/`: 781 / 775 / 6 / 0 / 0.

Focused tests cover causality, all-candidate T04 parity, deterministic ties, fingerprints, immutability, denominator cases, insufficient/unsupported/invalid evidence, arithmetic overflow, aggregate reconstruction, exact snapshots, correction identity, atomic rollback, concurrency, migration parity/downgrade, corruption rejection, and exact-series extraction. Hardening adds seeded parity across 36 generated finite sequences, every outer cutoff perturbation, the full short-history matrix, irregular dates, Unicode/escaping, independent hash/formula oracles, unusual Decimal traps/flags, maximum exact money, direct-SQL corruption with retained ORM children, missing populations even with a matching content hash, outer cross-candidate uniqueness and concurrent conflicting-evidence rejection. A fresh subprocess blocks SQLAlchemy, database, FastAPI, Redis, Celery, Azure/OpenAI/provider imports and network sockets while importing/running the pure evaluator; it passes. Fresh normal imports of T04, T11, T03 and T06 callers also pass. AST comparisons prove unchanged T04 formulas/defaults and forecast-next behavior apart from the relocated import.

During development, initial tests incorrectly expected nonfinite input to reach an INVALID result rather than Pydantic rejection; those assertions were corrected. Migration testing caught an autogenerated unqualified Text constructor, corrected to sa.Text before the final successful runs. These initial failures are not hidden in the final count. Existing Pydantic configuration deprecation warnings and a Redis destructor/event-loop-closed warning appeared in the full suite; warnings were not suppressed.

## Read-only current-data findings

Runtime queries used explicit read-only transactions. During the hardening replay, infrastructure/persistence imports, socket creation and subprocess execution were trapped while pure evaluation ran in memory. Counts were read before and after and match: 248 FreightRate rows, 0 RateForecast rows, 0 RateOutlook rows. All three runtime evaluation tables are absent; no EvaluationRun was persisted. No forecast/outlook generation, database export, or fixture was created. Recomputed champion metrics, outer metrics, winner distributions, switches and directional counts match the original report without numerical changes.

There are eight SCFI-labelled local series, each with 31 consecutive stored dates from August 3 through September 2, 2026. Each series has 16 selection targets ×5 candidates =80 selection points and 12 nested outer points, totaling 640 selection and 96 outer points. This observed local spacing does not verify daily external SCFI publication. All input provenance remains UNVERIFIED; current data appears sample/seed-origin.

The figures below are rounded to six decimals for presentation. Triples are MAE / RMSE / sMAPE (%). Direction counts are correct/valid, with the denominator stated explicitly. Persisted evidence, if a caller later elects to persist it, retains unrounded float components.

- Egypt–China 20: final MA(3), selection 17.612500 / 22.148571 / 0.976840, direction 12/16 (75%). Outer 19.226111 / 23.953989 / 1.063756, direction 8/12 (66.666667%). Winners MA(3):12, switches 0. Dataset fingerprint prefix 60507464170a4a6b.
- Egypt–China 40: final MA(3), selection 27.095833 / 34.075444 / 0.976828, direction 12/16 (75%). Outer 29.578889 / 36.853546 / 1.063765, direction 8/12 (66.666667%). Winners MA(3):12, switches 0. Fingerprint prefix 5e488a1dc138ab38.
- Egypt–Europe 20: final MA(4), selection 12.960000 / 16.923149 / 0.939761, direction 13/16 (81.25%). Outer 13.113542 / 17.512583 / 0.949836, direction 9/12 (75%). Winners MA(4):12, switches 0. Fingerprint prefix afb3c84e5344f704.
- Egypt–Europe 40: final MA(4), selection 19.939844 / 26.037571 / 0.939825, direction 13/16 (81.25%). Outer 20.175417 / 26.943796 / 0.949870, direction 9/12 (75%). Winners MA(4):12, switches 0. Fingerprint prefix 34c86c722036bd65.
- UAE–Asia 20: final MA(4), selection 16.314219 / 18.521879 / 0.850471, direction 11/16 (68.75%). Outer 17.191667 / 19.440980 / 0.895537, direction 7/12 (58.333333%). Winners MA(2):3 and MA(4):9, switches 2. Fingerprint prefix 59fd943cd3454302.
- UAE–Asia 40: final MA(4), selection 25.099687 / 28.496637 / 0.850501, direction 11/16 (68.75%). Outer 26.449167 / 29.910624 / 0.895553, direction 7/12 (58.333333%). Winners MA(2):3 and MA(4):9, switches 2. Fingerprint prefix de3060d647666b01.
- UAE–Europe 20: final MA(3), selection 13.702708 / 16.764317 / 0.730591, direction 12/16 (75%). Outer 14.766667 / 17.888009 / 0.787116, direction 9/12 (75%). Winners MA(3):12, switches 0. Fingerprint prefix 85179ca0eea38a39.
- UAE–Europe 40: final MA(3), selection 21.081458 / 25.791834 / 0.730605, direction 12/16 (75%). Outer 22.718056 / 27.520821 / 0.787121, direction 9/12 (75%). Winners MA(3):12, switches 0. Fingerprint prefix f5db7ae8e159dc6c.

All other selection candidates are retained, not discarded. In the following order Naive / MA(2) / MA(3) / MA(4) / Drift, each entry is MAE, RMSE, sMAPE; direction correct count out of 16:

- Egypt–China 20: (18.030625,24.645477,1.003642;0), (19.711563,25.123075,1.097029;10), (17.612500,22.148571,0.976840;12), (19.248906,23.197358,1.067057;13), (18.686178,25.372329,1.040650;4).
- Egypt–China 40: (27.740000,37.914816,1.003662;0), (30.324063,38.650448,1.096977;10), (27.095833,34.075444,0.976828;12), (29.614062,35.688437,1.067070;13), (28.748624,39.033101,1.040673;4).
- Egypt–Europe 20: (20.836875,24.849788,1.510495;0), (17.024687,20.930679,1.234848;10), (13.954792,18.775933,1.012108;12), (12.960000,16.923149,0.939761;13), (21.377980,25.503743,1.549498;3).
- Egypt–Europe 40: (32.058750,38.233049,1.510589;0), (26.193438,32.202830,1.234923;10), (21.469583,28.887610,1.012139;12), (19.939844,26.037571,0.939825;13), (32.891192,39.239240,1.549591;3).
- UAE–Asia 20: (19.891875,24.282272,1.037657;0), (17.855625,21.697540,0.931065;11), (18.643750,20.745472,0.972119;10), (16.314219,18.521879,0.850471;11), (20.196768,24.630111,1.053066;9).
- UAE–Asia 40: (30.602500,37.357992,1.037645;0), (27.470625,33.382300,0.931080;11), (28.683333,31.917145,0.972142;10), (25.099687,28.496637,0.850501;11), (31.071014,37.893177,1.053035;9).
- UAE–Europe 20: (16.113125,20.316663,0.859707;0), (15.500312,18.995672,0.826693;10), (13.702708,16.764317,0.730591;12), (15.008125,16.851673,0.800696;12), (16.271006,20.801557,0.867752;9).
- UAE–Europe 40: (24.792500,31.258092,0.859813;0), (23.850000,29.225414,0.826811;10), (21.081458,25.791834,0.730605;12), (23.089844,25.926116,0.800711;12), (25.034883,32.004165,0.867841;9).

The approved m=4 outer results differ from an earlier exploratory m=1 replay by construction, not by a baseline formula regression. Current final champions remain four MA(3) and four MA(4).

## Limitations, boundaries, and team impact

Current history is short and unverified as external daily market history. Nested outer folds are dependent and retrospective. The inner minimum is exploratory. Outer evaluation assesses selection procedure, not an independently validated final champion. Historical freshness/availability cannot be faithfully reconstructed, and same-source provenance remains limited by ingestion metadata. Dates represent next stored observation positions in replay; no verified market cadence or new production target-date rule is introduced.

There is no calibrated uncertainty, prediction interval, confidence, decision-success probability, savings/counterfactual evaluation, or policy optimization. Error and stability statistics are descriptive evidence. No advanced model is unlocked and T05's data gate remains in place. Prospective validation requires genuinely new observations under a frozen protocol, with provenance and availability recorded before outcomes become known.

T06 persistence/API and production forecast artifacts, T08 decision rules, T09 reliability semantics, T10 Decision API, and T07 GPT grounding are unchanged. T11 has no RateForecast foreign key, decision/outlook dependency, public router, scheduler, GPT prompt, provider configuration, or production generation hook. No frontend change or new API contract exists. Backend impact is new internal evaluation services/models and a future separately reviewed migration deployment; frontend impact is none at this stage. No teammate was contacted.

Competition-safe claims are limited to auditable evaluation evidence, immutable application artifacts with documented administrative limits, expanding walk-forward candidate evaluation, outer temporal evaluation of selection procedure, targets excluded from their own selection, explicit directional denominator, and reproducible residual evidence. No claim of statistically proven champion, independent real-market validation, optimal booking, calibrated confidence, or proven savings is justified.

## Hardening defects and scope reconciliation

Three integrity weaknesses were confirmed and fixed minimally: generic point uniqueness allowed multiple outer candidates at one target; cached child ORM objects could mask direct-SQL corruption during load; and phase completeness lacked an independent structural check when stored content/header metadata agreed with a malformed population. ORM and migration now share the partial unique index; child queries refresh persisted values. Loading checks phase completeness independently of the content hash, and translates malformed validation/configuration into an integrity error. No T04 formula or policy change was needed.

The pre-hardening authoritative inventory was 8 new files, 2 modified files, 1,221 additions and 4 deletions. The migration was 86 new lines, not a modification. The external 1,136/5 display is exactly reproduced by replacing that migration's +86/0 with +1/-1: 1,221−86+1=1,136; 4+1=5. That display therefore reflects an incremental migration edit rather than its complete new-file contribution against Git baseline. Its UI internals are unavailable; repository/history evidence establishes the authoritative classification. Final counts must include full untracked file contents alongside Git numstat for the two tracked modifications.

No protected file changed. All eight original SHA-256 fingerprints match, and the files remain untracked/unstaged. Security scans found no secrets, credentials, DSNs, private keys, local absolute paths or runtime artifacts in T11 scope. Tracked and every untracked T11 file pass explicit whitespace checks. The index remains empty and baseline Git state remains unchanged.

Final recommendation: READY TO STAGE after separate human review. No staging authorization is inferred from this verdict.
