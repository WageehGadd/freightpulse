# AI-V3-T04: Baseline Forecasting & Backtesting

## 1. Executive Summary
The T04 Baseline Forecasting layer establishes honest, deterministic quantitative benchmarks for the current FreightPulse dataset. Utilizing strictly chronological walk-forward evaluation, simple baselines (Naive, MA2, MA3, MA4, Drift) were backtested against the limited 31-observation series. MA(4) achieved the lowest macro-average MAE and is therefore selected as the default/global benchmark, while per-series model selection remains independent. Because historical depth is classified as `MINIMAL`, no advanced machine learning models were trained. T04 establishes the performance floor that any future T05 advanced model must decisively beat.

## 2. Scientific Constraints
- **Model Complexity is not the goal.** Small datasets demand simple algorithms to prevent overfitting.
- **Strict Chronological Backtesting.** Walk-forward validation without shuffling or arbitrary training/test splits.
- **Univariate only.** T03 proved there is no valid historical overlap for exogenous features (Bunker, FX, Advisories).

## 3. Actual Dataset
- Consumes the T03 `ForecastDataset`.
- **Series Evaluated:** 8 distinct lanes.
- **Observations:** Exactly 31 daily observations per lane.
- **Date Range:** `2026-08-03` to `2026-09-02`.

## 4. Models Considered
- **Naive:** 1-step lag (predicts exactly the previous day's rate).
- **MA(2):** 2-period moving average.
- **MA(3):** 3-period moving average.
- **MA(4):** 4-period moving average.
- **Drift:** Forecasts linearly based on the slope between the first and last observation of the training window.

## 5. Models Rejected/Deferred
- **Seasonal Naive:** Excluded. With only 31 daily mocked observations representing a nominally weekly SCFI index, there is no defensible basis for 7-day or 30-day seasonality. 
- **SARIMA / LightGBM / Neural Nets:** Excluded. 31 observations constitute `MINIMAL` evidence. Deep parameterization would overfit catastrophically.
- **Exogenous Models:** Excluded due to zero historical overlap with Bunker/FX/Advisories.

## 6. Walk-Forward Methodology
Chronological Expanding Window (Walk-Forward). For each prediction $t$, the model only trains on observations $1$ through $t-1$.

## 7. Initial Training Window
$k = 15$. Selected deterministically to balance having enough history for early moving averages/drift calculations against preserving enough points for evaluation. This yields exactly **16 evaluation points** per series.

## 8. Forecast Horizon
**1-Step Ahead.** Multi-step horizons were strictly deferred, as a 31-point dataset lacks statistical stability to project deep into the future.

## 9. Metrics
Evaluated per observation, then aggregated over the 16 walk-forward evaluation points per series (yielding 8 series × 16 points = 128 series-time evaluation points PER baseline model):
- **MAE:** Mean Absolute Error (Primary selection metric).
- **RMSE:** Root Mean Squared Error.
- **sMAPE:** Symmetric Mean Absolute Percentage Error.
- **Directional Accuracy:** Percentage of correct direction predictions (relative to prior actual).

## 10. Model Selection Policy
The baseline champion is selected deterministically per series by sorting models first by lowest MAE, followed by lowest RMSE as a tiebreaker.

## 11. Per-Series Results
| Series | Evals | Naive MAE | MA2 MAE | MA3 MAE | MA4 MAE | Drift MAE | Best | Best MAE | DirAcc |
|--------|-------|-----------|---------|---------|---------|-----------|------|----------|--------|
| SCFI_Egypt-China_20ft | 16 | 18.0 | 19.7 | 17.6 | 19.2 | 18.7 | **MA(3)** | 17.6 | 75.0% |
| SCFI_Egypt-China_40ft | 16 | 27.7 | 30.3 | 27.1 | 29.6 | 28.7 | **MA(3)** | 27.1 | 75.0% |
| SCFI_Egypt-Europe_20ft | 16 | 20.8 | 17.0 | 14.0 | 13.0 | 21.4 | **MA(4)** | 13.0 | 81.2% |
| SCFI_Egypt-Europe_40ft | 16 | 32.1 | 26.2 | 21.5 | 19.9 | 32.9 | **MA(4)** | 19.9 | 81.2% |
| SCFI_UAE-Asia_20ft | 16 | 19.9 | 17.9 | 18.6 | 16.3 | 20.2 | **MA(4)** | 16.3 | 68.8% |
| SCFI_UAE-Asia_40ft | 16 | 30.6 | 27.5 | 28.7 | 25.1 | 31.1 | **MA(4)** | 25.1 | 68.8% |
| SCFI_UAE-Europe_20ft | 16 | 16.1 | 15.5 | 13.7 | 15.0 | 16.3 | **MA(3)** | 13.7 | 75.0% |
| SCFI_UAE-Europe_40ft | 16 | 24.8 | 23.8 | 21.1 | 23.1 | 25.0 | **MA(3)** | 21.1 | 75.0% |

## 12. Aggregate Results (Macro Averages)
| Model | Macro MAE | Macro RMSE | Macro sMAPE | Macro DirAcc |
|-------|-----------|------------|-------------|--------------|
| Naive | 23.76 | 29.86 | 1.10 | 0.0% |
| MA(2) | 22.24 | 27.53 | 1.02 | 64.1% |
| MA(3) | 20.28 | 24.89 | 0.92 | 71.9% |
| **MA(4)** | **20.16** | **23.96** | **0.91** | **76.6%** |
| Drift | 24.28 | 30.56 | 1.13 | 39.1% |

*(Note: Naive scores 0.0% directional accuracy because it predicts exactly the last value, meaning the predicted change is exactly zero, yielding no correct directional signals).*

## 13. Champion Baseline
MA(4) achieved the lowest macro-average MAE (20.16) and superior Directional Accuracy (76.6%), and is therefore selected as the default/global benchmark, while per-series model selection remains independent.

## 14. Next-Step Forecast Evidence
| Series | Baseline | Next Fcst | Hist MAE | Live_Use |
|--------|----------|-----------|----------|----------|
| SCFI_Egypt-China_20ft | MA(3) | 1831.54 | 17.61 | False |
| SCFI_Egypt-China_40ft | MA(3) | 2817.76 | 27.10 | False |
| SCFI_Egypt-Europe_20ft | MA(4) | 1371.45 | 12.96 | False |
| SCFI_Egypt-Europe_40ft | MA(4) | 2109.93 | 19.94 | False |
| SCFI_UAE-Asia_20ft | MA(4) | 1927.29 | 16.31 | False |
| SCFI_UAE-Asia_40ft | MA(4) | 2965.06 | 25.10 | False |
| SCFI_UAE-Europe_20ft | MA(3) | 1877.74 | 13.70 | False |
| SCFI_UAE-Europe_40ft | MA(3) | 2888.83 | 21.08 | False |

## 15. Freshness / Live-Use Warning
The latest observation is from `2026-09-02`. Therefore, T04 correctly honors the T02 data quality freshness tag (`stale`), preventing the forecast generated in T04 from being erroneously recommended to business logic as active booking advice (`live_decision_eligible=False`).

## 16. Leakage Prevention
Walk-forward indices are strictly enforced. When predicting index `k`, the internal algorithms use `y[:k]` only. Extreme out-of-distribution values injected as future observations do not alter past predictions, verified by deterministic tests.

## 17. Exogenous Exclusion
Confirmed. The input payload relies solely on `obs.target_rate`. Features like `bunker_usd` or `fx_usd_egp` generated by T03 as `None` are ignored entirely.

## 18. Tests
- 8 focused deterministic tests for Baseline Forecaster (naive, moving averages, drift, leakage validation, empty inputs, deterministic champion selection).
- 133 full suite integration tests.

## 19. Files Changed
- `app/services/baseline_forecasting.py` (New Forecaster Domain Service)
- `tests/test_baseline_forecasting.py` (Test suite)
- `docs/FREIGHTPULSE_AI_V3_T04_BASELINE_FORECASTING_REPORT.md` (Report)

## 20. Known Limitations
With only 16 walk-forward evaluation points per lane, model superiority claims are mathematically weak. A single outlier observation heavily skews the aggregated RMSE or MAE. The victory of MA(4) demonstrates a mild smoothing preference, but shouldn't be interpreted as proof that a 4-day lag is structurally superior for real SCFI weekly data.

## 21. T05 Decision
**T05 Advanced Forecasting is DATA-GATED.** 
T05 remains locked until substantially deeper, real, provenance-verified historical series are available and model-specific feasibility can be demonstrated through chronological backtesting. Materially larger history (e.g. 100+ observations) would improve feasibility, but building LightGBM/SARIMA on the current 31 observations is anti-scientific.

## 22. T06 Readiness
T06 is unlocked. We now have a defensible (albeit structurally simple) baseline framework. T06 should focus strictly on persisting these Baseline outputs to a new `rate_forecasts` table, wrapping them with the `live_decision_eligible=False` warning, and exposing them via an API so the UI can draw the benchmarking charts.

## 23. Competition-Safe Claims
**WHAT WE CAN CLAIM:**
- FreightPulse has a real deterministic quantitative forecasting framework.
- It performs chronological walk-forward backtesting.
- It compares transparent statistical baselines.
- It measures MAE, RMSE, sMAPE, and directional accuracy.
- It performs per-series model selection.
- MA(4) currently provides the best macro-average MAE.
- Numerical forecasts are generated algorithmically, not by the LLM.
- Future models will be required to beat measured baselines.

**WHAT WE CANNOT YET CLAIM:**
- strong production forecasting accuracy
- statistically mature long-horizon forecasting
- validated seasonality
- advanced ML superiority
- live decision-grade forecasts from the current stale freight observations
- calibrated probabilistic confidence
- causal prediction
