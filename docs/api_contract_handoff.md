# FreightPulse AI — API Contract Handoff

This document provides the exact backend API contracts for the finalized AI features. The Backend Engineer will use this to expose these capabilities to the separate Frontend repository.

All endpoints below require authentication via the `X-API-Key` header and enforce rate-limiting.

---

## 1. Carrier Summarizer

Fetches the latest carrier advisories. The AI summarization happens asynchronously via background scraping; this endpoint simply returns the already-processed structured data synchronously.

- **Endpoint**: `/carriers/advisories`
- **Method**: `GET`
- **Authentication**: `X-API-Key: <your_api_key>`
- **Query Parameters**:
  - `carrier` (optional string): Filter by carrier name.
  - `type` (optional string): Filter by advisory type.
  - `affected_lane` (optional string): Filter by affected lane.
- **Success Response** (`200 OK`):
  ```json
  {
    "advisories": [
      {
        "id": "uuid-string",
        "carrier": "Maersk",
        "advisory_type": "delay",
        "title": "Port Congestion Warning",
        "summary": "AI-generated summary of the advisory.",
        "affected_lanes": ["Asia-Europe"],
        "effective_date": "2026-08-27T00:00:00Z",
        "impact_severity": "high",
        "source_url": "https://...",
        "published_at": "2026-08-27T10:00:00Z"
      }
    ]
  }
  ```
- **UI State Guidelines**: Implement standard `Loading -> Success/Empty -> Error` states. No async polling required.

---

## 2. Grounded Rate Outlook (T07)

Numerical evidence comes from a persisted T06 RateForecast. Azure GPT-5-mini explains it; it does not generate authoritative rates, confidence, probability, or booking recommendations.

### Submit

`POST /api/v1/rates/trends/{trend_id}/outlook?source=SCFI&container_type=40ft`

- Requires an active user's `X-API-Key`; admin is not required.
- Router limit: 100 requests per 60-second fixed window per user/concrete path; Redis failure is fail-open.
- UUID `trend_id` is required. No body. Optional retry=true explicitly requests a bounded transient retry. Supply source/container together, or omit both for exactly one matching series.
- 202: `{trend_id: string, outlook_id: UUID, forecast_id: UUID, status: string}`.
- Status can already be completed/failed/unavailable when the same generation is reused. Enqueue failure also returns 202 with failed status; evidence is already persisted.
- 404: missing trend or matching forecast (explicit unavailable; no GPT or numerical generation).
- 409: ambiguous series, newer source observations, non-current model/generation, or historical/mismatched trend.
- 422: malformed UUID or partial selection. 401/429 follow existing auth/limiter behavior; unexpected failures are 500.
- HTTPException responses use `{error: {code, message, details}}`; framework request-validation errors retain FastAPI's existing validation response.

### Retrieve authoritative result

`GET /api/v1/rates/outlooks/{outlook_id}` (same auth/limit; 200 or 404, with 401/422/429/500 as applicable).

Top-level fields:

- `id`, `trend_id`, `forecast_id`, `prompt_version`, `created_at`, `completed_at`.
- `quantitative`: T06 artifact shape: `id`, `series`, `forecast`, `evidence`, `provenance`, `safety`.
- `exact_values`: `predicted_rate`, `latest_actual_rate`, `expected_change`, `expected_change_pct`. Decimal values serialize as exact strings; percentage is rounded to four decimals, null for zero actual rate. These are application-owned, never GPT output.
- `context_state`: current | superseded | historical_trend | source_unavailable.
- `context_warning`: nullable safe explanation.
- `effective_live_decision_eligible`: stored model eligibility AND non-stale input AND current context. Freshness cannot promote a historical-only model.
- `narration`: `{status, text, error_message, attempt_count, retryable, retry_after, input_evidence}`. Status is pending | generating | completed | failed | unavailable. Text/error are nullable.

Poll this GET, not the legacy lane GET. Evidence is available before narration, after AI failure, and for historical artifacts. Consumers must inspect context_state, effective eligibility, and freshness; completed text can be historical and must not be treated as current advice. The narrative is explanatory prose; structured numbers are authoritative.

### Compatibility

POST path, auth, 202, trend_id and status remain. outlook_id/forecast_id are additive. Multi-series callers must now select a series; historical/superseded requests can now conflict. These are semantic contract changes.

GET `/api/v1/rates/{lane}` remains for lane data; its legacy outlook_text/recommendation/confidence return null and its status/error are suppressed as none/null. T07 does not write RateTrend AI fields. Existing lane polling is therefore incompatible with grounded completion and must migrate to the returned outlook_id. Database columns remain for compatibility; no frontend source was changed.

No Redis narration cache is used. The persisted outlook identity is `(trend_id, forecast_id, forecast_generated_at, prompt_version)`. Source/container are bound by forecast_id. The same identity reuses completed/pending/generating artifacts; retry=true may requeue a transient failure after a 60-second cooldown, with at most three attempts on the same row. Budget/rate-limit-guard and validation failures are terminal. The scheduler never retries failed rows. T06 regeneration or a different model/artifact/prompt produces a distinct identity. Legacy v1 cache keys are never read. Stored narrative is schema-validated before exposure. input_evidence preserves the exact context supplied to the latest attempted narration, separately from current read-time freshness.

Deployment must migrate the database and restart workers together, draining legacy trend-ID jobs: the registered grounded task has a distinct task name and receives an outlook-ID; old task names are rejected. Normal AI failures reach failed state; hard worker termination can leave generating state and requires operational recovery. No new scheduling subsystem is introduced.

---

## 3. Route Brief Generator

Generates a comprehensive logistical risk brief and PDF document for a specific route.

### A. Initiate Generation
- **Endpoint**: `/route-briefs`
- **Method**: `POST`
- **Authentication**: `X-API-Key: <your_api_key>`
- **Request Body**:
  ```json
  {
    "origin": "string (required)",
    "destination": "string (required)",
    "cargo_type": "string (required)"
  }
  ```
- **Success Response** (`202 Accepted`):
  ```json
  {
    "id": "uuid-string",
    "status": "pending"
  }
  ```

### B. Poll Status
- **Endpoint**: `/route-briefs/{brief_id}/status`
- **Method**: `GET`
- **Authentication**: `X-API-Key: <your_api_key>`
- **Success Response** (`200 OK`):
  ```json
  {
    "id": "uuid-string",
    "status": "pending" // or "generating", "completed", "failed"
  }
  ```

### C. Retrieve Result
- **Endpoint**: `/route-briefs/{brief_id}`
- **Method**: `GET`
- **Authentication**: `X-API-Key: <your_api_key>`
- **Success Response** (`200 OK`):
  ```json
  {
    "id": "uuid-string",
    "origin": "Shanghai",
    "destination": "Rotterdam",
    "cargo_type": "Electronics",
    "status": "completed",
    "brief_markdown": "# AI Generated Route Brief...",
    "recommendation": "Proceed with caution",
    "risk_level": "moderate",
    "error_message": null,
    "created_at": "2026-08-27T12:00:00Z"
  }
  ```

### D. Download PDF
- **Endpoint**: `/route-briefs/{brief_id}/pdf`
- **Method**: `GET`
- **Authentication**: `X-API-Key: <your_api_key>`
- **Success Response** (`200 OK`): `application/pdf` binary stream.
- **Error Responses**:
  - `409 Conflict`: Route brief is still generating.
  - `404 Not Found`: PDF generation failed or unavailable.
  
- **UI State Guidelines**: `Submitted -> Processing (Polling /status) -> Completed (Fetch Result/PDF) / Failed`. Handle graceful degradation (if PDF is 404 but markdown exists, show markdown).
