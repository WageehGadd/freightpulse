# AI-V3-T03: Forecast Dataset Pipeline

## 1. Executive Summary
The T03 Forecast Dataset Pipeline successfully converts raw database observations into a deterministic, chronological, and leakage-safe machine learning dataset ready for baseline forecasting (T04). It profiles actual per-series depth, dynamically extracts calendar and lag/rolling features strictly from historical data, and correctly blocks future observations from entering past rows.

## 2. Pre-T03 Repository State
Prior to T03, FreightPulse stored target and exogenous data with basic semantic validation but lacked any formal mechanism to align time series. Total rows (248) were misunderstood as dataset size. Exogenous history for Bunker and FX had just been seeded, lacking long-term overlap with freight data. 

## 3. Actual Data Profiling
T03 explicitly prevents conflating raw database row count with dataset depth.
- **Total Freight Rows:** 248
- **Distinct Forecasting Series:** 8
- Each series currently contains exactly 31 observations spanning 30 days.
*Note: The repository/runtime evidence proves that FreightPulse currently stores 31 consecutive daily FreightRate observations per series under its current SCFI ingestion/seeded data behavior. This does not imply we have proven that the Shanghai SCFI itself provides 31 genuine daily historical index observations.*

## 4. Forecasting Series Definition
A distinct forecasting series is explicitly defined by the combination of:
`source + trade_lane + container_type`
All sorting, feature engineering, and deduplication occurs strictly per series.

## 5. Dataset Readiness Policy
Categorized deterministically based on contiguous distinct dates:
- `INSUFFICIENT`: < 30 dates
- `MINIMAL`: 30-99 dates
- `BASELINE_READY`: 100-299 dates
- `EXTENDED_HISTORY`: ≥ 300 dates
Currently, all 8 series are classified as `MINIMAL`. 
*Note: `MINIMAL >= 30` observations is a T03 internal dataset-readiness policy. It is NOT statistical proof that 31 observations are sufficient for a particular forecasting model. Model suitability and performance must be determined empirically in T04/T05.*

## 6. Data Quality Integration
T03 correctly distinguishes `historical_dataset_usable` from `current_signal_freshness`. While T02 marks the Freight data as `stale` (latest is Sep 02), T03 acknowledges it is a contiguous, valid historical block that is structurally safe for backtesting/training, avoiding unnecessary aborts.

## 7. Dataset Contract
The pipeline enforces a typed Pydantic contract: `ForecastDataset` containing a `metadata` envelope (`ForecastDatasetMetadata`) and a list of `ForecastObservation` rows, making it trivially consumable by any T04 model structure.

## 8. Target Definition
The target is the unmodified `rate_usd` at `rate_date`, mapped to `target_rate` at `date`. No forward-filling, interpolation, or horizon shifting is forced prematurely.

## 9. Calendar Features
Target-independent and leakage-safe: `year`, `month`, `week_of_year` (ISO calendar).

## 10. Lag Features
Strict shifted history: `lag_1`, `lag_2`, `lag_4`. Missing initial values are retained as explicit `None`. 

## 11. Rolling Features
Target-independent shifting prevents current-observation leakage:
`rolling_mean_4` and `rolling_std_4` are calculated on a shifted frame (i.e. strictly prior to `date`).

## 12. Bunker Integration / Coverage
Integrated via strict backward `merge_asof`.
- **Actual Coverage:** Starts `2026-10-01`. 
- **Overlap:** 0 days with freight history (ends `2026-09-02`). Therefore, `bunker_usd` evaluates perfectly safely to `None` for all current historical rows.

## 13. FX Integration / Coverage
Integrated via strict backward `merge_asof`.
- **Actual Coverage:** Starts `2026-10-01`.
- **Overlap:** 0 days. Evaluates to `None`.

## 14. Advisory Integration / Coverage
Not integrated in T03. Carrier advisories are sparse (3 records) and event-driven. Converting these to a generic numeric feature (like counts) is mathematically dubious without an explicit event-decay strategy. Deferred.

## 15. Port Congestion Exclusion
Port congestion is strictly excluded from dataset features. T02 metadata classifies it as `seeded` and `usable_for_decisioning=False`.

## 16. Missing-Data Policy
Missing target periods remain explicitly missing; there is absolutely no synthetic fabrication or interpolation of freight rates. Exogenous signals missing from history evaluate to `None`, not 0, preserving true non-availability.

## 17. Leakage Prevention
Leakage is strictly prevented by:
1. `shift()` application before `rolling()` (prevents current target leaking into historical stats).
2. `direction="backward"` in `merge_asof` (guarantees external data is strictly ≤ target date).
3. Hard sorting by `rate_date` ascending.
4. Deterministic deduplication.

## 18. Feature Metadata
```json
[
  "year", "month", "week_of_year",
  "lag_1", "lag_2", "lag_4",
  "rolling_mean_4", "rolling_std_4",
  "bunker_usd", "fx_usd_egp"
]
```

## 19. Runtime Dataset Evidence
```
Series                         | Source | Lane            | Container  | Obs  | Start      | End        | Span | Missing | Readiness
--------------------------------------------------------------------------------------------------------------------------------------------
SCFI_Egypt-China_20ft          | SCFI   | Egypt-China     | 20ft       | 31   | 2026-08-03 | 2026-09-02 | 30   | 0       | MINIMAL
...
```

## 20. Tests
- 5 focused T03 tests (Profiling, Ordering, Leakage, ASOF joins, Nulls).
- Full suite (133 tests passed).

## 21. Files Changed
- `app/services/forecast_dataset.py` (New Pipeline)
- `tests/test_forecast_dataset.py` (New Test Suite)
- `docs/FREIGHTPULSE_AI_V3_T03_FORECAST_DATASET_REPORT.md` (Documentation)

## 22. Known Limitations
With exactly 31 contiguous observations per series, dataset sizes are currently `MINIMAL`. Advanced ML algorithms (e.g. LightGBM, neural networks) will severely overfit this limited depth.

## 23. T04 Readiness
The pipeline is 100% complete and ready. T04 can inject `ForecastDatasetBuilder.build_dataset(series)` and immediately receive a perfectly ordered, feature-rich Pandas-backed observation list.

## 24. Recommendation for T04
Due to the `MINIMAL` dataset size (31 points), T04 must strictly avoid complex neural networks or deeply parameterised gradient boosters. T04 should focus exclusively on simple, robust, low-parameter baselines (e.g., naive lags, simple ARIMA, or basic linear regression) that can generalize gracefully on micro-datasets.

---

### Mandatory Report Questions Answered
1. **Total freight-rate rows:** 248.
2. **Distinct forecasting series:** 8.
3. **What defines one series?** `source + trade_lane + container_type`.
4. **Observations per series:** 31.
5. **Real date range:** 2026-08-03 to 2026-09-02.
6. **Are 248 rows actually useful?** No, 248 is the sum across 8 distinct lanes. Each lane only has 31 rows, which is `MINIMAL`.
7. **Which are baseline-ready?** None are strictly baseline ready (>100). All 8 are `MINIMAL`.
8. **Which are NOT ready?** None are `INSUFFICIENT` (<30), but 31 is the absolute bare minimum to test an algorithm.
9. **Bunker overlap:** 0 days.
10. **FX overlap:** 0 days.
11. **Carrier advisories useful?** No. Sparse and event-driven, excluded.
12. **Why is Port Congestion excluded?** Seeded/static mock data.
13. **How are lag features protected?** Calculated strictly via `.shift(N)` on ascending sorted data.
14. **How are rolling features protected?** Calculated via `.shift(1).rolling(W)` ensuring the current target is blind to the rolling frame.
15. **How are external signals joined?** `pd.merge_asof(direction="backward")` ensures strictly prior or equal timestamps.
16. **Fabricate/interpolate targets?** NO.
17. **Train any forecasting model?** NO.
18. **Introduce paid service?** NO.
19. **Require a migration?** NO.
20. **What EXACTLY should T04 implement?** Naive lag or highly constrained unparameterised models (ARIMA(1,0,0) or simple linear models) that don't overfit 31 rows.
