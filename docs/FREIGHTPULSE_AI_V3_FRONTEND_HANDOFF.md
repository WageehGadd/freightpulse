# FreightPulse AI V3 — Frontend Handoff

## 1. Handoff Context

AI V3 CODE STATUS = COMPLETE FOR APPROVED SCOPE

Baseline: `de65aff978234cd1b43a0050ebf92b9293951334`. Frontend owns product presentation and interaction. Implemented/tested AI code is not proof of deployment, populated runtime data or product integration. Backend adapters remain necessary for T14/T17/T18 consumption. T05/T15 remain DATA-GATED; T12/T13/T16 are Frontend handoffs. See [Final Status](FREIGHTPULSE_AI_V3_FINAL_STATUS.md) and [Backend Handoff](FREIGHTPULSE_AI_V3_BACKEND_HANDOFF.md).

## 2. Existing Frontend Areas

The handoff covers forecast/rate view, decision card, evidence panel, hypothetical scenario controls, market-lane evidence dossier and predictive alerts. This backend repository supplies T06/T07/T10 APIs; it does not certify completion of a separate frontend repository, which was not modified.

Current consumable boundaries are `/api/v1/forecasts`, `/api/v1/forecasts/latest`, `/api/v1/decisions/latest`, and grounded outlook create/read routes under `/api/v1/rates`. T17/T18 core names below are internal Python contracts, not public HTTP endpoints. T14 proposals require Backend acceptance/delivery before UI consumption.

## 3. T12 — Forecast UI

T06 `ForecastListResponse` in `app/schemas/forecast.py` contains `forecasts` and `count`. Each `RateForecastResponse` separates `series`, `forecast`, `evidence`, `provenance`, `safety` and ID.

Show exact source/lane/container, `predicted_rate`, `forecast_for_date`, `horizon`, `model` and `model_version`; history/evaluation counts, MAE/RMSE/sMAPE/directional accuracy, readiness and limitations. T06 monetary fields are JSON numbers. T07 `exact_values` and T10 Decimal fields use JSON strings; preserve those exact values rather than recomputing policy in browser arithmetic.

Distinguish stored `input_freshness_at_generation`, read-time `current_input_freshness`, `freshness_evaluated_at` and `generated_at`. Generation time does not refresh source data. T06 stored safety is not full current source/forecast supersession eligibility; use T10 current decision state where required. Current +1-day targets represent the local dataset contract, not verified daily SCFI publication.

No unsupported probability/confidence display. Deterministic forecast evidence remains visible when narration is pending or unavailable.

## 4. T13 — Decision Card

`GET /api/v1/decisions/latest` requires exact `source`, `trade_lane`, `container_type`. `DecisionAPIResponse` in `app/schemas/decision_api.py` separates identity, forecast, decision, evidence, current state, policy and provenance.

Decisions are `CONSIDER_EARLIER_BOOKING`, `CONSIDER_LATER_BOOKING`, `MONITOR`, `WITHHOLD`, `UNAVAILABLE`. Only the two directional suggestions can have `actionable=true`; do not override supplied actionability. Movement is `INCREASE`, `DECREASE`, `NEGLIGIBLE`, or `UNDEFINED`. Display reasons/blockers and evidence separately from GPT prose. WITHHOLD/MONITOR can be successful 200 responses; missing persisted forecast is 404, not an invented decision.

Show movement, error scale, policy and methodology identity where useful. `decision-rules-v1` thresholds are heuristic, not learned optimal booking policy. MAE guard is not a confidence interval; readiness does not prove accuracy. Honor `Cache-Control: no-store` and avoid presenting old eligibility as current.

## 5. T16 — Evidence Panel

T09 is **Evidence Assessment**, never AI confidence, probability, chance of success or prediction confidence. Show historical evidence status, sample sufficiency, decision evidence status, errors, normalized ratios, explanatory factors and assessment limitations from T10.

AVAILABLE is not high reliability; POLICY_MINIMUMS_MET is not statistical validation; DIRECTIONAL_RULES_PASSED is not probability of correctness. Preserve the unavailable directional denominator rather than using evaluation count as its substitute. T11 historical evaluation, if later exposed, still does not supply calibrated confidence. Keep missing evidence and selection-window limitations visible.

## 6. Scenario Intelligence UI

T17 `ScenarioRequest` / `ScenarioResult` in `app/schemas/scenario.py` and `evaluate_scenario` in `app/services/scenario_intelligence.py` are pure contracts awaiting a Backend adapter.

Always label the UI **HYPOTHETICAL / NON-OPERATIONAL**. Category is `MARKET_WHAT_IF`; one assumption supports `ABSOLUTE_PREDICTED_RATE` or `PERCENTAGE_ADJUSTMENT` with `requested_value`, according to the eventual Backend contract. Do not expose baseline/state/policy editing as authoritative facts.

Display factual baseline result/evidence, requested/applied assumption, hypothetical result, decision change and added/removed blockers. Percentage adjustment is relative to baseline predicted rate, not latest actual. `live_actionable` must remain `false` regardless of nested hypothetical rule actionability. The assumed rate is not predicted to occur; no causal effect or probability is established. Never present or trigger scenario output as a factual operational alert.

## 7. Route Evidence UI

T18 `RouteEvidenceRequest` / `RouteEvidenceResult` in `app/schemas/route_intelligence.py` and `compose_route_evidence` in `app/services/route_intelligence.py` await Backend lineage/API integration.

Present **market-lane evidence**, exact series, unchanged deterministic decision/evidence, advisory provenance/qualification/conflicts and operational availability gaps. Source context and derived summaries must remain distinguishable; seeded/unverified context is excluded from factual support. Advisory context is not decision-authoritative. A fingerprint is not proof of source truth.

Physical route, port operations, distance, transit time, route alternatives/ranking and operational risk remain unavailable under this methodology. Do not display best/optimal/recommended physical route, ETA prediction, delay probability, risk score or savings calculator.

## 8. Predictive Alert UI

Consume Backend-operationalized T14 events only after checkpoint acceptance, deduplication, concurrency and delivery are implemented. Internal `PredictiveAlertResult` can be BASELINE_ONLY, EMIT, SUPPRESS or INVALID_INPUT; it is not itself a delivered notification.

Distinguish entered/reversed directional transitions from operational actionability withdrawal. First observation is baseline-only. Do not create fake repeated alerts by polling identical state, and do not relabel hypothetical T17 results as factual events. Backend owns tenant delivery; UI consumes its accepted event contract.

## 9. Grounded GPT Narration

T07 uses `POST /api/v1/rates/trends/{trend_id}/outlook` (202) and `GET /api/v1/rates/outlooks/{outlook_id}`. `GroundedOutlookResponse` in `app/schemas/outlook.py` retains quantitative evidence, exact values, read-time context/effective eligibility and separate narration status/text/error/retry state. Creating narration is an authenticated Backend operation, not a reason to ship privileged credentials to the browser.

Grounded `rate_outlook/v2` output explains application-owned forecast evidence; T08 supplies decision authority. Legacy GPT Route Brief or RateTrend recommendation/confidence fields must not feed the V3 decision card.

Pending, failed or unavailable narration requires an honest state, not fabricated replacement prose. Keep deterministic evidence visible. Respect superseded/historical/source-unavailable context and supplied retry timing; do not make narration appear current solely because it recently completed.

## 10. Data Quality and Freshness UX

Present supplied available/unavailable, unknown freshness, stale/withheld and superseded states. Do not substitute ingestion/storage timestamps for missing publication time. Event-driven advisory freshness `not_applicable` does not mean independently verified fresh market data. Generation timestamp and source timestamp have different meanings. Do not invent Live badges.

## 11. Seeded / Demo Data Labeling

Label seeded, demo, synthetic, example-based or unverified data honestly. Implemented data collection capability is not verification of all stored observations. T05 advanced forecasting and T15 live-port capability remain DATA-GATED. The previous audit found absent runtime forecasts/outlooks and an unapplied T11 migration; these were not rechecked during closure/document preparation. Integration and deployment must precede claims of operational product availability.

## 12. Security Constraint

Do not expose privileged/shared Backend API secrets in public browser bundles, URLs or configuration. Browser access must follow Backend/Deployment's approved authentication and tenant architecture. Existing REST contracts do not certify WebSocket, test-alert or browser-secret safety. These findings remain team-owned; no separate frontend repository or security implementation was changed here.

## 13. Scientific Language — Allowed vs Forbidden

| Safer language when evidence supports it | Unsupported language to avoid |
| --- | --- |
| Forecast / historical baseline evaluation | 95% confidence / AI certainty / probability of rate increase |
| Evidence Assessment / deterministic decision | Chance of success / learned-optimal booking policy |
| Hypothetical scenario / sensitivity analysis | Predicted scenario occurrence / causal effect |
| Market-lane evidence | Best/optimal route / ETA / delay or risk probability |
| Data unavailable / source status disclosed | Verified real-time port congestion / invented Live badge |
| Grounded explanation | AI guarantees / guaranteed or expected savings |
| Tested baseline methodology | Advanced-model superiority |

Stronger claims require separately validated future capability, not a UI label or reinterpretation of current metrics.

## 14. Loading / Error / Empty States

- No persisted forecast: explicit empty state; T10 404 is not fabricated evidence.
- Forecast generation pending: show only a status actually supplied by Backend; T06 generation is synchronous and exposes no pending-job contract.
- Outlook pending/failed/unavailable: preserve quantitative evidence and show actual narration state.
- Evidence withheld: show reasons/blockers; do not treat it as a generic loading error.
- Source data unavailable or freshness unknown: retain those distinctions.
- Scenario adapter/request unavailable: no sample result masquerading as actual output.
- Route operational evidence unavailable: explicit gaps, not zero-risk defaults.
- Alert feed empty: no fake notification or frontend-only transition.

Handle authentication, validation, rate-limit and sanitized server errors separately. Do not substitute fake content in any state.

## 15. Frontend Acceptance Checklist

These are pending product acceptance criteria, not completed Frontend implementation claims.

- [ ] Forecast UI preserves exact series identity.
- [ ] No unsupported confidence percentage or probability.
- [ ] Decision visually separated from narration; supplied actionability respected.
- [ ] Evidence limitations and missing-data states visible.
- [ ] Scenario clearly HYPOTHETICAL/NON-OPERATIONAL.
- [ ] Scenario cannot appear as factual alert.
- [ ] Route evidence not marketed as optimization.
- [ ] Unknown freshness remains unknown; source and generation times distinguished.
- [ ] No fake Live label.
- [ ] Seeded/demo/unverified data labeled; T05/T15 gates respected.
- [ ] GPT failure has honest unavailable state without hiding evidence.
- [ ] Alert UI depends on Backend accepted transitions.
- [ ] No privileged shared secret shipped to browser.
- [ ] Empty/loading states do not fabricate evidence or unsupported job contracts.
