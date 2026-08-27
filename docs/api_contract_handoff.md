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

## 2. Rate Outlook Narrator

Generates a strategic rate outlook for a specific trend ID asynchronously using Azure OpenAI.

- **Endpoint**: `/rates/trends/{trend_id}/outlook`
- **Method**: `POST`
- **Authentication**: `X-API-Key: <your_api_key>`
- **Path Parameters**:
  - `trend_id` (UUID, required): The ID of the existing RateTrend.
- **Success Response** (`202 Accepted`):
  ```json
  {
    "trend_id": "uuid-string",
    "status": "pending"
  }
  ```
- **Error Responses**:
  - `404 Not Found`: Rate trend not found.
- **Async Lifecycle / Polling**:
  After receiving a `202`, the frontend must poll the existing `GET /rates/{lane}` endpoint. The `trend` object in that response will reflect the async status:
  - `status`: `"pending" | "failed" | "completed"`
  - `outlook_text`: Populated when `completed`.
  - `error_message`: Populated when `failed`.
- **UI State Guidelines**: `Submitted -> Processing (Polling) -> Completed (Show Outlook) / Failed (Show Error)`.

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
