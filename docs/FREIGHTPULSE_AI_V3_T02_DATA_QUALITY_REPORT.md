# AI-V3-T02: Data Quality & Freshness Layer

## 1. Executive Summary
The T02 Data Quality Layer was successfully implemented as a deterministic, reusable service. It correctly evaluates the availability, freshness, completeness, and provenance of all key FreightPulse datasets without relying on heuristics or language models. The result is a robust foundation that will safely gate untrusted or stale data from polluting future Forecasting and Decision Intelligence pipelines.

## 2. Pre-T02 Architecture
Before T02, FreightPulse scraped and stored data (T01 introduced persistent Bunker and FX history), but the system lacked semantic awareness of its own data's quality. 
- Freshness was implied merely by database timestamps.
- Time-series gaps were untracked.
- Port Congestion data, despite being mock/seeded, could theoretically masquerade as live data if it had a recent timestamp.

## 3. Data Quality Contract
A centralized Pydantic model `DataQualityReport` acts as the domain contract. It exposes:
- `signal_name` and `source_type` (live, periodic, seeded).
- `record_count`, `available`.
- `latest_observation_at`, `age_seconds`.
- `expected_cadence_seconds`.
- `freshness_status` (fresh, aging, stale, unknown, not_applicable).
- `completeness_status` (complete, gaps, unknown, not_applicable) and `missing_periods`.
- `usable_for_forecasting` and `usable_for_decisioning` (booleans).
- `warnings`.

## 4. Source Policy
The `DataQualityService` codifies policies based on actual source behavior:
- **Freight Rates:** Periodic (weekly). Expected cadence = 7 days. 
- **Bunker Rates:** Periodic (daily). Expected cadence = 1 day.
- **Exchange Rates:** Periodic (daily). Expected cadence = 1 day.
- **Carrier Advisories:** Live/Event-driven. No expected cadence.
- **Port Congestion:** Seeded/Static mock data.

## 5. Freshness Algorithm
Freshness for periodic signals is calculated strictly relative to expected cadence:
- `ratio = age / expected_cadence`
- Ratio ≤ 1.5 → `fresh`
- Ratio ≤ 3.0 → `aging`
- Ratio > 3.0 → `stale`
Event-driven signals and static signals are marked `not_applicable` and `unknown` respectively.

## 6. Completeness Algorithm
Completeness evaluates chronological density for periodic signals:
- `expected_periods = (latest_date - earliest_date) / cadence + 1`
- `missing_periods = max(0, expected_periods - distinct_dates)`
- If `missing_periods == 0`, status is `complete`, otherwise `gaps`.

## 7. Provenance Classification
- `live`: Carrier advisories (real event-driven).
- `periodic`: Freight, Bunker, FX (real chronological observation).
- `seeded`: Port Congestion (static mock data).

## 8. Forecast Eligibility Rules
Forecasting eligibility gates signals that lack historical depth or predictable cadences.
- Freight Rates: Requires > 4 distinct periods (weeks).
- Bunker / FX: Requires ≥ 7 distinct periods (days).
- Advisories / Port Congestion: Unusable for time-series forecasting.

## 9. Decision Eligibility Rules
Decision eligibility gates signals that are unsafe for live Decision Intelligence.
- Periodic signals: Eligible if `fresh` or `aging` (ratio ≤ 3.0).
- Event-driven signals: Eligible if they exist.
- Seeded signals (Port Congestion): Explicitly ineligible.

## 10. Port Congestion Safety Handling
Port congestion is definitively flagged as `source_type="seeded"`. It is mathematically blocked from live decision engines (`usable_for_decisioning = False`) regardless of how recent its `measured_at` timestamp is, preventing AI hallucinations based on mock data.

## 11. Runtime Quality Snapshot
Executed against the live local PostgreSQL database:
| Signal               | Source Type     | Records | Latest Obs                | Age (s)    | Freshness       | Coverage        | Forecast Eligible  | Decision Eligible  | Warnings |
|----------------------|-----------------|---------|---------------------------|------------|-----------------|-----------------|--------------------|--------------------|----------|
| freight_rates        | periodic        | 248     | 2026-09-02 00:00:00+00:00 | 2559763.2  | stale           | complete        | YES                | NO                 | Data is stale |
| bunker_rates         | periodic        | 9       | 2026-10-01 00:00:00+00:00 | 54163.2    | fresh           | complete        | NO                 | YES                | |
| exchange_rates       | periodic        | 1       | 2026-10-01 00:00:00+00:00 | 54163.2    | fresh           | complete        | NO                 | YES                | |
| carrier_advisories   | live            | 3       | 2026-09-01 11:55:53+00:00 | 2603209.4  | not_applicable  | not_applicable  | NO                 | YES                | |
| port_congestion      | seeded          | 6       | 2026-09-02 11:55:53+00:00 | N/A        | unknown         | not_applicable  | NO                 | NO                 | Port congestion is seeded mock data and MUST NOT be used for live decisioning. |

## 12. Tests
- 8 new focused data quality tests verifying availability, freshness, source provenance, port congestion security, completeness with gaps, event-driven data, forecast eligibility.
- `tests/test_historical_persistence.py` (2 passed).
- `tests/test_ai/` (75 passed).
- Full suite (128 passed).

## 13. Files Changed
- `app/services/data_quality.py` (New service and contract)
- `tests/test_data_quality.py` (New test suite)
- `t02_runtime_validation.py` (Temporary execution script)

## 14. Known Limitations
- The exact missing periods calculation uses `(latest - earliest) / cadence` versus `count(distinct_date)`. This is highly accurate for strictly periodic upserted data, but may slightly undercount gaps if multiple observations occurred on a single period erroneously.

## 15. T03 Readiness
The Data Quality Layer perfectly positions T03 to filter out "stale" or "insufficiently covered" datasets before they ever enter the dataset construction phase. T02 is 100% complete.

## 16. Recommendations for T03
When building T03 (Forecast Dataset Pipeline), explicitly inject `DataQualityService`. Any signal where `report.usable_for_forecasting == False` must trigger a short-circuit rejection rather than producing a malformed dataset matrix.

---
### Design Questions Answered

1. **What is the expected cadence of each actual FreightPulse signal?**
   Freight: Weekly. Bunker/FX: Daily. Advisories: Event-driven. Port Congestion: Static mock.
2. **Which cadence values are verified by repository behavior and which are policy assumptions?**
   Freight, Bunker, FX cadences are strongly implied by scraping behavior (T00/T01). Carrier Advisory is proven event-driven by RSS structure. Port Congestion is known seeded.
3. **How is freshness calculated?**
   `age / expected_cadence`. ≤ 1.5 is fresh, ≤ 3.0 is aging, > 3.0 is stale.
4. **How do we prevent a recent database timestamp from making old/static data appear fresh?**
   Port Congestion is explicitly hardcoded in the Quality Service as `seeded` and `usable_for_decisioning=False`. Its timestamp is intentionally ignored.
5. **How is weekly data treated differently from daily data?**
   Freight uses a 7-day expected cadence, so an age of 4 days yields a ratio of ~0.57 (Fresh), whereas an age of 4 days for Bunker (1-day cadence) yields a ratio of 4.0 (Stale).
6. **How are event-driven advisories treated?**
   Event-driven data is considered active until superseded; freshness is marked `not_applicable`, age is not penalized, and it remains decision-eligible.
7. **What does "forecast eligible" mean at T02?**
   It means the dataset has enough chronological depth (e.g. > 4 weeks for freight, ≥ 7 days for daily signals) and is periodic, making it mathematically valid for time-series extraction.
8. **What does "decision eligible" mean at T02?**
   It means the data is a real, live or periodic source that is not excessively stale (ratio ≤ 3.0).
9. **Which current signals are actually trustworthy enough for future Decision Intelligence?**
   Bunker, FX, Carrier Advisories, and Freight Rates (if they become fresh).
10. **Which current signals are NOT trustworthy?**
   Port Congestion (mock data).
11. **Does T02 require any new database schema?**
    NO. Computed dynamically.
12. **Does T02 require any paid service?**
    NO.
